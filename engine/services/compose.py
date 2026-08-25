"""Outreach email composition.

Preserves the validated mechanism from the research phase — per-signal
confidence averaging gates the email into Assertion vs Inquiry mode — but the
identity, honesty constraints, and style now come from the workspace playbook
instead of hardcoded Tenacious seed files, so any tenant can run it.
"""
import json

from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import Campaign, Prospect, Workspace
from engine.services import llm

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.7, "low": 0.4}
ASSERTION_THRESHOLD = 0.70

COMPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "maxLength": 60},
        "body": {"type": "string"},
        "mode_used": {"type": "string", "enum": ["assertion", "inquiry"]},
        "grounding_notes": {
            "type": "string",
            "description": "Which brief signals each claim in the body rests on",
        },
    },
    "required": ["subject", "body", "mode_used", "grounding_notes"],
    "additionalProperties": False,
}

DEFAULT_HONESTY_CONSTRAINTS = [
    "Only assert claims directly supported by the prospect's signal brief.",
    "If overall signal confidence is below the assertion threshold, use inquiry "
    "language (questions), never assertions about the prospect's situation.",
    "Never commit to capacity, pricing, or outcomes not stated in the playbook.",
    "Keep the body under 120 words.",
    "Subject line under 60 characters, no emojis.",
    "Never use placeholder text in brackets. Sign with the configured sign-off "
    "exactly.",
    "Do not invent names, numbers, funding amounts, or events.",
]


def compute_avg_confidence(signals: dict) -> float:
    scores = [
        CONFIDENCE_MAP.get(str(v.get("confidence", "low")).lower(), 0.4)
        for v in signals.values()
        if isinstance(v, dict)
    ]
    return sum(scores) / len(scores) if scores else 0.0


def build_system_prompt(workspace: Workspace, campaign: Campaign | None) -> str:
    pb = dict(workspace.playbook or {})
    if campaign is not None:
        pb.update({k: v for k, v in (campaign.playbook or {}).items() if v})

    constraints = pb.get("honesty_constraints") or DEFAULT_HONESTY_CONSTRAINTS
    constraint_lines = "\n".join(f"{i+1}. {c}" for i, c in enumerate(constraints))
    sections = [
        f"You are an outreach agent for {pb.get('company_name', workspace.name)}.",
        pb.get("company_description", ""),
        f"VALUE PROPOSITION:\n{pb['value_proposition']}" if pb.get("value_proposition") else "",
        f"IDEAL CUSTOMER PROFILE:\n{pb['icp_definition']}" if pb.get("icp_definition") else "",
        f"STYLE GUIDE:\n{pb['style_guide']}" if pb.get("style_guide") else "",
        f"CAPACITY / OFFERING FACTS (the only capacity claims you may make):\n{pb['capacity_notes']}"
        if pb.get("capacity_notes") else "",
        f"PRICING NOTES (public bands only):\n{pb['pricing_notes']}" if pb.get("pricing_notes") else "",
        f"HONESTY CONSTRAINTS — hard rules, never violate:\n{constraint_lines}",
        f"SIGN-OFF (use exactly):\n{pb['sign_off']}" if pb.get("sign_off") else "",
        f"EXAMPLES OF GOOD OUTREACH:\n{pb['examples']}" if pb.get("examples") else "",
    ]
    return "\n\n".join(s for s in sections if s)


async def compose_outreach(
    db: AsyncSession,
    workspace: Workspace,
    prospect: Prospect,
    campaign: Campaign | None,
    *,
    touch_number: int = 1,
    angle: str = "",
) -> tuple[dict, float]:
    """Compose one outreach email. Returns (draft fields, llm cost in USD)."""
    avg_conf = compute_avg_confidence(prospect.signals or {})
    mode = "ASSERTION" if avg_conf >= ASSERTION_THRESHOLD else "INQUIRY"

    followup_note = ""
    if touch_number > 1:
        followup_note = (
            f"\nThis is follow-up touch #{touch_number}. The prospect has not "
            "replied to earlier emails. Reference the earlier outreach briefly, "
            "add one new piece of value, and keep it shorter than the first email."
        )
    angle_note = f"\nCampaign angle to emphasize: {angle}" if angle else ""

    user_prompt = f"""Compose a cold outreach email for this prospect.
Mode: {mode} (average signal confidence: {avg_conf:.2f} — threshold {ASSERTION_THRESHOLD}).
In ASSERTION mode you may state facts the brief supports with high confidence.
In INQUIRY mode ask about the prospect's situation instead of asserting it.
{followup_note}{angle_note}

Prospect:
{json.dumps({"name": prospect.name, "company": prospect.company, "title": prospect.title}, indent=2)}

Signal brief:
{json.dumps(prospect.signals or {}, indent=2)}
"""

    result = await llm.complete(
        db,
        workspace.id,
        model=llm.model_for(workspace, "compose"),
        system=build_system_prompt(workspace, campaign),
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=2048,
        json_schema=COMPOSE_SCHEMA,
    )
    draft = result.json()
    draft["avg_confidence"] = avg_conf
    return draft, result.cost_usd
