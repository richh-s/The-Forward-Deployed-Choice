from openai import OpenAI
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.load_seed import build_system_prompt_context, build_few_shot_block

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
)

_SEED_CONTEXT = None

def _get_seed_context() -> str:
    global _SEED_CONTEXT
    if _SEED_CONTEXT is None:
        _SEED_CONTEXT = build_system_prompt_context()
    return _SEED_CONTEXT

_FEW_SHOT_BLOCK = None

def _get_few_shot_block() -> str:
    global _FEW_SHOT_BLOCK
    if _FEW_SHOT_BLOCK is None:
        _FEW_SHOT_BLOCK = build_few_shot_block(n_transcripts=3)
    return _FEW_SHOT_BLOCK


SYSTEM_PROMPT_TEMPLATE = """\
You are an outreach agent for Tenacious Consulting and Outsourcing.
Tenacious provides managed talent outsourcing and project consulting to B2B tech companies.

{seed_context}

HONESTY CONSTRAINTS — hard rules, never violate:
1. Only assert claims directly supported by the hiring signal brief.
2. If signal confidence is "low" or "medium" AND open_roles < 5, use inquiry language not assertion language.
3. Never use the word "offshore" in first contact.
4. Never commit to engineering-team capacity not confirmed in the bench summary above.
5. Never pitch Segment 4 to a prospect with ai_maturity_score below 2.
6. Route to human for pricing beyond public bands.
7. If competitor gap confidence is "medium", say "peers like X" not "you are behind X".
8. Keep first email under 120 words in the body.
9. Do not use "bench" — say "engineering team" or "available capacity" instead.
10. Subject line must start with Request, Follow-up, Context, or Question. Under 60 characters. No emojis.
11. NEVER use placeholder text in brackets like [Your Name], [Your Title], [Company], etc. Sign the email as: Alex Chen, Senior Engagement Manager, Tenacious Intelligence Corporation. Always use this exact sign-off.

KILL-SWITCH RULE:
Compute avg_confidence across all 6 signals.
If avg_confidence < 0.70 → Inquiry Mode (ask, do not assert)
If avg_confidence >= 0.70 → Assertion Mode (state verified facts)

TENACIOUS TONE MARKERS — every email must score 4/5 or above on all five or it is regenerated:

1. DIRECT
Clear, brief, actionable. No filler. Subject lines state intent — never use "Quick", "Just", or "Hey".
Cold outreach body: 120 words maximum. One clear ask only.

2. GROUNDED
Every claim supported by the hiring signal brief or competitor gap brief. When signal is weak (fewer than 5 open roles, single low-confidence input), ask rather than assert. Example of correct weak-signal phrasing:
"Three open Python roles since January — is hiring velocity matching the runway?" NOT "You're scaling aggressively."

3. HONEST
Refuses claims that cannot be grounded in data. Never claims "aggressive hiring" if job-post signal is weak. Never over-commits engineering-team capacity not in bench_summary. Never fabricates peer practices. When a signal is missing, name the absence and ask.

4. PROFESSIONAL
Language appropriate for founders, CTOs, VPs Engineering. Never use the word "bench" in any prospect-facing message. Use "engineering team", "available capacity", or "engineers ready to deploy" instead.

5. NON-CONDESCENDING
Frame competitor gaps as research findings or questions, never as failures of the prospect's leadership. The value is the specificity of what peers are doing, not the implication that the prospect is behind.

BANNED PHRASES — none of these may appear anywhere in the subject line or body. If any appear, regenerate immediately:

world-class
top talent
A-players
rockstar
ninja
wizard
skyrocket
supercharge
10x
I hope this email finds you well
just following up
circling back
Quick question
Quick chat
synergize
synergy
leverage
ecosystem
game-changer
disruptor
paradigm shift
our proprietary
per my last email

FORMATTING RULES:
- Cold outreach body: maximum 120 words
- Warm reply body: maximum 200 words
- Re-engagement body: maximum 100 words
- Subject line: maximum 60 characters
- Exactly ONE call to action per email
- The default ask is "15 minutes" — never invent other durations like 20 or 25 minutes
- If a recipient.first_name is present in the brief, address them by it (e.g. "Maya,"). Never emit "[First Name]" or any bracketed placeholder.
- No attached PDFs ever
- No emojis in cold outreach
- Signature: [First name] / [Title] / Tenacious Intelligence Corporation / gettenacious.com — nothing else

BAD EXAMPLE 1 — DO NOT write like this:
Subject: Tenacious — World-Class Engineering Talent

Body: Dear Maya, Tenacious Intelligence Corporation is a world-class engineering outsourcing firm with over 200 senior engineers. Our top talent is graduated from elite programs and our delivery model is the gold standard in the industry.

FAILURE MODES IN THIS EXAMPLE:
- "world-class" and "top talent" are banned phrases
- Entire body is about Tenacious, not the prospect
- No hiring signal referenced at all
- Lists every service (self-centered)
- Asks for 45 minutes (too long for cold outreach)
- 152 words — exceeds limit

BAD EXAMPLE 2 — DO NOT write like this:
Subject: Quick chat: your aggressive hiring

Body: Hi Tom, I see you are scaling aggressively — your engineering team is clearly growing fast. We solve this exact problem. Tenacious places top talent in 48 hours and we will skyrocket your delivery throughput.

FAILURE MODES IN THIS EXAMPLE:
- "scaling aggressively" asserted on weak signal (2 open roles)
- "top talent" and "skyrocket" are banned phrases
- "Quick chat" in subject is banned
- Assumes pain that signal does not support

BAD EXAMPLE 3 — DO NOT write like this:
Subject: Your AI maturity is behind the curve

Body: Hi Felix, I will be direct: your AI maturity score is a 1, while your top competitors are a 3. You are falling behind in a market where AI is no longer optional.

FAILURE MODES IN THIS EXAMPLE:
- Subject is condescending — senior leaders will not reply
- "falling behind", "catch up" frames prospect as failing
- "world-class" appears later in the draft
- Assumes a board meeting that is not in the brief

DISCOVERY TRANSCRIPT EXAMPLES (tone and structure reference):
{few_shot_block}
"""

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.7, "low": 0.4}


