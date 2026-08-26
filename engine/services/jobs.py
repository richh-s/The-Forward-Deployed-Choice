"""Job handlers — the asynchronous pipeline.

enrich_prospect → workspace enrichment source → prospect.signals, 'enriched'
compose_draft   → compose + judge (one regeneration on a low score) → Draft
                  (auto-approve per campaign policy → enqueue send_draft)
send_draft      → policy-checked send. Outreach drafts: email send, prospect
                  stage/touch update, follow-up scheduling, HubSpot sync
                  enqueue. Reply drafts: channel-appropriate send only.
inbound_message → reply agent → suppression / escalation → reply Draft
                  (held for approval unless the workspace opts into
                  auto-send; escalated replies are always held)
sync_hubspot_contact, hubspot_mark_booked → CRM writes with retries
"""
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import get_settings
from engine.models import (
    AuditLog,
    Booking,
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
from engine.services import enrichment as enrichment_svc
from engine.services import hubspot as hubspot_svc
from engine.services import judge as judge_svc
from engine.services import reply_agent, slack
from engine.services.emailer import send_email, send_internal_email
from engine.services.smser import send_sms
from engine.services.suppression import SendBlocked, is_suppressed, suppress
from engine.services.whatsapp import send_whatsapp

logger = logging.getLogger(__name__)

REGENERATION_SCORE = 0.6  # below this, try composing once more with feedback


async def _load(db: AsyncSession, model, obj_id: str, label: str):
    obj = await db.get(model, obj_id)
    if obj is None:
        raise RuntimeError(f"{label} {obj_id} not found")
    return obj


async def _load_scoped(db: AsyncSession, payload: dict):
    """Load (workspace, prospect) from a job payload and verify they belong
    together — defense in depth against a forged/mismatched payload."""
    workspace = await _load(db, Workspace, payload["workspace_id"], "workspace")
    prospect = await _load(db, Prospect, payload["prospect_id"], "prospect")
    if prospect.workspace_id != workspace.id:
        raise RuntimeError(
            f"Prospect {prospect.id} does not belong to workspace {workspace.id}"
        )
    return workspace, prospect


@job_handler("enrich_prospect")
async def handle_enrich_prospect(db: AsyncSession, job: Job) -> None:
    workspace, prospect = await _load_scoped(db, job.payload)
    if prospect.stage != "new":
        return  # already enriched or advanced — nothing to do
    await enrichment_svc.enrich_prospect(
        db, workspace, prospect,
        final_attempt=job.attempts >= job.max_attempts,
    )


@job_handler("compose_draft")
async def handle_compose_draft(db: AsyncSession, job: Job) -> None:
    p = job.payload
    workspace, prospect = await _load_scoped(db, p)
    campaign = await db.get(Campaign, p["campaign_id"]) if p.get("campaign_id") else None
    if campaign is not None and campaign.workspace_id != workspace.id:
        raise RuntimeError("Campaign/workspace mismatch in job payload")
    touch_number = int(p.get("touch_number", 1))
    angle = p.get("angle", "")

    # Release the transaction before the (potentially minutes-long) LLM
    # calls — don't hold a DB connection idle-in-transaction.
    await db.commit()

    draft_fields, cost = await compose_svc.compose_outreach(
        db, workspace, prospect, campaign, touch_number=touch_number, angle=angle
    )
    score, feedback, judge_cost, dimensions = await judge_svc.judge_draft(
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
        score, feedback, jc2, dimensions = await judge_svc.judge_draft(
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
        # The original angle (not the regeneration feedback) is the
        # learning-loop attribution key.
        angle=angle.strip()[:200],
        avg_confidence=draft_fields["avg_confidence"],
        judge_score=score,
        judge_scores=dimensions,
        judge_feedback=feedback,
        grounding_notes=str(draft_fields.get("grounding_notes", "")),
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
    else:
        await slack.notify(
            db, workspace.id,
            f"📝 Draft for *{prospect.name or prospect.email}* "
            f"({prospect.company or 'unknown company'}) awaits review — "
            f"judge {score:.2f}. {get_settings().base_url}/approvals",
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

    if prospect.workspace_id != workspace.id:
        raise RuntimeError("Draft prospect/workspace mismatch")

    try:
        if draft.kind == "reply" and draft.channel == "sms" and prospect.phone:
            message = await send_sms(
                db, workspace, prospect,
                to_phone=prospect.phone, body=draft.body,
            )
        elif (
            draft.kind == "reply"
            and draft.channel == "whatsapp"
            and prospect.phone
        ):
            message = await send_whatsapp(
                db, workspace, prospect,
                to_phone=prospect.phone, body=draft.body,
            )
        else:
            message = await send_email(
                db,
                workspace,
                prospect,
                subject=draft.subject or "Re: your reply",
                body=draft.body,
                # LLM cost stays on the Draft row (kill-switch/analytics sum
                # drafts + messages) — copying it here would double-count.
                # Resend-side dedup: a retry after a post-send DB failure
                # must not deliver this draft a second time.
                idempotency_key=f"draft-{draft.id}",
            )
    except SendBlocked as exc:
        draft.status = "failed"
        draft.reject_reason = f"blocked: {exc.reason}"
        logger.warning("Draft %s send blocked: %s", draft.id, exc.reason)
        return

    draft.status = "sent"
    draft.sent_message_id = message.id

    if draft.kind == "reply":
        # A reply is not an outreach touch: it never advances the sequence,
        # touch count, or stage (intent handling already did that inbound).
        return

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
        # Per-draft, not per-prospect: later touches must be able to enqueue
        # their own sync (sync_contact itself is idempotent on HubSpot).
        idempotency_key=f"hs_contact:{draft.id}",
    )


@job_handler("inbound_message")
async def handle_inbound_message(db: AsyncSession, job: Job) -> None:
    p = job.payload
    workspace, prospect = await _load_scoped(db, p)
    channel = p["channel"]
    text = p["text"]

    # Release the transaction across the LLM call (see handle_compose_draft).
    await db.commit()

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
            await suppress(db, workspace.id, "whatsapp", prospect.phone, "opt_out")
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
        await slack.notify(
            db, workspace.id,
            f"🚨 Escalation from *{prospect.name or prospect.email}*: "
            f"{result['escalation_reason']} — "
            f"{get_settings().base_url}/prospects/{prospect.id}",
        )

    reply_text = (result.get("reply") or "").strip()
    if not reply_text:
        return

    # The reply agent's output is model text produced from attacker-
    # controllable inbound content — it goes through the same Draft gate as
    # outreach. Escalations are ALWAYS held for a human, and workspaces only
    # auto-send after explicitly opting out of reply approval.
    hold = workspace.require_reply_approval or bool(result["escalate"])
    if channel in ("sms", "whatsapp") and prospect.phone:
        reply_channel = channel  # answer on the channel they wrote on
    else:
        reply_channel = "email"
    draft = Draft(
        workspace_id=workspace.id,
        prospect_id=prospect.id,
        kind="reply",
        channel=reply_channel,
        subject="" if reply_channel in ("sms", "whatsapp") else "Re: your reply",
        body=reply_text,
        touch_number=0,
        compose_cost_usd=result.get("cost_usd", 0.0),
        status="pending_review" if hold else "approved",
        auto_approved=not hold,
    )
    db.add(draft)
    await db.flush()
    if not hold:
        await enqueue(
            db,
            "send_draft",
            {"draft_id": draft.id},
            workspace_id=workspace.id,
            idempotency_key=f"send_draft:{draft.id}",
        )
    else:
        await slack.notify(
            db, workspace.id,
            f"💬 Reply to *{prospect.name or prospect.email}* awaits review "
            f"({intent} intent, {reply_channel}) — "
            f"{get_settings().base_url}/approvals",
        )


@job_handler("booking_reminder")
async def handle_booking_reminder(db: AsyncSession, job: Job) -> None:
    """SMS no-show reduction: remind the prospect ahead of their booking.
    Transactional message — bypasses the touch ceiling and daily caps but
    NEVER a suppression."""
    p = job.payload
    workspace, prospect = await _load_scoped(db, p)
    booking = await _load(db, Booking, p["booking_id"], "booking")
    if booking.workspace_id != workspace.id:
        raise RuntimeError("Booking/workspace mismatch in job payload")
    if booking.status not in ("confirmed", "rescheduled"):
        return  # cancelled since the reminder was scheduled
    from engine.models import as_aware

    start = as_aware(booking.start_time)
    if start is None or start <= utcnow():
        return  # nothing to remind about
    if not prospect.phone:
        return
    if await is_suppressed(db, workspace.id, "sms", prospect.phone):
        return

    company = (workspace.playbook or {}).get("company_name", workspace.name)
    when = start.strftime("%a %b %-d at %H:%M UTC")
    try:
        await send_sms(
            db, workspace, prospect,
            to_phone=prospect.phone,
            body=(
                f"Reminder: your call with {company} is {when}. "
                "Reply STOP to opt out."
            ),
            # Transactional: the reminder must not burn an outreach touch or
            # get blocked by the daily cap (suppression checked above).
            skip_policy_checks=True,
        )
    except SendBlocked as exc:
        logger.warning(
            "Booking reminder blocked for %s: %s", booking.id, exc.reason
        )
        return
    booking.meta = {**(booking.meta or {}), "reminder_sent_at": utcnow().isoformat()}


@job_handler("weekly_digest")
async def handle_weekly_digest(db: AsyncSession, job: Job) -> None:
    """Weekly ROI digest to the workspace's admins (and Slack): what the
    engine did last week and what it cost."""
    from sqlalchemy import select

    from engine.models import User
    from engine.services.killswitch import compute_metrics

    workspace = await _load(db, Workspace, job.payload["workspace_id"], "workspace")
    metrics = await compute_metrics(db, workspace)
    booked = len((await db.execute(
        select(Booking.id).where(
            Booking.workspace_id == workspace.id,
            Booking.status.in_(["confirmed", "rescheduled"]),
            Booking.created_at >= utcnow() - timedelta(days=7),
        )
    )).all())

    cost = metrics["llm_cost_usd"]
    cost_per_meeting = f"${cost / booked:.2f}" if booked else "—"
    lines = [
        f"Weekly digest for {workspace.name}",
        "",
        f"Emails sent:        {metrics['emails_out']}",
        f"SMS sent:           {metrics['sms_out']}",
        f"Qualified leads:    {metrics['qualified_leads']}",
        f"Meetings booked:    {booked}",
        f"Bounce rate:        {metrics['bounce_rate']:.1%}",
        f"Opt-out rate:       {metrics['opt_out_rate']:.1%}",
        f"LLM spend:          ${cost:.2f}",
        f"Cost per meeting:   {cost_per_meeting}",
        "",
        f"Full analytics: {get_settings().base_url}/analytics",
    ]
    body = "\n".join(lines)

    admins = (await db.execute(
        select(User).where(
            User.workspace_id == workspace.id,
            User.role == "admin",
            User.is_active.is_(True),
        )
    )).scalars().all()
    subject = f"{workspace.name} — weekly outreach digest"
    delivered = 0
    for admin in admins:
        try:
            await send_internal_email(
                db, workspace, to_email=admin.email, subject=subject, body=body
            )
            delivered += 1
        except SendBlocked as exc:
            # No Resend credentials / sending identity yet — Slack (below)
            # may still land it; don't retry the job for this.
            logger.info("Digest email skipped for %s: %s", workspace.id, exc.reason)
            break
    await slack.notify(db, workspace.id, f"📊 {subject}\n```{body}```")
    logger.info(
        "Weekly digest for ws=%s: %d email(s), booked=%d",
        workspace.id, delivered, booked,
    )


@job_handler("sync_hubspot_contact")
async def handle_sync_hubspot(db: AsyncSession, job: Job) -> None:
    workspace, prospect = await _load_scoped(db, job.payload)
    await hubspot_svc.sync_contact(db, workspace, prospect)


@job_handler("hubspot_mark_booked")
async def handle_hubspot_booked(db: AsyncSession, job: Job) -> None:
    p = job.payload
    workspace, prospect = await _load_scoped(db, p)
    await hubspot_svc.mark_meeting_booked(
        db,
        workspace,
        prospect,
        booking_time=p.get("booking_time", ""),
        booking_uid=p.get("booking_uid", ""),
    )
