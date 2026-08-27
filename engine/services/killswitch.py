"""Kill-switch: computes rolling-window health metrics per workspace and
auto-pauses outbound when any threshold is breached.

Implements the policy that previously existed only in the README: metrics over
a rolling window; a breach pauses the workspace and records why; a human must
review and resume from Settings.
"""
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.config import get_settings
from engine.models import (
    AuditLog,
    Draft,
    Message,
    Prospect,
    Suppression,
    Workspace,
    utcnow,
)

logger = logging.getLogger(__name__)


async def compute_metrics(
    db: AsyncSession, workspace: Workspace, *, since=None
) -> dict:
    settings = get_settings()
    window_start = utcnow() - timedelta(days=settings.killswitch_window_days)
    since = max(since, window_start) if since is not None else window_start

    async def _count(*conds) -> int:
        row = await db.execute(
            select(func.count()).select_from(Message).where(
                Message.workspace_id == workspace.id,
                Message.created_at >= since,
                *conds,
            )
        )
        return int(row.scalar_one())

    emails_out = await _count(Message.channel == "email", Message.direction == "out")
    sms_out = await _count(Message.channel == "sms", Message.direction == "out")
    bounced = await _count(
        Message.channel == "email", Message.status.in_(["bounced", "complained"])
    )
    opt_outs = int((await db.execute(
        select(func.count()).select_from(Suppression).where(
            Suppression.workspace_id == workspace.id,
            Suppression.reason == "opt_out",
            Suppression.created_at >= since,
        )
    )).scalar_one())
    # LLM spend where it is incurred: compose+judge cost lives on the Draft
    # (counted whether or not the draft is ever sent — a compose→reject loop
    # must still trip the ceiling); reply-agent cost lives on the Message.
    # Sent drafts no longer copy their cost onto the Message, so the two
    # sums don't double-count.
    draft_cost = float((await db.execute(
        select(func.coalesce(func.sum(Draft.compose_cost_usd), 0.0)).where(
            Draft.workspace_id == workspace.id, Draft.created_at >= since
        )
    )).scalar_one())
    message_cost = float((await db.execute(
        select(func.coalesce(func.sum(Message.cost_usd), 0.0)).where(
            Message.workspace_id == workspace.id, Message.created_at >= since
        )
    )).scalar_one())
    llm_cost = draft_cost + message_cost
    qualified = int((await db.execute(
        select(func.count()).select_from(Prospect).where(
            Prospect.workspace_id == workspace.id,
            Prospect.stage.in_(["warm", "booked"]),
            Prospect.updated_at >= since,
        )
    )).scalar_one())

    total_out = emails_out + sms_out
    return {
        "window_days": settings.killswitch_window_days,
        "emails_out": emails_out,
        "sms_out": sms_out,
        "bounce_rate": (bounced / emails_out) if emails_out else 0.0,
        "opt_out_rate": (opt_outs / total_out) if total_out else 0.0,
        "qualified_leads": qualified,
        "llm_cost_usd": round(llm_cost, 4),
        "cost_per_qualified_lead": (llm_cost / qualified) if qualified else 0.0,
    }


def _thresholds(workspace: Workspace) -> dict:
    settings = get_settings()
    overrides = workspace.killswitch or {}
    return {
        "opt_out_rate": float(
            overrides.get("opt_out_rate", settings.killswitch_opt_out_rate)
        ),
        "bounce_rate": float(
            overrides.get("bounce_rate", settings.killswitch_bounce_rate)
        ),
        "cost_per_qualified_lead": float(
            overrides.get(
                "cost_per_qualified_lead",
                settings.killswitch_cost_per_qualified_lead_usd,
            )
        ),
        "max_llm_cost_usd": float(
            overrides.get(
                "max_llm_cost_usd", settings.killswitch_max_llm_cost_usd
            )
        ),
    }


# Rate thresholds are meaningless on a handful of sends; require a floor of
# activity before a breach can trip the switch.
MIN_SENDS_FOR_RATES = 20


async def evaluate_killswitch(db: AsyncSession, workspace: Workspace) -> list[str]:
    """Check thresholds; pause the workspace on breach. Returns breach list."""
    if workspace.outbound_paused:
        return []  # already paused — nothing to trip, nothing to re-notify
    # Resume watermark: an admin resume means "I reviewed this breach". Only
    # data since the last resume counts, otherwise the same rolling window
    # re-trips the switch within 60 seconds and resume is impossible.
    last_resume = (await db.execute(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.workspace_id == workspace.id,
            AuditLog.action == "outbound_resumed",
        )
    )).scalar_one()
    from engine.models import as_aware

    metrics = await compute_metrics(db, workspace, since=as_aware(last_resume))
    thresholds = _thresholds(workspace)
    breaches: list[str] = []

    total_out = metrics["emails_out"] + metrics["sms_out"]
    if total_out >= MIN_SENDS_FOR_RATES:
        if metrics["opt_out_rate"] > thresholds["opt_out_rate"]:
            breaches.append(
                f"opt_out_rate {metrics['opt_out_rate']:.1%} > "
                f"{thresholds['opt_out_rate']:.1%}"
            )
        if metrics["bounce_rate"] > thresholds["bounce_rate"]:
            breaches.append(
                f"bounce_rate {metrics['bounce_rate']:.1%} > "
                f"{thresholds['bounce_rate']:.1%}"
            )
    if metrics["qualified_leads"] > 0 and (
        metrics["cost_per_qualified_lead"] > thresholds["cost_per_qualified_lead"]
    ):
        breaches.append(
            f"cost_per_qualified_lead ${metrics['cost_per_qualified_lead']:.2f} > "
            f"${thresholds['cost_per_qualified_lead']:.2f}"
        )
    # Absolute spend ceiling: catches the runaway that converts nobody —
    # the per-lead check above can never fire at zero qualified leads.
    if (
        thresholds["max_llm_cost_usd"] > 0
        and metrics["llm_cost_usd"] > thresholds["max_llm_cost_usd"]
    ):
        breaches.append(
            f"llm_cost_usd ${metrics['llm_cost_usd']:.2f} > "
            f"${thresholds['max_llm_cost_usd']:.2f} over the window"
        )

    if breaches:
        workspace.outbound_paused = True
        workspace.pause_reason = "Kill-switch: " + "; ".join(breaches)
        db.add(
            AuditLog(
                workspace_id=workspace.id,
                action="killswitch_pause",
                detail={"breaches": breaches, "metrics": metrics},
            )
        )
        logger.warning(
            "KILL-SWITCH paused workspace %s: %s", workspace.id, breaches
        )
        # Enqueued, not sent inline: the ping commits atomically with the
        # pause, so a rolled-back pause can't have already alerted Slack.
        from engine.services.jobs import notify_slack

        await notify_slack(
            db, workspace.id,
            f"⛔ Kill-switch paused outbound for *{workspace.name}*: "
            + "; ".join(breaches),
        )
    return breaches
