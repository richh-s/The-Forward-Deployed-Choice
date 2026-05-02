from openai import OpenAI
import os
import json
import re
import sys
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.load_seed import build_system_prompt_context, build_few_shot_block

# ── Model constants ──────────────────────────────────────────────────────────
# Composer and judge must be different model families (preference-leakage prevention).
# Composer = Claude (Anthropic via OpenRouter).
# Judge = Qwen (Alibaba via OpenRouter) — never the same family as the composer.
COMPOSER_MODEL = "anthropic/claude-sonnet-4.6"
JUDGE_MODEL = os.environ.get("TONE_JUDGE_MODEL", "qwen/qwen3-next-80b-a3b-instruct")

# ── Regeneration loop constants ──────────────────────────────────────────────
MAX_ATTEMPTS = 2           # total LLM calls (initial + 1 retry on single-marker fail)
SCORE_THRESHOLD = 4        # any marker below this triggers a retry or escalation
ESCALATION_THRESHOLD = 2   # this many failed markers → escalate immediately, no retry

# Escalation log path — written by compose_with_tone_gate, read by human reviewers
_ESCALATION_LOG = Path(__file__).parent.parent / "eval" / "escalations.jsonl"

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
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


# ── System prompt ────────────────────────────────────────────────────────────

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

# Per-marker repair instructions injected into the feedback prompt on retry.
# Each string tells the model exactly what was wrong and how to fix it.
_MARKER_REPAIR = {
    "direct": (
        "Reduce body length if over the word limit. "
        "Remove every sentence that does not reference a specific signal or make the ask. "
        "Ensure exactly ONE call-to-action — '15 minutes' — and nothing else."
    ),
    "grounded": (
        "Every factual claim must name a specific value from the brief: dollar amount, "
        "role count, days-ago, or named leadership change. "
        "For any signal with confidence='low' or fewer than 5 open roles, switch to "
        "interrogative phrasing: 'Is X the case?' not 'You are doing X'."
    ),
    "honest": (
        "Remove every claim not directly traceable to a field in the hiring signal brief. "
        "If job-post velocity is low or medium confidence, use inquiry phrasing throughout. "
        "Do not reference bench headcount or specific capacity numbers. "
        "Do not name peer practices that are not in the competitor gap brief."
    ),
    "professional": (
        "Scan for every banned phrase (world-class, top talent, rockstar, skyrocket, etc.) "
        "and replace with plain language. "
        "Replace any use of 'bench' with 'engineering team' or 'available capacity'. "
        "Calibrate vocabulary to a CTO or VP Engineering reading this between meetings."
    ),
    "non_condescending": (
        "Reframe every competitor gap as a research finding or open question, "
        "never as a deficiency of the prospect's leadership. "
        "Replace 'you are falling behind' → "
        "'peers in your sector are doing X — curious if that's on your roadmap'. "
        "Never imply the prospect is late, behind, or failing."
    ),
}

_ROAST_REPAIR = (
    "The email would be screenshotted and shared publicly as a negative example. "
    "Check for: (1) any banned phrases still present, "
    "(2) unfilled bracket placeholders like [First Name] or [Company], "
    "(3) condescending framing that implies the recipient is failing or behind, "
    "(4) claims that could be disproved in 10 seconds (e.g. wrong funding round, "
    "fake hiring numbers), (5) passive-aggressive language about not replying. "
    "Rewrite to be specific, grounded, and peer-level in every sentence."
)


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
    """Apply pre-LLM gates. Returns directives injected into the user prompt."""
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
    extra_feedback: str = "",
) -> tuple[dict, dict]:
    """Raw single-shot LLM composer. No scoring, no regeneration.

    Returns (draft_dict, usage_dict).
    Call compose_with_tone_gate() for the gated version.
    """
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
{extra_feedback}
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
        model=COMPOSER_MODEL,
        max_tokens=700,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": prompt},
        ],
    )
    text = response.choices[0].message.content.strip()
    if text.startswith("```json"):
        text = text[7:-3].strip()
    elif text.startswith("```"):
        text = text[3:-3].strip()
    return json.loads(text), dict(response.usage)


# ── Tone-preservation gate ───────────────────────────────────────────────────

def _build_task_for_scoring(
    draft: dict,
    brief: dict,
    bench_summary: dict,
    is_re_engagement: bool,
) -> dict:
    """Wrap composer output into the task shape scoring_evaluator.score_task expects."""
    return {
        "task_id": "RUNTIME-COMPOSE",
        "candidate_output": {
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "message_type": "re_engagement" if is_re_engagement else "cold",
        },
        "input": {
            "hiring_signal_brief": brief,
            "bench_summary": bench_summary,
        },
        "ground_truth": {},
        "failure_dimension": "runtime",
    }