def _build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        seed_context=_get_seed_context(),
        few_shot_block=_get_few_shot_block(),
    )


def compute_avg_confidence(signals: dict) -> float:
    keys = [
        "signal_1_funding_event",
        "signal_2_job_post_velocity",
        "signal_3_layoff_event",
        "signal_4_leadership_change",
        "signal_5_ai_maturity",
        "signal_6_icp_segment",
    ]
    scores = [
        CONFIDENCE_MAP.get(str(signals[k].get("confidence", "low")).lower(), 0.4)
        for k in keys if k in signals
    ]
    return sum(scores) / len(scores) if scores else 0.0


def _required_stacks_from_brief(brief: dict, competitor_brief: dict) -> list:
    stacks = []
    bench_match = brief.get("bench_to_brief_match") or {}
    stacks.extend(bench_match.get("required_stacks") or [])
    sig5 = (brief.get("signals") or {}).get("signal_5_ai_maturity") or {}
    for j in sig5.get("justification", []) or []:
        detail = (j.get("detail") or "").lower()
        if "ml" in detail or "ai" in detail:
            stacks.append("ml")
        if "data" in detail or "snowflake" in detail or "dbt" in detail:
            stacks.append("data")
    return list({s.lower() for s in stacks if s})


def build_decision_flow_directives(
    brief: dict,
    competitor_brief: dict,
    bench_summary: dict,
    is_re_engagement: bool = False,
    pricing_in_scope: bool = False,
) -> dict:
    """Apply pre-LLM gates from the outreach decision flow.

    Returns a dict with:
      - directives: list[str] of additional system instructions
      - icp_segment_number: int
      - icp_segment_confidence: float
      - ai_maturity_score: int
      - segment_4_blocked: bool
      - bench_supports_ask: bool
    """
    signals = brief.get("signals") or {}

    icp_signal = signals.get("signal_6_icp_segment") or {}
    segment_number = icp_signal.get("segment_number")
    if segment_number is None:
        segment_number = brief.get("primary_segment_number") or 0
    icp_confidence_label = str(icp_signal.get("confidence", "low")).lower()
    icp_confidence = CONFIDENCE_MAP.get(icp_confidence_label, brief.get("segment_confidence") or 0.4)

    ai_signal = signals.get("signal_5_ai_maturity") or brief.get("ai_maturity") or {}
    ai_score = int(ai_signal.get("score", 0) or 0)

    required_stacks = _required_stacks_from_brief(brief, competitor_brief)
    stacks = (bench_summary or {}).get("stacks", {})
    bench_supports_ask = True
    bench_gaps = []
    for stack in required_stacks:
        available = (stacks.get(stack) or {}).get("available_engineers", 0)
        if not available or available <= 0:
            bench_supports_ask = False
            bench_gaps.append(stack)

    directives: list[str] = []

    directives.append(
        f"DECISION FLOW STEP 1 — ICP segment is {segment_number} "
        f"(confidence {icp_confidence_label}, {icp_confidence:.2f}). "
        f"If confidence < 0.70, use inquiry phrasing for any segment-specific claim."
    )

    segment_4_blocked = ai_score < 2
    if segment_4_blocked:
        directives.append(
            f"DECISION FLOW STEP 2 — AI maturity score is {ai_score} (< 2). "
            "DO NOT use Segment 4 (AI/ML capability gap) framing under any circumstance. "
            "If the brief suggests Segment 4, fall back to the next eligible segment or ask a "
            "research question instead of pitching capability gap."
        )
    else:
        directives.append(
            f"DECISION FLOW STEP 2 — AI maturity score is {ai_score} (>= 2). "
            "Segment 4 framing is permitted but only with confidence-aware language."
        )

    if not bench_supports_ask:
        directives.append(
            "DECISION FLOW STEP 3 — Bench cannot support the implied stack ask "
            f"(missing capacity in: {', '.join(bench_gaps)}). "
            "Do not commit to specific headcount, stack, or timeline. "
            "Route to discovery call instead. Frame the email as a research question, "
            "not a capacity offer."
        )
    else:
        directives.append(
            "DECISION FLOW STEP 3 — Bench supports the implied stack ask. "
            "You may reference 'engineering team' or 'available capacity' generically, "
            "but never commit to a specific headcount in cold outreach."
        )

    if pricing_in_scope:
        directives.append(
            "DECISION FLOW STEP 4 — Pricing has been requested. "
            "Use only the public price bands documented in the seed pricing sheet. "
            "Never invent a total contract value or quote a custom number. "
            "If the prospect asked for a custom quote, state that pricing is finalized on the discovery call."
        )
    else:
        directives.append(
            "DECISION FLOW STEP 4 — Do not introduce pricing. Defer pricing discussions to discovery call."
        )

    if is_re_engagement:
        directives.append(
            "DECISION FLOW STEP 5 — This is a RE-ENGAGEMENT. "
            "You MUST add a new signal or piece of data not present in the prior thread. "
            "Never write 'following up', 'circling back', 'just checking in', or any equivalent. "
            "Body must be under 100 words."
        )
    else:
        directives.append(
            "DECISION FLOW STEP 5 — This is a cold first-touch outreach (no prior contact). "
            "Body must be under 120 words."
        )

    return {
        "directives": directives,
        "icp_segment_number": segment_number,
        "icp_segment_confidence": icp_confidence,
        "ai_maturity_score": ai_score,
        "segment_4_blocked": segment_4_blocked,
        "bench_supports_ask": bench_supports_ask,
        "bench_gaps": bench_gaps,
        "is_re_engagement": is_re_engagement,
        "pricing_in_scope": pricing_in_scope,
    }


