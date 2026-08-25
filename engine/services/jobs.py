"""Job handlers — the asynchronous pipeline.

compose_draft   → compose + judge (one regeneration on a low score) → Draft
                  (auto-approve per campaign policy → enqueue send_draft)
send_draft      → policy-checked email send, prospect stage/touch update,
                  follow-up scheduling, HubSpot sync enqueue
inbound_message → reply agent → suppression / reply send / escalation
sync_hubspot_contact, hubspot_mark_booked → CRM writes with retries
"""
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import (
    AuditLog,
    Campaign,
    Draft,
    Job,
    Message,
    Prospect,
    Workspace,
    utcnow,
)
from engine.queue import enqueue, job_handler
from engine.services import compose as compose_svc
from engine.services import hubspot as hubspot_svc
from engine.services import judge as judge_svc
from engine.services import reply_agent
from engine.services.emailer import send_email
from engine.services.smser import send_sms
from engine.services.suppression import SendBlocked, suppress

logger = logging.getLogger(__name__)

REGENERATION_SCORE = 0.6  # below this, try composing once more with feedback


async def _load(db: AsyncSession, model, obj_id: str, label: str):
    obj = await db.get(model, obj_id)
    if obj is None:
        raise RuntimeError(f"{label} {obj_id} not found")
    return obj


@job_handler("compose_draft")
async def handle_compose_draft(db: AsyncSession, job: Job) -> None:
    p = job.payload
    workspace = await _load(db, Workspace, p["workspace_id"], "workspace")
    prospect = await _load(db, Prospect, p["prospect_id"], "prospect")
    campaign = await db.get(Campaign, p["campaign_id"]) if p.get("campaign_id") else None
    touch_number = int(p.get("touch_number", 1))
    angle = p.get("angle", "")

    draft_fields, cost = await compose_svc.compose_outreach(
        db, workspace, prospect, campaign, touch_number=touch_number, angle=angle
    )
    score, feedback, judge_cost = await judge_svc.judge_draft(
        db,
        workspace,
        subject=draft_fields["subject"],
        body=draft_fields["body"],
        mode=draft_fields["mode_used"],
        avg_confidence=draft_fields["avg_confidence"],
        signals=prospect.signals or {},
    )
    if score < REGENERATION_SCORE:
        regen_angle = (
            f"{angle}\nA previous draft failed review with this feedback — "
            f"fix it: {feedback}"
        )
        draft_fields, cost2 = await compose_svc.compose_outreach(
            db, workspace, prospect, campaign,
            touch_number=touch_number, angle=regen_angle,
        )
        cost += cost2
        score, feedback, jc2 = await judge_svc.judge_draft(
            db,
            workspace,
            subject=draft_fields["subject"],
            body=draft_fields["body"],
            mode=draft_fields["mode_used"],
            avg_confidence=draft_fields["avg_confidence"],
            signals=prospect.signals or {},
        )
        judge_cost += jc2

    draft = Draft(
        workspace_id=workspace.id,
        prospect_id=prospect.id,
        campaign_id=campaign.id if campaign else None,
        channel="email",
        subject=draft_fields["subject"],
        body=draft_fields["body"],
        mode=draft_fields["mode_used"],
        avg_confidence=draft_fields["avg_confidence"],
        judge_score=score,
        judge_feedback=feedback,
        touch_number=touch_number,
        compose_cost_usd=cost + judge_cost,
    )
    auto_ok = (
        campaign is not None
        and not campaign.require_approval
        and score >= campaign.auto_approve_score
    )
    if auto_ok:
        draft.status = "approved"
        draft.auto_approved = True
    db.add(draft)
    prospect.avg_confidence = draft_fields["avg_confidence"]
    if prospect.stage in ("new", "enriched"):
        prospect.stage = "queued"
    await db.flush()

    if auto_ok:
        await enqueue(
            db,
            "send_draft",
            {"draft_id": draft.id},
            workspace_id=workspace.id,
            idempotency_key=f"send_draft:{draft.id}",
        )