def build_feedback_prompt(
    draft: dict,
    failed_markers: list[str],
    score_result: dict,
    brief: dict,
) -> str:
    """Build a targeted repair instruction for the regeneration prompt.

    Tells the model exactly which marker failed, at what score, what the rubric
    requires, and (where possible) which signal values to use in the rewrite.
    """
    lines = ["\n\n--- FEEDBACK FROM PREVIOUS ATTEMPT ---"]
    lines.append(
        f"Your previous draft failed {len(failed_markers)} tone "
        f"marker(s): {', '.join(m.upper() for m in failed_markers)}."
    )

    marker_scores = score_result.get("marker_scores") or {}
    det_checks = score_result.get("deterministic_checks") or {}

    for marker in failed_markers:
        score = marker_scores.get(marker, "?")
        repair = _MARKER_REPAIR.get(marker, "Rewrite this section carefully.")
        lines.append(
            f"\n{marker.upper()} marker failed (score {score}/5). {repair}"
        )

    # Surface concrete brief values to anchor the rewrite
    signals = brief.get("signals") or {}
    job_sig = signals.get("signal_2_job_post_velocity") or {}
    eng_roles = job_sig.get("engineering_roles")
    job_conf = job_sig.get("confidence", "")
    if eng_roles is not None and ("grounded" in failed_markers or "honest" in failed_markers):
        lines.append(
            f"\nSignal anchors from the brief: "
            f"open_engineering_roles={eng_roles}, "
            f"job_post_confidence={job_conf!r}. "
            f"If fewer than 5 roles or confidence is 'low'/'medium', "
            f"you must use interrogative phrasing."
        )

    # Surface any deterministic failures too
    det_fails = [k for k, v in det_checks.items() if not v.get("passed")]
    if det_fails:
        lines.append(
            f"\nDeterministic check failures (must also fix): {', '.join(det_fails)}. "
            f"Details: "
            + "; ".join(
                f"{k}: {det_checks[k].get('detail', '')}"
                for k in det_fails
            )
        )

    lines.append("\nRewrite the ENTIRE email from scratch addressing every point above.")
    lines.append("--- END FEEDBACK ---\n")
    return "\n".join(lines)


def linkedin_roast_test(
    draft_subject: str,
    draft_body: str,
    model: str = JUDGE_MODEL,
) -> bool:
    """Binary judge: would a senior VP of Engineering screenshot and post this email?

    Returns True (passed — would NOT be posted) or False (failed — would be posted).
    Uses JUDGE_MODEL (Qwen), a different family from the Claude composer.
    Falls back to True (permissive) if the API call fails, so a network error
    never blocks a send — deterministic checks are the authoritative gate.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return True  # offline / no key — skip roast test

    prompt = f"""You are a senior VP of Engineering who just received this cold email. Read it carefully.

Subject: {draft_subject}
Body:
{draft_body}

Would you screenshot this email and post it on LinkedIn with a sarcastic or critical caption?

Answer YES if the email:
- Contains factually wrong information about your company
- Talks down to you or implies you are behind peers
- Is obviously a template with unfilled tokens like [First Name] or [Company]
- Makes claims you could disprove in 10 seconds on Google
- Has passive-aggressive language about not replying
- Promises things that seem impossible or fabricated
- Uses any of these exact phrases: "world-class", "top talent", "skyrocket", \
"I hope this email finds you well", "per my last email", "quick chat"

Answer NO if the email:
- References something real and specific about this company's situation
- Asks rather than assumes when signal is weak
- Respects the reader's time with one clear ask
- Makes a claim the recipient could verify and it would check out