def compose_outreach_email(
    brief: dict,
    competitor_brief: dict,
    bench_summary: dict,
    is_re_engagement: bool = False,
    pricing_in_scope: bool = False,
) -> dict:
    avg_conf = compute_avg_confidence(brief["signals"])
    mode = "ASSERTION" if avg_conf >= 0.70 else "INQUIRY"

    flow = build_decision_flow_directives(
        brief=brief,
        competitor_brief=competitor_brief,
        bench_summary=bench_summary,
        is_re_engagement=is_re_engagement,
        pricing_in_scope=pricing_in_scope,
    )
    directives_block = "\n".join(f"- {d}" for d in flow["directives"])

    word_limit = 100 if is_re_engagement else 120
    email_type = "re_engagement" if is_re_engagement else "cold"

    prompt = f"""
Compose a {email_type} outreach email for this prospect.
Mode: {mode} (avg signal confidence: {avg_conf:.2f})

PRE-LLM DECISION FLOW (apply these constraints to every line you write):
{directives_block}

Hiring Signal Brief:
{json.dumps(brief, indent=2)}

Competitor Gap Brief:
{json.dumps(competitor_brief, indent=2)}

Available engineering team capacity:
{json.dumps(bench_summary, indent=2)}

Return valid JSON only — no markdown, no backticks:
{{
  "subject": "string (under 60 chars, starts with Request/Follow-up/Context/Question)",
  "body": "string (plain text, under {word_limit} words)",
  "variant_tag": "signal_grounded" or "generic",
  "mode_used": "assertion" or "inquiry",
  "avg_confidence": float,
  "signals_used": ["list of signal keys from the brief actually referenced in the body"],
  "confidence_flag": "high" | "medium" | "low"
}}
"""
    response = client.chat.completions.create(
        model="anthropic/claude-sonnet-4.6",
        max_tokens=700,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": prompt}
        ]
    )
    text = response.choices[0].message.content.strip()
    if text.startswith("```json"):
        text = text[7:-3].strip()
    elif text.startswith("```"):
        text = text[3:-3].strip()
    return json.loads(text), dict(response.usage)
