import json
import time
import os
import datetime as dt
from pathlib import Path
import anthropic
import httpx
from enrichment.mock_brief import (
    SYNTHETIC_PROSPECT,
    HIRING_SIGNAL_BRIEF,
    COMPETITOR_GAP_BRIEF,
    BENCH_SUMMARY
)
from agent.email_pipeline import compose_with_regeneration
from agent.email_sender   import send_outreach
from agent.hubspot_writer import create_contact, mark_meeting_booked
from agent.calendar       import get_available_slots, book_discovery_call

client = anthropic.Anthropic()

SYNTHETIC_PROSPECT["email"] = "rahelsamson953@gmail.com"

OUTREACH_TRACE_LOG = Path("eval/trace_log_outreach.jsonl")
ESCALATIONS_LOG = Path("eval/escalations.jsonl")


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _log_escalation_to_langfuse(prospect: dict, pipeline_result: dict, tag: str) -> None:
    """Best-effort Langfuse tagging for human-review escalations. Never raises."""
    try:
        from langfuse import Langfuse  # type: ignore

        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return
        lf = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        )
        lf.trace(
            name="email-pipeline-human-review",
            user_id=prospect.get("email"),
            tags=["human_review_required", tag],
            metadata={
                "company": prospect.get("company"),
                "status": pipeline_result.get("status"),
                "reason": pipeline_result.get("reason"),
                "attempts": pipeline_result.get("attempts"),
                "failed_markers": pipeline_result.get("failed_markers"),
                "deterministic_failures": pipeline_result.get("deterministic_failures"),
                "roast_verdict": pipeline_result.get("roast_verdict"),
                "model_used": pipeline_result.get("model_used"),
                "judge_model_used": pipeline_result.get("judge_model_used"),
            },
        )
        lf.flush()
    except Exception as e:
        print(f"  [warn] langfuse escalation log skipped: {e}")


