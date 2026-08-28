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
from engine.queue import PermanentJobError, enqueue, job_handler
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
        # Permanent: a deleted row (e.g. GDPR erasure) will still be gone on
        # every retry — don't burn five attempts logging errors about it.
        raise PermanentJobError(f"{label} {obj_id} not found")
    return obj


async def _load_scoped(db: AsyncSession, payload: dict):
    """Load (workspace, prospect) from a job payload and verify they belong
    together — defense in depth against a forged/mismatched payload."""
    workspace = await _load(db, Workspace, payload["workspace_id"], "workspace")
    prospect = await _load(db, Prospect, payload["prospect_id"], "prospect")
    if prospect.workspace_id != workspace.id:
        raise PermanentJobError(
            f"Prospect {prospect.id} does not belong to workspace {workspace.id}"
        )
    return workspace, prospect


@job_handler("slack_notify")
async def handle_slack_notify(db: AsyncSession, job: Job) -> None:
    """Operator pings (Slack AND Telegram, each best-effort) run as their
    own job, enqueued atomically with the work they announce — notifying
    mid-transaction would fire for work that later rolls back, and fire
    again on every retry."""
    from engine.services import telegram as telegram_svc

    await slack.notify(db, job.payload["workspace_id"], job.payload["text"])
    await telegram_svc.notify_operator(
        db, job.payload["workspace_id"], job.payload["text"]
    )


@job_handler("telegram_raw_send")
async def handle_telegram_raw_send(db: AsyncSession, job: Job) -> None:
    """Bot utility replies (onboarding hints, /stop confirmations) — the
    person just messaged the bot, so this is a service-window response, not
    outreach; policy checks don't apply."""
    from engine.services import telegram as telegram_svc
    from engine.services.credentials import get_credentials

    creds = await get_credentials(
        db, job.payload["workspace_id"], "telegram"
    ) or {}
    token = creds.get("bot_token")
    if not token:
        return
    await telegram_svc._tg_call(token, "sendMessage", {
        "chat_id": job.payload["chat_id"], "text": job.payload["text"],
    })