Respond with exactly one word: YES or NO.
Then on the next line, one sentence explaining why."""

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        text = response.choices[0].message.content.strip()
        verdict = text.split("\n")[0].strip().upper()
        return verdict == "NO"  # True = passed (would NOT post)
    except Exception:
        return True  # fail-open: network errors don't block send


def _log_escalation(
    draft: dict,
    failed_markers: list[str],
    brief: dict,
    reason: str = "",
) -> None:
    """Append an escalation record to eval/escalations.jsonl."""
    try:
        _ESCALATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": datetime.now(UTC).isoformat(),
            "reason": reason or f"failed_markers={failed_markers}",
            "failed_markers": failed_markers,
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "company": (brief.get("firmographics") or {}).get("industry", ""),
            "prospect_domain": brief.get("prospect_domain", ""),
        }
        with _ESCALATION_LOG.open("a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass  # escalation logging must never crash the pipeline


def compose_with_tone_gate(
    brief: dict,
    competitor_brief: dict,
    bench_summary: dict,
    is_re_engagement: bool = False,
    pricing_in_scope: bool = False,
) -> tuple[dict | None, dict, dict]:
    """Compose, score, and regenerate until the email passes or escalation triggers.

    Implements the full tone-preservation gate described in the Week 10 spec:

      for attempt in range(MAX_ATTEMPTS):
          draft = compose_outreach_email(...)
          score  = score_task(draft, judge=JUDGE_MODEL)
          failed = [m for m, s in score["marker_scores"] if s < SCORE_THRESHOLD]

          if not failed:          → run roast test; return on pass
          if len(failed) >= 2:    → escalate immediately (no retry)
          else:                   → build feedback prompt and retry

      After MAX_ATTEMPTS without a clean draft → escalate.

    Returns:
      (draft | None, usage_dict, gate_result_dict)
      draft is None when the email was escalated (do not send).
    """
    from scoring_evaluator import score_task  # local import avoids circular at module load

    extra_feedback = ""
    draft: dict = {}
    usage: dict = {}
    last_score_result: dict = {}
    last_failed: list[str] = []

    for attempt in range(MAX_ATTEMPTS):
        try:
            draft, usage = compose_outreach_email(
                brief=brief,
                competitor_brief=competitor_brief,
                bench_summary=bench_summary,
                is_re_engagement=is_re_engagement,
                pricing_in_scope=pricing_in_scope,
                extra_feedback=extra_feedback,
            )
        except Exception as e:
            return None, {}, {
                "status": "error",
                "reason": f"compose_exception: {type(e).__name__}: {e}",
                "attempt": attempt + 1,
                "failed_markers": [],
                "roast_verdict": "SKIPPED",
            }

        task = _build_task_for_scoring(draft, brief, bench_summary, is_re_engagement)
        try:
            score_result = score_task(task, use_judge=True, judge_model=JUDGE_MODEL)
        except Exception as e:
            return None, usage, {
                "status": "error",
                "reason": f"score_exception: {type(e).__name__}: {e}",
                "attempt": attempt + 1,
                "failed_markers": [],
                "roast_verdict": "SKIPPED",
            }

        last_score_result = score_result
        marker_scores = score_result.get("marker_scores") or {}
        det_checks = score_result.get("deterministic_checks") or {}

        failed_markers = [
            m for m, s in marker_scores.items() if s < SCORE_THRESHOLD
        ]
        det_fails = [k for k, v in det_checks.items() if not v.get("passed")]
        last_failed = failed_markers + [f"det:{d}" for d in det_fails]

        # ── All checks pass: run roast test, then return ──────────────────
        if not failed_markers and not det_fails:
            passed_roast = linkedin_roast_test(
                draft.get("subject", ""),
                draft.get("body", ""),
            )
            if passed_roast:
                return draft, usage, {
                    "status": "sent",
                    "attempt": attempt + 1,
                    "failed_markers": [],
                    "roast_verdict": "NO",
                    "marker_scores": marker_scores,
                    "composite_score": score_result.get("composite_score"),
                }
            # Roast failed: treat as DIRECT marker failure and retry if budget remains
            if attempt < MAX_ATTEMPTS - 1:
                extra_feedback = build_feedback_prompt(
                    draft=draft,
                    failed_markers=["direct"],
                    score_result={
                        **score_result,
                        "marker_scores": {**marker_scores, "direct": 1},
                    },
                    brief=brief,
                )
                extra_feedback += f"\n\nROAST TEST FAILURE: {_ROAST_REPAIR}"
                last_failed = ["direct (roast_fail)"]
                continue
            # Out of retries after roast fail
            _log_escalation(draft, ["direct (roast_fail)"], brief, reason="roast_test_failed")
            return None, usage, {
                "status": "roast_fail",
                "attempt": attempt + 1,
                "failed_markers": ["direct (roast_fail)"],
                "roast_verdict": "YES",
                "marker_scores": marker_scores,
            }

        # ── 2+ markers failed: escalate immediately ────────────────────────
        if len(failed_markers) >= ESCALATION_THRESHOLD:
            _log_escalation(draft, failed_markers + det_fails, brief,
                            reason=f"escalation_threshold_exceeded_attempt_{attempt+1}")
            return None, usage, {
                "status": "escalated",
                "attempt": attempt + 1,
                "failed_markers": failed_markers,
                "det_failures": det_fails,
                "roast_verdict": "SKIPPED",
                "marker_scores": marker_scores,
                "reason": (
                    f"{len(failed_markers)} tone markers below {SCORE_THRESHOLD} "
                    f"({', '.join(failed_markers)}); "
                    f"escalation threshold {ESCALATION_THRESHOLD} reached on attempt {attempt+1}"
                ),
            }

        # ── Exactly 1 marker failed: build feedback and retry ─────────────
        extra_feedback = build_feedback_prompt(
            draft=draft,
            failed_markers=failed_markers + det_fails,
            score_result=score_result,
            brief=brief,
        )

    # Exhausted all attempts without a clean draft
    _log_escalation(draft, last_failed, brief,
                    reason=f"exhausted_{MAX_ATTEMPTS}_attempts")
    return None, usage, {
        "status": "escalated",
        "attempt": MAX_ATTEMPTS,
        "failed_markers": last_failed,
        "roast_verdict": "SKIPPED",
        "marker_scores": (last_score_result.get("marker_scores") or {}),
        "reason": f"Exhausted {MAX_ATTEMPTS} attempts. Last failures: {last_failed}",
    }