def run_outreach(
    prospect: dict,
    hiring_signal_brief: dict,
    competitor_gap_brief: dict,
    bench_summary: dict,
    prior_thread: dict | None = None,
    pricing_in_scope: bool = False,
) -> dict:
    """Compose → tone-gate → send (or escalate). Returns a normalised result dict."""
    print(f"\nComposing outreach for {prospect.get('company')} (regeneration loop active)...")

    pipeline = compose_with_regeneration(
        hiring_signal_brief=hiring_signal_brief,
        competitor_gap_brief=competitor_gap_brief,
        bench_summary=bench_summary,
        prior_thread=prior_thread,
        pricing_in_scope=pricing_in_scope,
    )

    status = pipeline["status"]
    print(
        f"  status: {status} | attempts: {pipeline['attempts']} | "
        f"roast: {pipeline['roast_verdict']}"
    )
    print(f"  reason: {pipeline['reason']}")
    print(f"  subject: {pipeline['subject'][:80]}")

    if status in ("escalated", "roast_fail", "error"):
        tag = (
            "tone_marker_escalation" if status == "escalated"
            else "roast_fail" if status == "roast_fail"
            else "pipeline_error"
        )
        _log_escalation_to_langfuse(prospect, pipeline, tag)
        escalation_row = {
            "timestamp":              dt.datetime.utcnow().isoformat() + "Z",
            "prospect_email":         prospect.get("email"),
            "prospect_company":       prospect.get("company"),
            "status":                 status,
            "reason":                 pipeline["reason"],
            "attempts":               pipeline["attempts"],
            "subject":                pipeline["subject"],
            "body":                   pipeline["body"],
            "final_scores":           pipeline["final_scores"],
            "failed_markers":         pipeline["failed_markers"],
            "deterministic_failures": pipeline["deterministic_failures"],
            "roast_verdict":          pipeline["roast_verdict"],
            "langfuse_trace_id":      pipeline["langfuse_trace_id"],
            "model_used":             pipeline["model_used"],
            "judge_model_used":       pipeline["judge_model_used"],
        }
        _append_jsonl(ESCALATIONS_LOG, escalation_row)
        print(f"  escalation written to {ESCALATIONS_LOG}")
        return {
            "decision":           "human_review",
            "status":             status,
            "subject":            pipeline["subject"],
            "body":               pipeline["body"],
            "trace_id":           pipeline["langfuse_trace_id"],
            "contact_id":         None,
            "cost_usd":           0.0,
            "latency_ms":         None,
            "attempts":           pipeline["attempts"],
            "failed_markers":     pipeline["failed_markers"],
            "roast_verdict":      pipeline["roast_verdict"],
        }

    email_payload = {
        "subject":        pipeline["subject"],
        "body":           pipeline["body"],
        "variant_tag":    pipeline["draft"].get("variant_tag", "signal_grounded"),
        "mode_used":      pipeline["draft"].get("mode_used", "assertion"),
        "avg_confidence": pipeline["draft"].get("avg_confidence", 0.0),
    }
    send_result = send_outreach(prospect, email_payload, pipeline["usage"])
    if "error" in send_result:
        print(f"  [warn] send failed: {send_result['details']}")
        return {
            "decision":   "send_failed",
            "status":     "error",
            "subject":    pipeline["subject"],
            "body":       pipeline["body"],
            "trace_id":   send_result.get("trace_id"),
            "contact_id": None,
            "cost_usd":   0.0,
            "latency_ms": None,
            "attempts":   pipeline["attempts"],
        }
    print(f"  resend trace_id: {send_result['trace_id']} | routing: {send_result.get('routing_mode')}")
    print(f"  send latency:    {send_result['latency_ms']:.0f}ms | cost: ${send_result['cost_usd']:.5f}")

    contact_id = None
    try:
        contact_id = create_contact(prospect, hiring_signal_brief)
        print(f"  hubspot contact_id: {contact_id}")
    except Exception as e:
        print(f"  [warn] hubspot contact creation skipped: {e}")

    trace_row = {
        "timestamp":          dt.datetime.utcnow().isoformat() + "Z",
        "trace_id":           send_result["trace_id"],
        "channel":            "email",
        "prospect_email":     prospect.get("email"),
        "prospect_company":   prospect.get("company"),
        "subject":            pipeline["subject"],
        "body":               pipeline["body"],
        "word_count":         len(pipeline["body"].split()),
        "attempts":           pipeline["attempts"],
        "final_scores":       pipeline["final_scores"],
        "failed_markers":     pipeline["failed_markers"],
        "roast_verdict":      pipeline["roast_verdict"],
        "model_used":         pipeline["model_used"],
        "judge_model_used":   pipeline["judge_model_used"],
        "latency_ms":         send_result["latency_ms"],
        "cost_usd":           send_result["cost_usd"],
        "routing_mode":       send_result.get("routing_mode"),
        "intended_to":        send_result.get("intended_to"),
        "actual_to":          send_result.get("actual_to"),
        "hubspot_contact_id": contact_id,
        "langfuse_trace_id":  pipeline["langfuse_trace_id"] or send_result["trace_id"],
    }
    _append_jsonl(OUTREACH_TRACE_LOG, trace_row)

    return {
        "decision":           "send",
        "status":             status,
        "subject":            pipeline["subject"],
        "body":               pipeline["body"],
        "trace_id":           send_result["trace_id"],
        "contact_id":         contact_id,
        "cost_usd":           send_result["cost_usd"],
        "latency_ms":         send_result["latency_ms"],
        "attempts":           pipeline["attempts"],
        "failed_markers":     pipeline["failed_markers"],
        "roast_verdict":      pipeline["roast_verdict"],
    }


def run_happy_path():
    print("=== HAPPY PATH START ===")

    result = run_outreach(
        prospect=SYNTHETIC_PROSPECT,
        hiring_signal_brief=HIRING_SIGNAL_BRIEF,
        competitor_gap_brief=COMPETITOR_GAP_BRIEF,
        bench_summary=BENCH_SUMMARY,
    )

    if result["decision"] != "send":
        print(f"\n=== OUTREACH HALTED ({result['decision']}) — see eval/escalations.jsonl ===")
        return result

    webhook_base = os.environ.get("WEBHOOK_BASE_URL", "http://localhost:8000")
    try:
        httpx.post(
            f"{webhook_base}/internal/register-prospect",
            json={
                "email":   SYNTHETIC_PROSPECT["email"],
                "name":    SYNTHETIC_PROSPECT["name"],
                "company": SYNTHETIC_PROSPECT["company"],
                "phone":   SYNTHETIC_PROSPECT.get("phone", os.environ.get("DEMO_PHONE", "")),
            },
            timeout=5,
        )
        print(f"  registered: {SYNTHETIC_PROSPECT['email']} for SMS handoff")
    except Exception as exc:
        print(f"  [warn] prospect registration skipped: {exc}")

    print("\n=== OUTREACH COMPLETE — AWAITING PROSPECT REPLY ===")
    print(f"  trace_id:   {result['trace_id']}")
    print(f"  contact_id: {result['contact_id']}")
    print(f"  cost:       ${result['cost_usd']:.5f}")
    print()
    print("Next step: when prospect replies (warm intent detected),")
    print("  system sends SMS with Cal.com booking link → prospect books → HubSpot updated.")

    return result


if __name__ == "__main__":
    run_happy_path()