@job_handler("send_draft")
async def handle_send_draft(db: AsyncSession, job: Job) -> None:
    p = job.payload
    draft = await _load(db, Draft, p["draft_id"], "draft")
    if draft.status not in ("approved",):
        logger.info("Draft %s is %s — not sending", draft.id, draft.status)
        return
    workspace = await _load(db, Workspace, draft.workspace_id, "workspace")
    prospect = await _load(db, Prospect, draft.prospect_id, "prospect")

    try:
        message = await send_email(
            db,
            workspace,
            prospect,
            subject=draft.subject,
            body=draft.body,
            compose_cost_usd=draft.compose_cost_usd,
        )
    except SendBlocked as exc:
        draft.status = "failed"
        draft.reject_reason = f"blocked: {exc.reason}"
        logger.warning("Draft %s send blocked: %s", draft.id, exc.reason)
        return

    draft.status = "sent"
    draft.sent_message_id = message.id
    prospect.stage = "contacted"
    prospect.touch_count += 1
    prospect.last_outbound_at = utcnow()

    campaign = await db.get(Campaign, draft.campaign_id) if draft.campaign_id else None
    steps = (campaign.sequence if campaign else None) or []
    if draft.touch_number <= len(steps):
        step = steps[draft.touch_number - 1]
        prospect.next_followup_at = utcnow() + timedelta(
            days=float(step.get("day_offset", 3))
        )
    else:
        prospect.next_followup_at = None

    await enqueue(
        db,
        "sync_hubspot_contact",
        {"workspace_id": workspace.id, "prospect_id": prospect.id},
        workspace_id=workspace.id,
        idempotency_key=f"hs_contact:{prospect.id}",
    )


@job_handler("inbound_message")
async def handle_inbound_message(db: AsyncSession, job: Job) -> None:
    p = job.payload
    workspace = await _load(db, Workspace, p["workspace_id"], "workspace")
    prospect = await _load(db, Prospect, p["prospect_id"], "prospect")
    channel = p["channel"]
    text = p["text"]

    result = await reply_agent.handle_inbound(
        db, workspace, prospect, channel=channel, inbound_text=text
    )
    intent = result["intent"]

    # Record the classification on the inbound message row.
    if p.get("message_id"):
        inbound = await db.get(Message, p["message_id"])
        if inbound is not None:
            inbound.intent = intent

    if intent == "cold":
        await suppress(db, workspace.id, "email", prospect.email, "opt_out")
        if prospect.phone:
            await suppress(db, workspace.id, "sms", prospect.phone, "opt_out")
        prospect.stage = "opted_out"
        prospect.next_followup_at = None
        return

    if intent == "warm":
        prospect.stage = "warm"
    elif prospect.stage == "contacted":
        prospect.stage = "replied"
    prospect.next_followup_at = None  # replied — stop the automatic sequence

    if result["escalate"]:
        db.add(
            AuditLog(
                workspace_id=workspace.id,
                action="escalation",
                detail={
                    "prospect_id": prospect.id,
                    "reason": result["escalation_reason"],
                    "inbound": text[:500],
                },
            )
        )

    reply_text = (result.get("reply") or "").strip()
    if not reply_text:
        return
    try:
        if channel == "sms" and prospect.phone:
            await send_sms(
                db, workspace, prospect, to_phone=prospect.phone, body=reply_text
            )
        else:
            await send_email(
                db,
                workspace,
                prospect,
                subject="Re: your reply",
                body=reply_text,
                compose_cost_usd=result.get("cost_usd", 0.0),
            )
    except SendBlocked as exc:
        logger.warning(
            "Reply to prospect %s blocked: %s", prospect.id, exc.reason
        )


@job_handler("sync_hubspot_contact")
async def handle_sync_hubspot(db: AsyncSession, job: Job) -> None:
    p = job.payload
    workspace = await _load(db, Workspace, p["workspace_id"], "workspace")
    prospect = await _load(db, Prospect, p["prospect_id"], "prospect")
    await hubspot_svc.sync_contact(db, workspace, prospect)


@job_handler("hubspot_mark_booked")
async def handle_hubspot_booked(db: AsyncSession, job: Job) -> None:
    p = job.payload
    workspace = await _load(db, Workspace, p["workspace_id"], "workspace")
    prospect = await _load(db, Prospect, p["prospect_id"], "prospect")
    await hubspot_svc.mark_meeting_booked(
        db,
        workspace,
        prospect,
        booking_time=p.get("booking_time", ""),
        booking_uid=p.get("booking_uid", ""),
    )