async def notify_slack(
    db: AsyncSession, workspace_id: str, text: str,
    *, idempotency_key: str | None = None,
) -> None:
    await enqueue(
        db,
        "slack_notify",
        {"workspace_id": workspace_id, "text": text},
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
        max_attempts=2,  # a notification isn't worth five retries
    )


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
    if prospect.stage == "opted_out":
        return  # opted out since this compose was queued — spend nothing
    campaign = await db.get(Campaign, p["campaign_id"]) if p.get("campaign_id") else None
    if campaign is not None and campaign.workspace_id != workspace.id:
        raise PermanentJobError("Campaign/workspace mismatch in job payload")
    touch_number = int(p.get("touch_number", 1))
    # First touches carry no angle in the payload — fall back to the
    # campaign-level angle the operator set (Settings → "Campaign angle").
    angle = p.get("angle") or (
        (campaign.playbook or {}).get("angle", "") if campaign else ""
    )
    compose_angle = angle
    if p.get("rejection_feedback"):
        compose_angle = (
            f"{angle}\nA previous draft was rejected by a human reviewer — "
            f"address this feedback: {p['rejection_feedback']}"
        )

    # Resolve the model/key before releasing the transaction, then commit so
    # the (potentially minutes-long) LLM calls never hold a DB connection
    # idle-in-transaction.
    await db.commit()

    draft_fields, cost = await compose_svc.compose_outreach(
        db, workspace, prospect, campaign,
        touch_number=touch_number, angle=compose_angle,
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
            f"{compose_angle}\nA previous draft failed review with this "
            f"feedback — fix it: {feedback}"
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
        await notify_slack(
            db, workspace.id,
            f"📝 Draft for *{prospect.name or prospect.email}* "
            f"({prospect.company or 'unknown company'}) awaits review — "
            f"judge {score:.2f}. {get_settings().base_url}/approvals",
            idempotency_key=f"slack:draft:{draft.id}",
        )


@job_handler("send_draft")
async def handle_send_draft(db: AsyncSession, job: Job) -> None:
    p = job.payload
    draft = await _load(db, Draft, p["draft_id"], "draft")
    if draft.status == "sending":
        # A previous attempt crashed between the provider accepting the
        # message and the commit. SMS/WhatsApp have no provider-side
        # idempotency key (unlike Resend), so re-sending could deliver
        # twice — stop and let a human verify with the provider.
        raise PermanentJobError(
            f"Draft {draft.id} is stuck in 'sending' — a previous attempt "
            "may already have delivered. Verify with the provider, then set "
            "the draft back to approved to retry."
        )
    if draft.status not in ("approved",):
        logger.info("Draft %s is %s — not sending", draft.id, draft.status)
        return
    workspace = await _load(db, Workspace, draft.workspace_id, "workspace")
    prospect = await _load(db, Prospect, draft.prospect_id, "prospect")

    if prospect.workspace_id != workspace.id:
        raise PermanentJobError("Draft prospect/workspace mismatch")

    is_reply = draft.kind == "reply"
    try:
        if is_reply and draft.channel == "sms" and prospect.phone:
            # Mark-and-commit before the provider call so a crash afterwards
            # is detected (see the 'sending' check above) instead of
            # silently double-delivering on retry.
            draft.status = "sending"
            await db.commit()
            message = await send_sms(
                db, workspace, prospect,
                to_phone=prospect.phone, body=draft.body, is_reply=True,
            )
        elif is_reply and draft.channel == "whatsapp" and prospect.phone:
            draft.status = "sending"
            await db.commit()
            message = await send_whatsapp(
                db, workspace, prospect,
                to_phone=prospect.phone, body=draft.body, is_reply=True,
            )
        elif (
            is_reply
            and draft.channel == "telegram"
            and prospect.telegram_chat_id
        ):
            from engine.services.telegram import send_telegram

            draft.status = "sending"
            await db.commit()
            message = await send_telegram(
                db, workspace, prospect, body=draft.body, is_reply=True,
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
                is_reply=is_reply,
            )
    except SendBlocked as exc:
        draft.status = "failed"
        draft.reject_reason = f"blocked: {exc.reason}"
        logger.warning("Draft %s send blocked: %s", draft.id, exc.reason)
        return
    except PermanentJobError as exc:
        # Provider definitively rejected the recipient — nothing was
        # delivered, so record the outcome on the draft and let the job die.
        draft.status = "failed"
        draft.reject_reason = f"provider rejected: {exc}"[:400]
        await db.commit()
        raise

    draft.status = "sent"
    draft.sent_message_id = message.id

    # Every conversation event lands on the CRM timeline (challenge
    # requirement) — the handler no-ops when HubSpot isn't configured.
    await enqueue(
        db,
        "hubspot_log_event",
        {
            "workspace_id": workspace.id,
            "prospect_id": prospect.id,
            "message_id": message.id,
        },
        workspace_id=workspace.id,
        idempotency_key=f"hs_note:{message.id}",
    )

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

    # Record the classification on the inbound message row, and log the
    # inbound event to the CRM timeline.
    if p.get("message_id"):
        inbound = await db.get(Message, p["message_id"])
        if inbound is not None:
            inbound.intent = intent
        await enqueue(
            db,
            "hubspot_log_event",
            {
                "workspace_id": workspace.id,
                "prospect_id": prospect.id,
                "message_id": p["message_id"],
            },
            workspace_id=workspace.id,
            idempotency_key=f"hs_note:{p['message_id']}",
        )

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
        await notify_slack(
            db, workspace.id,
            f"🚨 Escalation from *{prospect.name or prospect.email}*: "
            f"{result['escalation_reason']} — "
            f"{get_settings().base_url}/prospects/{prospect.id}",
            idempotency_key=f"slack:esc:{p.get('message_id') or job.id}",
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
    elif channel == "telegram" and prospect.telegram_chat_id:
        reply_channel = "telegram"
    else:
        reply_channel = "email"
    draft = Draft(
        workspace_id=workspace.id,
        prospect_id=prospect.id,
        kind="reply",
        channel=reply_channel,
        subject="" if reply_channel in ("sms", "whatsapp", "telegram") else "Re: your reply",
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
        await notify_slack(
            db, workspace.id,
            f"💬 Reply to *{prospect.name or prospect.email}* awaits review "
            f"({intent} intent, {reply_channel}) — "
            f"{get_settings().base_url}/approvals",
            idempotency_key=f"slack:reply:{draft.id}",
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
    # Progress is committed after each recipient so a retry (e.g. admin #3's
    # send failed transiently) never re-emails admins #1 and #2.
    already_sent = set(job.payload.get("digest_sent") or [])
    delivered = 0
    for admin in admins:
        if admin.email in already_sent:
            continue
        try:
            await send_internal_email(
                db, workspace, to_email=admin.email, subject=subject, body=body
            )
            delivered += 1
            already_sent.add(admin.email)
            job.payload["digest_sent"] = sorted(already_sent)
            await db.commit()
        except SendBlocked as exc:
            # No Resend credentials / sending identity yet — Slack (below)
            # may still land it; don't retry the job for this.
            logger.info("Digest email skipped for %s: %s", workspace.id, exc.reason)
            break
    await notify_slack(
        db, workspace.id, f"📊 {subject}\n```{body}```",
        idempotency_key=f"slack:digest:{job.id}",
    )
    logger.info(
        "Weekly digest for ws=%s: %d email(s), booked=%d",
        workspace.id, delivered, booked,
    )


@job_handler("sync_hubspot_contact")
async def handle_sync_hubspot(db: AsyncSession, job: Job) -> None:
    workspace, prospect = await _load_scoped(db, job.payload)
    await hubspot_svc.sync_contact(db, workspace, prospect)


@job_handler("hubspot_log_event")
async def handle_hubspot_log_event(db: AsyncSession, job: Job) -> None:
    workspace, prospect = await _load_scoped(db, job.payload)
    message = await db.get(Message, job.payload["message_id"])
    if message is None or message.workspace_id != workspace.id:
        return  # message purged or mismatched — nothing to log
    await hubspot_svc.log_conversation_event(db, workspace, prospect, message)


@job_handler("voice_schedule_link")
async def handle_voice_schedule_link(db: AsyncSession, job: Job) -> None:
    """Caller pressed 2 in the IVR: email them the booking link. Responsive
    to an inbound call, so it rides the reply policy (no touch burn)."""
    from engine.services.booking import booking_url_for

    workspace, prospect = await _load_scoped(db, job.payload)
    url = booking_url_for(workspace, prospect)
    if url is None:
        # No booking link configured — hand the promise to a human instead
        # of silently dropping it.
        db.add(AuditLog(
            workspace_id=workspace.id,
            action="escalation",
            detail={
                "prospect_id": prospect.id,
                "reason": "Caller asked for a scheduling link (IVR digit 2) "
                "but no Cal.com event URL is configured",
            },
        ))
        await notify_slack(
            db, workspace.id,
            f"📞 *{prospect.name or prospect.email}* asked for a scheduling "
            "link on a call, but no Cal.com event URL is configured — "
            "follow up manually.",
            idempotency_key=f"slack:voicelink:{job.id}",
        )
        return
    company = (workspace.playbook or {}).get("company_name", workspace.name)
    try:
        await send_email(
            db, workspace, prospect,
            subject=f"Scheduling link from {company}",
            body=(
                f"Hi {prospect.name or 'there'},\n\n"
                "As requested on the call just now, here is the link to book "
                f"a time that suits you:\n\n{url}\n\n"
                f"— {company}"
            ),
            idempotency_key=f"voice-link-{job.id}",
            is_reply=True,
        )
    except SendBlocked as exc:
        logger.warning(
            "Voice scheduling link blocked for %s: %s", prospect.id, exc.reason
        )


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
