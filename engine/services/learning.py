"""The learning loop: read outcomes back out of the pipeline's own records.

Every sent draft carries its angle, judge scores, and (after review) how
much a human edited it; every inbound message and booking is on the
timeline. This module turns that into:

- angle_performance: which campaign angles actually earn replies/bookings
  (a reply or booking is attributed to the last sent draft that preceded it
  for that prospect);
- judge_calibration: how often humans agree with the judge per score band,
  plus a recommended auto_approve_score derived from where human approval
  becomes near-unanimous;
- edit_stats: how much humans still rewrite the model's drafts;
- export_judge_training_rows: (draft, judge verdict, human verdict) rows for
  fine-tuning a workspace-specific judge.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import Booking, Draft, Message, Prospect, utcnow

LOOKBACK_DAYS = 90

# Human approval above this rate within a band means the judge can be
# trusted to auto-approve at that score.
CALIBRATION_APPROVAL_BAR = 0.95
# Bands need a floor of reviewed drafts before their rate means anything.
MIN_REVIEWED_PER_BAND = 10

# (floor, ceiling, label) — highest band first; ceiling is exclusive.
SCORE_BANDS = [
    (0.9, 1.01, "≥ 0.90"),
    (0.8, 0.9, "0.80–0.89"),
    (0.6, 0.8, "0.60–0.79"),
    (0.0, 0.6, "< 0.60"),
]


async def _sent_outreach_drafts(db: AsyncSession, workspace_id: str) -> list[Draft]:
    since = utcnow() - timedelta(days=LOOKBACK_DAYS)
    return list((await db.execute(
        select(Draft).where(
            Draft.workspace_id == workspace_id,
            Draft.kind == "outreach",
            Draft.status == "sent",
            Draft.created_at >= since,
        ).order_by(Draft.created_at)
    )).scalars().all())


async def angle_performance(db: AsyncSession, workspace_id: str) -> list[dict]:
    """Per-angle sends, replies, and bookings over the lookback window."""
    since = utcnow() - timedelta(days=LOOKBACK_DAYS)
    drafts = await _sent_outreach_drafts(db, workspace_id)
    if not drafts:
        return []
    inbound = list((await db.execute(
        select(Message.prospect_id, Message.created_at).where(
            Message.workspace_id == workspace_id,
            Message.direction == "in",
            Message.created_at >= since,
        )
    )).all())
    bookings = list((await db.execute(
        select(Booking.prospect_id, Booking.created_at).where(
            Booking.workspace_id == workspace_id,
            Booking.status.in_(["confirmed", "rescheduled"]),
            Booking.created_at >= since,
        )
    )).all())

    # Attribute each reply/booking to the last sent draft that preceded it
    # for that prospect. Drafts are already ordered by created_at.
    by_prospect: dict[str, list[Draft]] = {}
    for d in drafts:
        by_prospect.setdefault(d.prospect_id, []).append(d)

    def _attribute(prospect_id, event_at) -> Draft | None:
        last = None
        for d in by_prospect.get(prospect_id, []):
            if d.created_at <= event_at:
                last = d
            else:
                break
        return last

    stats: dict[str, dict] = {}
    for d in drafts:
        key = d.angle or "(no angle)"
        s = stats.setdefault(key, {"angle": key, "sends": 0, "replies": 0,
                                   "bookings": 0})
        s["sends"] += 1
    replied_pairs: set[tuple[str, str]] = set()
    for prospect_id, at in inbound:
        d = _attribute(prospect_id, at)
        # Count one reply per (prospect, draft): a long back-and-forth is
        # still a single earned reply for that touch.
        if d is not None and (prospect_id, d.id) not in replied_pairs:
            replied_pairs.add((prospect_id, d.id))
            stats[d.angle or "(no angle)"]["replies"] += 1
    for prospect_id, at in bookings:
        d = _attribute(prospect_id, at)
        if d is not None:
            stats[d.angle or "(no angle)"]["bookings"] += 1

    rows = []
    for s in stats.values():
        s["reply_rate"] = s["replies"] / s["sends"] if s["sends"] else 0.0
        rows.append(s)
    rows.sort(key=lambda s: (s["reply_rate"], s["sends"]), reverse=True)
    return rows


async def judge_calibration(db: AsyncSession, workspace_id: str) -> dict:
    """Human-vs-judge agreement per score band + a recommended
    auto_approve_score (None when there's not enough reviewed data)."""
    since = utcnow() - timedelta(days=LOOKBACK_DAYS)
    reviewed = list((await db.execute(
        select(Draft).where(
            Draft.workspace_id == workspace_id,
            Draft.kind == "outreach",
            Draft.reviewed_by.is_not(None),
            Draft.judge_score.is_not(None),
            Draft.created_at >= since,
        )
    )).scalars().all())

    bands = []
    recommended = None
    for floor, ceiling, label in SCORE_BANDS:
        in_band = [
            d for d in reviewed if floor <= d.judge_score < ceiling
        ]
        approved = [d for d in in_band if d.status in ("approved", "sent")]
        edit_ratios = [d.edit_ratio for d in approved if d.edit_ratio is not None]
        rate = len(approved) / len(in_band) if in_band else None
        bands.append({
            "band": label,
            "reviewed": len(in_band),
            "approved": len(approved),
            "approval_rate": rate,
            "avg_edit_ratio": (sum(edit_ratios) / len(edit_ratios))
            if edit_ratios else None,
        })
    # Recommend the lowest band floor down to which humans approve
    # near-unanimously on a meaningful sample — bands must qualify
    # contiguously from the top, so a good 0.6 band can't outvote a bad 0.8.
    for (floor, _ceiling, _label), band in zip(SCORE_BANDS, bands, strict=True):
        if (
            floor > 0
            and band["reviewed"] >= MIN_REVIEWED_PER_BAND
            and (band["approval_rate"] or 0) >= CALIBRATION_APPROVAL_BAR
        ):
            recommended = floor
        else:
            break
    return {"bands": bands, "recommended_auto_approve_score": recommended,
            "reviewed_total": len(reviewed)}


async def edit_stats(db: AsyncSession, workspace_id: str) -> dict:
    since = utcnow() - timedelta(days=LOOKBACK_DAYS)
    ratios = [
        r for (r,) in (await db.execute(
            select(Draft.edit_ratio).where(
                Draft.workspace_id == workspace_id,
                Draft.edit_ratio.is_not(None),
                Draft.created_at >= since,
            )
        )).all()
    ]
    return {
        "reviewed": len(ratios),
        "avg_edit_ratio": (sum(ratios) / len(ratios)) if ratios else None,
        "sent_verbatim": sum(1 for r in ratios if r < 0.02),
        "heavily_edited": sum(1 for r in ratios if r > 0.5),
    }


async def export_judge_training_rows(
    db: AsyncSession, workspace_id: str
) -> list[dict]:
    """Reviewed drafts as fine-tuning rows for a workspace-specific judge:
    the model input (signals + draft) with both the API judge's verdict and
    the human's (the label)."""
    reviewed = list((await db.execute(
        select(Draft, Prospect)
        .join(Prospect, Draft.prospect_id == Prospect.id)
        .where(
            Draft.workspace_id == workspace_id,
            Draft.kind == "outreach",
            Draft.reviewed_by.is_not(None),
        )
        .order_by(Draft.created_at)
    )).all())
    rows = []
    for draft, prospect in reviewed:
        rows.append({
            "signals": prospect.signals or {},
            "mode": draft.mode,
            "avg_confidence": draft.avg_confidence,
            "subject": draft.subject,
            "body": draft.body,
            "grounding_notes": draft.grounding_notes,
            "judge_score": draft.judge_score,
            "judge_scores": draft.judge_scores or {},
            "judge_feedback": draft.judge_feedback,
            "human_decision": "approved"
            if draft.status in ("approved", "sent") else "rejected",
            "edit_ratio": draft.edit_ratio,
            "reject_reason": draft.reject_reason,
        })
    return rows
