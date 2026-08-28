"""Conversational reply agent.

Handles inbound prospect messages (email or SMS) with a real model instead of
regex + canned strings: classifies intent, answers questions strictly from the
playbook, qualifies against the ICP, offers the booking link to warm
prospects, and escalates to a human whenever it is out of its depth.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import Message, Prospect, Workspace
from engine.services import llm
from engine.services.booking import booking_url_for

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["warm", "question", "objection", "neutral", "cold"],
        },
        "reply": {
            "type": "string",
            "description": "The message to send back. Empty string if no reply "
            "should be sent (cold intent).",
        },
        "escalate": {
            "type": "boolean",
            "description": "True if a human must take over (pricing beyond "
            "public bands, legal/contract questions, anger, anything the "
            "playbook does not cover).",
        },
        "escalation_reason": {"type": "string"},
    },
    "required": ["intent", "reply", "escalate", "escalation_reason"],
    "additionalProperties": False,
}

REPLY_SYSTEM_TEMPLATE = """You are {company}'s conversational assistant handling \
replies from sales prospects on {channel}.

FACTS YOU MAY USE (the playbook — the ONLY source of claims):
{playbook_facts}
{capacity_block}
RULES:
1. Answer only from the playbook. If the answer isn't there, say you'll have a
   colleague follow up, and set escalate=true.
2. Warm prospects (interested, asking to talk/meet): thank them and share the
   booking link: {booking_url}
3. Questions: answer briefly and factually, then offer the booking link.
4. Objections: acknowledge honestly, one short counterpoint from the playbook
   at most, never argue.
5. Cold replies (not interested, remove me): intent=cold, reply must be empty —
   the system handles suppression; do not attempt to change their mind.
6. Pricing beyond the public bands in the playbook → escalate.
7. Never commit to capacity, team size, start dates, or staffing not stated
   in the capacity facts above. A prospect asking for specific staffing or
   availability beyond them → answer that a colleague will confirm, and set
   escalate=true.
8. {channel_style}
9. Never invent availability, names, customers, or numbers.
"""


def _channel_style(channel: str) -> str:
    if channel == "sms":
        return (
            "SMS: at most 300 characters, plain text, no links other than the "
            "booking link, always end with 'Reply STOP to opt out.'"
        )
    if channel == "whatsapp":
        return (
            "WhatsApp: at most 500 characters, conversational but professional, "
            "no links other than the booking link, always end with "
            "'Reply STOP to opt out.'"
        )
    if channel == "telegram":
        return (
            "Telegram: at most 500 characters, conversational but "
            "professional, no links other than the booking link, always end "
            "with 'Send /stop to opt out.'"
        )
    return "Email: at most 120 words, plain text, professional and warm."


async def conversation_history(
    db: AsyncSession, prospect: Prospect, limit: int = 20
) -> list[dict]:
    """Prospect's message history as alternating chat turns, oldest first."""
    rows = await db.execute(
        select(Message)
        .where(
            Message.workspace_id == prospect.workspace_id,
            Message.prospect_id == prospect.id,
            Message.channel.in_(["email", "sms", "whatsapp", "telegram"]),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    turns = []
    for m in reversed(rows.scalars().all()):
        role = "assistant" if m.direction == "out" else "user"
        prefix = f"[{m.channel}] "
        content = (f"Subject: {m.subject}\n" if m.subject else "") + (m.body or "")
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n\n" + prefix + content
        else:
            turns.append({"role": role, "content": prefix + content})
    # The API requires the first turn to be from the user.
    if turns and turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": "(conversation start)"})
    return turns


async def handle_inbound(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect,
    *,
    channel: str,
    inbound_text: str,
) -> dict:
    """Classify + draft a reply to an inbound message.
    Returns the REPLY_SCHEMA dict plus 'cost_usd'."""
    pb = workspace.playbook or {}
    playbook_facts = "\n\n".join(
        f"## {k}\n{v}"
        for k, v in pb.items()
        if isinstance(v, str) and v
        and k not in ("sign_off", "capacity_notes")
    ) or "(no playbook configured — escalate anything substantive)"

    # Capacity gets its own framed block (mirroring the composer): these are
    # the ONLY capacity claims the agent may make — bench over-commitment is
    # the highest-cost failure mode this product exists to prevent.
    if pb.get("capacity_notes"):
        capacity_block = (
            "\nCAPACITY / OFFERING FACTS (the only capacity or availability "
            f"claims you may make):\n{pb['capacity_notes']}\n"
        )
    else:
        capacity_block = (
            "\nCAPACITY: no capacity facts are configured — NEVER state team "
            "sizes, availability, or start dates; escalate staffing asks.\n"
        )

    system = REPLY_SYSTEM_TEMPLATE.format(
        company=pb.get("company_name", workspace.name),
        channel=channel,
        playbook_facts=playbook_facts,
        capacity_block=capacity_block,
        booking_url=booking_url_for(workspace, prospect) or "(no booking link configured — offer a call and escalate)",
        channel_style=_channel_style(channel),
    )

    history = await conversation_history(db, prospect)
    messages = history + [
        {
            "role": "user",
            "content": f"[{channel}] {inbound_text}\n\n"
            "Classify this reply and produce the response JSON.",
        }
    ]
    result = await llm.complete(
        db,
        workspace.id,
        model=llm.model_for(workspace, "reply"),
        system=system,
        messages=messages,
        max_tokens=4096,
        json_schema=REPLY_SCHEMA,
    )
    out = result.json()
    out["cost_usd"] = result.cost_usd
    return out
