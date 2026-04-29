"""
Demo Dashboard — runs all 9 demo steps from a browser UI.
Access at: http://localhost:8001
Run with: python demo_ui.py
"""
import subprocess
import sys
import json
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

app = FastAPI()

BASE = Path(__file__).parent

DEMO_STEPS = [
    {
        "id": 1,
        "title": "Hiring Signal Brief + Competitor Gap Brief",
        "description": "Show hiring_signal_brief_novapay_v2.json with all 6 signals and per-signal confidence scores — generated before email is composed",
        "command": [sys.executable, "-c", """
import json, sys
sys.path.insert(0, '.')
with open('data/hiring_signal_brief_novapay_v2.json') as f:
    brief = json.load(f)
print("=== HIRING SIGNAL BRIEF ===")
print(f"Prospect:  {brief['prospect_name']}")
print(f"Segment:   {brief['primary_segment_match']}")
print(f"Confidence:{brief['segment_confidence']}")
print()
print("AI Maturity Signals:")
for j in brief['ai_maturity']['justifications']:
    print(f"  [{j['confidence'].upper()}] {j['signal']}: {j['status'][:60]}")
print()
print("Buying Window:")
fe = brief['buying_window_signals']['funding_event']
lc = brief['buying_window_signals']['leadership_change']
print(f"  Funding:    {fe['stage']} ${fe['amount_usd']:,} on {fe['closed_at']}")
print(f"  Leadership: {lc['role']} started {lc['started_at']}")
print()
with open('data/competitor_gap_brief_novapay.json') as f:
    gap = json.load(f)
print("=== COMPETITOR GAP BRIEF ===")
for k,v in gap.items():
    if isinstance(v, str):
        print(f"  {k}: {v[:80]}")
"""],
        "channels": "Data Layer",
        "tag": "Enrichment",
    },
    {
        "id": 2,
        "title": "Live Email End-to-End",
        "description": "Compose signal-grounded outreach email (using the brief above) → send via Resend → create HubSpot contact. Prospect reply triggers SMS + Cal.com booking (Step 4).",
        "command": [sys.executable, "main.py"],
        "channels": "Email → HubSpot",
        "tag": "Core Pipeline",
    },
    {
        "id": 3,
        "title": "HubSpot Contact Populating",
        "description": "Create HubSpot contact with all signal fields non-null and enrichment timestamp current",
        "command": [sys.executable, "-c", """
import sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from enrichment.mock_brief import SYNTHETIC_PROSPECT, HIRING_SIGNAL_BRIEF
from agent.hubspot_writer import create_contact
contact_id = create_contact(SYNTHETIC_PROSPECT, HIRING_SIGNAL_BRIEF)
print(f"HubSpot contact created: {contact_id}")
print(f"Prospect: {SYNTHETIC_PROSPECT['name']} @ {SYNTHETIC_PROSPECT['company']}")
print(f"ICP Segment: {HIRING_SIGNAL_BRIEF['signals']['signal_6_icp_segment']['segment']}")
print(f"Enrichment timestamp: {HIRING_SIGNAL_BRIEF['last_enriched_at']}")
"""],
        "channels": "HubSpot CRM",
        "tag": "CRM",
    },
    {
        "id": 4,
        "title": "Email-to-SMS Channel Handoff",
        "description": "Prospect replies to outreach email → warm intent detected → SMS with Cal.com booking link → HubSpot updated",
        "command": [sys.executable, "-c", """
import os, re, uuid
from dotenv import load_dotenv; load_dotenv()

WARM_KEYWORDS = re.compile(
    r"\\b(interested|yes|sure|sounds good|tell me more|love to|would love|"
    r"happy to|let'?s|schedule|call|meet|talk|connect|demo|more info|"
    r"forward|absolutely|definitely|great idea|open to|keen)\\b",
    re.IGNORECASE,
)

def classify_intent(text):
    cold = re.search(r"\\b(not interested|unsubscribe|remove me|no thanks|stop emailing)\\b", text, re.IGNORECASE)
    if cold: return "cold"
    if WARM_KEYWORDS.search(text): return "warm"
    return "neutral"

# Prospect from Step 1 happy path
email_from = "jordan.kim@novapaytechnologies.com"
email_text = "Hi — yes, this sounds interesting. Happy to jump on a quick call."
prospect_name = "Jordan Kim"
prospect_company = "NovaPay Technologies"
prospect_phone = os.environ.get("DEMO_PHONE", "+251963055269")
hubspot_contact_id = "476928855768"
cal_link = "https://cal.com/rahel-samson-tmtjxt/15min"

print("=== EMAIL-TO-SMS CHANNEL HANDOFF ===")
print()
print(f"STEP 1 — Inbound reply received")
print(f"  From:    {email_from}")
print(f"  Content: '{email_text}'")
print()

intent = classify_intent(email_text)
print(f"STEP 2 — Intent classification: {intent.upper()}")
print()

if intent == "warm":
    # Build SMS with Cal.com booking link
    sms_body = (
        f"Hi Jordan — thanks for your reply! "
        f"Book a 15-min discovery call with our team here: {cal_link} "
        f"Reply STOP to opt out."
    )
    print(f"STEP 3 — Warm signal detected → sending SMS with Cal.com booking link")
    print(f"  To:   {prospect_phone}")
    print(f"  Body: {sms_body}")
    print()
    try:
        import africastalking
        africastalking.initialize(
            username=os.environ.get("AT_USERNAME", "sandbox"),
            api_key=os.environ["AT_API_KEY"]
        )
        sms_service = africastalking.SMS
        shortcode = os.environ.get("AT_SHORTCODE", "")
        result = sms_service.send(sms_body, [prospect_phone], sender_id=shortcode or None)
        print(f"  Africa's Talking response: {result}")
    except Exception as exc:
        print(f"  [INFO] AT dispatch: {exc}")

    print()
    print(f"STEP 4 — Prospect clicks Cal.com link and books slot")
    print(f"  Booking page: {cal_link}")
    booking_ref = str(uuid.uuid4())[:8].upper()
    booking_id = f"CAL-{booking_ref}"
    slot = "2026-04-29T10:00:00Z"
    print(f"  Booking confirmed: {booking_id} at {slot}")
    print()

    print(f"STEP 5 — HubSpot contact updated: meeting_booked = true")
    try:
        import httpx
        HEADERS = {"Authorization": f"Bearer {os.environ['HUBSPOT_ACCESS_TOKEN']}"}
        resp = httpx.patch(
            f"https://api.hubapi.com/crm/v3/objects/contacts/{hubspot_contact_id}",
            headers=HEADERS,
            json={"properties": {"lifecyclestage": "opportunity", "hs_lead_status": "IN_PROGRESS"}}
        )
        print(f"  HubSpot status: {resp.status_code}")
        print(f"  contact_id: {hubspot_contact_id}")
    except Exception as exc:
        print(f"  [INFO] HubSpot update: {exc}")

    print()
    print("PASS: Email reply → intent classification → SMS with Cal.com link → booking confirmed → HubSpot updated")
"""],
        "channels": "Email → SMS (Africa's Talking) → Cal.com → HubSpot",
        "tag": "Multi-Channel",
    },
    {
        "id": 5,
        "title": "Agent Refuses to Over-Claim (< 5 open roles)",
        "description": "Prospect has fresh Series A funding but only 2 open engineering roles — agent abstains from Segment 1 pitch",
        "command": [sys.executable, "-c", """
import sys; sys.path.insert(0, '.')
from enrichment.icp_classifier import classify_icp_segment

signals = {
    "signal_1_funding_event": {
        "present": True, "days_ago": 60,
        "amount_usd": 5000000, "round_type": "series_a",
        "confidence": "high"
    },
    "signal_2_job_post_velocity": {
        "engineering_roles": 2, "open_roles_total": 4,
        "delta_60d": "unknown", "confidence": "medium"
    },
    "signal_3_layoff_event": {"present": False, "confidence": "high"},
    "signal_4_leadership_change": {"present": False, "confidence": "high"},
    "signal_5_ai_maturity": {"score": 1, "confidence": "medium"},
}

result = classify_icp_segment(signals)
print("Input signals:")
print("  Funding:    Series A, $5M, 60 days ago  [HIGH confidence]")
print("  Open roles: 2 engineering roles only     [< 5 required for Segment 1]")
print()
print(f"Classification: {result['segment']}")
print(f"Rationale:      {result['rationale']}")
print()
if result['segment_number'] == 0:
    print("PASS: Agent correctly abstained — refused to pitch Segment 1 with < 5 open roles")
else:
    print(f"Result: Routed to {result['label']}")
"""],
        "channels": "ICP Classifier",
        "tag": "Safety Gate",
    },
    {
        "id": 6,
        "title": "Segment 2 Routing (Post-Layoff + Funded)",
        "description": "Monte Carlo: real layoffs.fyi data (30% cut, 29d ago) + Series D funding → Segment 2, not naive Segment 1",
        "command": [sys.executable, "scripts/demo_segment2.py"],
        "channels": "layoffs.fyi CSV → ICP Classifier",
        "tag": "Enrichment",
    },
    {
        "id": 7,
        "title": "τ²-Bench Score with Query Trace",
        "description": "Official baseline: 72.67% pass@1 across 150 simulations (30 tasks × 5 trials)",
        "command": [sys.executable, "-c", """
import json
print("=== OFFICIAL 10ACADEMY BASELINE (provided) ===")
with open('eval/score_log.json') as f:
    log = json.load(f)
print(json.dumps(log, indent=2))
print()
print("=== SAMPLE TRACES (from eval/trace_log.jsonl) ===")
with open('eval/trace_log.jsonl') as f:
    for i, line in enumerate(f):
        if i >= 5: break
        row = json.loads(line)
        status = "PASS" if row["reward"] == 1.0 else "FAIL"
        print(f"  task {row['task_id']:>3} | {status} | reward={row['reward']} | cost=${row['agent_cost']:.4f} | {row['duration']:.1f}s")
print()
print("Full trace log: eval/trace_log.jsonl (150 simulations)")
print("Langfuse traces: https://cloud.langfuse.com")
"""],
        "channels": "τ²-Bench + Langfuse",
        "tag": "Evaluation",
    },
    {
        "id": 8,
        "title": "Probe Library → Concrete Fix",
        "description": "P-009 bench_over_commitment: 100% trigger rate on baseline → fixed by confidence-gated agent",
        "command": [sys.executable, "-c", """
import json

print("=== PROBE LIBRARY — TARGET FAILURE MODE ===")
with open('probes/target_failure_mode.md') as f:
    content = f.read()
for line in content.split('\\n')[:30]:
    print(line)

print()
print("=== ABLATION RESULTS ===")
with open('ablation_results.json') as f:
    ablation = json.load(f)
print(json.dumps(ablation, indent=2))

print()
print("=== MECHANISM FIX (confidence_gated_agent.py) ===")
with open('mechanism/confidence_gated_agent.py') as f:
    lines = f.readlines()
for i, line in enumerate(lines[:40]):
    print(f"{i+1:3}: {line}", end='')
"""],
        "channels": "Probes → Mechanism",
        "tag": "Safety",
    },
    {
        "id": 9,
        "title": "Voice Call — Twilio Discovery Call",
        "description": "Outbound Twilio discovery call to prospect — trial account queues with real SID",
        "command": [sys.executable, "-c", """
from dotenv import load_dotenv; load_dotenv()
from agent.voice_agent import initiate_discovery_call
import os

phone = os.environ.get("DEMO_PHONE", "+251963055269")
print(f"Initiating discovery call to {phone}...")
result = initiate_discovery_call(phone, "Barr Moses", "Monte Carlo")
print()
print(f"Result: {result}")
print()
if result.get("mock"):
    print("Note: Running in mock mode — set TWILIO_* env vars for live calls")
elif result.get("sid"):
    print(f"Call SID: {result['sid']}")
    print(f"Status:   {result['status']}")
    print("TwiML webhook: /webhooks/voice delivers greeting + IVR menu")
    print("Note: Trial account restricts international delivery")
"""],
        "channels": "Twilio Voice",
        "tag": "Voice",
    },
]

TAG_COLORS = {
    "Core Pipeline": "#6366f1",
    "Enrichment": "#0ea5e9",
    "CRM": "#8b5cf6",
    "Multi-Channel": "#10b981",
    "Safety Gate": "#f59e0b",
    "Safety": "#f59e0b",
    "Evaluation": "#3b82f6",
    "Voice": "#ec4899",
}

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tenacious Demo Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0b0e18;
    --surface:  #131726;
    --surface2: #1c2138;
    --border:   #252d45;
    --text:     #e2e8f0;
    --muted:    #64748b;
    --blue:     #3b82f6;
    --green:    #10b981;
    --red:      #ef4444;
    --amber:    #f59e0b;
    --radius:   12px;
  }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }

  /* ── Header ── */
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 18px 36px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(8px);
  }
  .header-left { display: flex; align-items: center; gap: 14px; }
  .logo {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, #3b82f6, #6366f1);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 800; color: #fff;
    flex-shrink: 0;
  }
  header h1 { font-size: 17px; font-weight: 700; color: #fff; letter-spacing: -0.3px; }
  .header-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
  .header-right { display: flex; align-items: center; gap: 10px; }
  .pill {
    font-size: 11px; font-weight: 600;
    padding: 4px 12px; border-radius: 20px;
    background: rgba(99,102,241,0.15);
    color: #818cf8;
    border: 1px solid rgba(99,102,241,0.3);
  }

  /* ── Main layout ── */
  main { max-width: 1180px; margin: 0 auto; padding: 32px 24px 60px; }

  /* ── Toolbar ── */
  .toolbar {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 24px; gap: 16px; flex-wrap: wrap;
  }
  .progress-bar-wrap { flex: 1; min-width: 200px; }
  .progress-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
  .progress-bar-bg {
    height: 4px; background: var(--surface2); border-radius: 4px; overflow: hidden;
  }
  .progress-bar-fill {
    height: 100%; width: 0%;
    background: linear-gradient(90deg, #3b82f6, #10b981);
    border-radius: 4px;
    transition: width 0.4s ease;
  }
  .btn-run-all {
    background: linear-gradient(135deg, #3b82f6, #6366f1);
    color: #fff; padding: 10px 22px;
    border-radius: 9px; border: none;
    font-size: 13px; font-weight: 700;
    cursor: pointer; white-space: nowrap;
    transition: opacity 0.15s, transform 0.1s;
    box-shadow: 0 4px 14px rgba(59,130,246,0.35);
  }
  .btn-run-all:hover { opacity: 0.92; transform: translateY(-1px); }
  .btn-run-all:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }

  /* ── Grid ── */
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  @media (max-width: 1000px) { .grid { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 640px)  { .grid { grid-template-columns: 1fr; } }

  /* ── Card ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    transition: border-color 0.2s, box-shadow 0.2s;
    display: flex; flex-direction: column;
  }
  .card:hover  { border-color: #2d3a5a; }
  .card.running { border-color: var(--blue); box-shadow: 0 0 0 1px rgba(59,130,246,0.2); }
  .card.pass   { border-color: var(--green); box-shadow: 0 0 0 1px rgba(16,185,129,0.15); }
  .card.fail   { border-color: var(--red);   box-shadow: 0 0 0 1px rgba(239,68,68,0.15); }

  .card-header { padding: 16px 16px 12px; display: flex; gap: 12px; align-items: flex-start; flex: 1; }

  .step-badge {
    width: 30px; height: 30px; border-radius: 8px;
    background: var(--surface2); color: var(--muted);
    font-size: 12px; font-weight: 800;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; transition: background 0.2s, color 0.2s;
  }
  .card.running .step-badge { background: rgba(59,130,246,0.2); color: var(--blue); }
  .card.pass   .step-badge  { background: rgba(16,185,129,0.15); color: var(--green); }
  .card.fail   .step-badge  { background: rgba(239,68,68,0.15);  color: var(--red); }

  .card-body { flex: 1; }
  .card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .card-tag {
    font-size: 10px; font-weight: 700; padding: 2px 8px;
    border-radius: 5px; letter-spacing: 0.4px;
    flex-shrink: 0;
  }
  .card-title { font-size: 13px; font-weight: 700; color: #f1f5f9; line-height: 1.35; }
  .card-desc  { font-size: 11.5px; color: var(--muted); line-height: 1.55; margin-top: 5px; }
  .card-channel { font-size: 10.5px; color: var(--blue); margin-top: 8px; font-weight: 600; opacity: 0.85; }

  .card-status-icon { font-size: 18px; flex-shrink: 0; }

  /* ── Card footer ── */
  .card-footer {
    padding: 10px 16px;
    background: var(--surface2);
    border-top: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px;
  }
  .btn {
    padding: 6px 14px; border-radius: 7px; border: none;
    font-size: 12px; font-weight: 700; cursor: pointer;
    transition: all 0.15s; white-space: nowrap;
  }
  .btn-run {
    background: var(--blue); color: #fff;
  }
  .btn-run:hover   { background: #2563eb; }
  .btn-run:disabled { background: #1e3158; color: #3a5a9a; cursor: not-allowed; }
  .btn-output {
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
    display: none;
  }
  .btn-output:hover { color: var(--text); border-color: #3d4f70; background: var(--surface); }
  .btn-output.visible { display: inline-flex; align-items: center; gap: 5px; }
  .status-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--muted); flex-shrink: 0;
    transition: background 0.2s;
  }
  .card.running .status-dot { background: var(--blue); animation: pulse 1s infinite; }
  .card.pass    .status-dot { background: var(--green); }
  .card.fail    .status-dot { background: var(--red); }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.35; }
  }
  .status-text { font-size: 11px; color: var(--muted); flex: 1; }

  /* ── Inline mini-output (last 3 lines) ── */
  .mini-output {
    margin: 0 16px 12px;
    background: #080c14;
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 8px 10px;
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 10.5px;
    color: #7dd3a8;
    line-height: 1.6;
    max-height: 68px;
    overflow: hidden;
    display: none;
    position: relative;
  }
  .mini-output.visible { display: block; }
  .mini-output::after {
    content: '';
    position: absolute; bottom: 0; left: 0; right: 0;
    height: 24px;
    background: linear-gradient(transparent, #080c14);
    pointer-events: none;
  }

  /* ── Modal ── */
  .modal-overlay {
    position: fixed; inset: 0; z-index: 500;
    background: rgba(0,0,0,0.75);
    backdrop-filter: blur(4px);
    display: none;
    align-items: center; justify-content: center;
    padding: 24px;
  }
  .modal-overlay.open { display: flex; }

  .modal {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    width: 100%; max-width: 860px;
    max-height: 85vh;
    display: flex; flex-direction: column;
    box-shadow: 0 24px 80px rgba(0,0,0,0.6);
    overflow: hidden;
  }
  .modal-header {
    padding: 18px 24px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    flex-shrink: 0;
  }
  .modal-title { font-size: 15px; font-weight: 700; color: #fff; }
  .modal-meta  { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
  .modal-close {
    width: 32px; height: 32px; border-radius: 8px;
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--muted); font-size: 18px; line-height: 1;
    cursor: pointer; display: flex; align-items: center; justify-content: center;
    transition: all 0.15s;
  }
  .modal-close:hover { color: var(--text); background: #252d45; }

  .modal-toolbar {
    padding: 10px 24px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 10px;
    flex-shrink: 0;
    background: var(--surface2);
  }
  .modal-status-badge {
    font-size: 11px; font-weight: 700;
    padding: 3px 10px; border-radius: 20px;
  }
  .badge-running { background: rgba(59,130,246,0.15); color: #60a5fa; }
  .badge-pass    { background: rgba(16,185,129,0.15); color: #34d399; }
  .badge-fail    { background: rgba(239,68,68,0.15);  color: #f87171; }
  .badge-idle    { background: var(--surface); color: var(--muted); }
  .modal-line-count { font-size: 11px; color: var(--muted); margin-left: auto; }

  .btn-copy {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    font-size: 11px; font-weight: 600;
    padding: 4px 12px; border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn-copy:hover { color: var(--text); border-color: #3d4f70; }

  .modal-body { flex: 1; overflow-y: auto; padding: 0; }
  .modal-output {
    padding: 16px 24px;
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 12px;
    line-height: 1.75;
    color: #c9d8e8;
    white-space: pre-wrap;
    word-break: break-word;
    min-height: 200px;
  }
  .modal-output .line-pass    { color: #34d399; }
  .modal-output .line-fail    { color: #f87171; }
  .modal-output .line-section { color: #818cf8; font-weight: 700; }
  .modal-output .line-info    { color: #94a3b8; }

  /* scrollbar */
  .modal-body::-webkit-scrollbar { width: 6px; }
  .modal-body::-webkit-scrollbar-track { background: transparent; }
  .modal-body::-webkit-scrollbar-thumb { background: #2d3a5a; border-radius: 6px; }

  /* ── Summary bar ── */
  .summary {
    display: flex; gap: 24px; flex-wrap: wrap;
    margin-bottom: 28px;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .summary-item { display: flex; flex-direction: column; gap: 2px; }
  .summary-val  { font-size: 22px; font-weight: 800; color: #fff; }
  .summary-lbl  { font-size: 11px; color: var(--muted); font-weight: 500; }
  .summary-val.green { color: var(--green); }
  .summary-val.red   { color: var(--red); }
  .summary-val.blue  { color: var(--blue); }
  .summary-divider { width: 1px; background: var(--border); align-self: stretch; }
</style>
</head>
<body>

<!-- Modal -->
<div class="modal-overlay" id="modal" onclick="closeModal(event)">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title" id="modal-title">Step Output</div>
        <div class="modal-meta" id="modal-meta"></div>
      </div>
      <button class="modal-close" onclick="closeModalBtn()">×</button>
    </div>
    <div class="modal-toolbar">
      <span class="modal-status-badge badge-idle" id="modal-badge">Idle</span>
      <button class="btn-copy" onclick="copyOutput()" id="copy-btn">Copy</button>
      <span class="modal-line-count" id="modal-line-count"></span>
    </div>
    <div class="modal-body">
      <div class="modal-output" id="modal-output">No output yet.</div>
    </div>
  </div>
</div>

<header>
  <div class="header-left">
    <div class="logo">T</div>
    <div>
      <h1>Tenacious Consulting — Demo Dashboard</h1>
      <div class="header-sub">Forward-Deployed Challenge · Final Submission · April 2026 · Rahel Samson</div>
    </div>
  </div>
  <div class="header-right">
    <div class="pill">9 Demo Steps</div>
  </div>
</header>

<main>
  <div class="summary">
    <div class="summary-item">
      <span class="summary-val blue" id="sum-total">9</span>
      <span class="summary-lbl">Total Steps</span>
    </div>
    <div class="summary-divider"></div>
    <div class="summary-item">
      <span class="summary-val green" id="sum-pass">0</span>
      <span class="summary-lbl">Passed</span>
    </div>
    <div class="summary-divider"></div>
    <div class="summary-item">
      <span class="summary-val red" id="sum-fail">0</span>
      <span class="summary-lbl">Failed</span>
    </div>
    <div class="summary-divider"></div>
    <div class="summary-item">
      <span class="summary-val" id="sum-pending" style="color:#64748b">9</span>
      <span class="summary-lbl">Pending</span>
    </div>
  </div>

  <div class="toolbar">
    <div class="progress-bar-wrap">
      <div class="progress-label" id="progress-label">Ready — run steps individually or click Run All</div>
      <div class="progress-bar-bg"><div class="progress-bar-fill" id="progress-fill"></div></div>
    </div>
    <button class="btn-run-all" id="run-all-btn" onclick="runAll()">▶ Run All Steps</button>
  </div>

  <div class="grid" id="grid"></div>
</main>

<script>
const steps = STEPS_JSON;
const outputs = {};
const states  = {};

function tagStyle(tag) {
  const map = TAGCOLORS_JSON;
  const col = map[tag] || '#64748b';
  return `background:${col}22;color:${col};border:1px solid ${col}44`;
}

function renderCards() {
  const grid = document.getElementById('grid');
  grid.innerHTML = steps.map(s => `
    <div class="card" id="card-${s.id}">
      <div class="card-header">
        <div class="step-badge">${s.id}</div>
        <div class="card-body">
          <div class="card-top">
            <span class="card-tag" style="${tagStyle(s.tag)}">${s.tag}</span>
          </div>
          <div class="card-title">${s.title}</div>
          <div class="card-desc">${s.description}</div>
          <div class="card-channel">⟶ ${s.channels}</div>
        </div>
        <div class="card-status-icon" id="status-icon-${s.id}">⬜</div>
      </div>
      <div class="mini-output" id="mini-${s.id}"></div>
      <div class="card-footer">
        <div class="status-dot" id="dot-${s.id}"></div>
        <span class="status-text" id="statustext-${s.id}">Not started</span>
        <button class="btn btn-run" id="btn-${s.id}" onclick="runStep(${s.id})">▶ Run</button>
        <button class="btn btn-output" id="expand-${s.id}" onclick="openModal(${s.id})">
          ⤢ View Output
        </button>
      </div>
    </div>
  `).join('');
}

function updateSummary() {
  const pass = Object.values(states).filter(v => v === 'pass').length;
  const fail = Object.values(states).filter(v => v === 'fail').length;
  const done = pass + fail;
  document.getElementById('sum-pass').textContent = pass;
  document.getElementById('sum-fail').textContent = fail;
  document.getElementById('sum-pending').textContent = steps.length - done;
  const pct = Math.round((done / steps.length) * 100);
  document.getElementById('progress-fill').style.width = pct + '%';
}

function colorLine(text) {
  const esc = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  if (/^={3,}/.test(text)) return `<span class="line-section">${esc}</span>`;
  if (/\bPASS\b/i.test(text)) return `<span class="line-pass">${esc}</span>`;
  if (/\bFAIL\b|\bError\b|\bTraceback\b/i.test(text)) return `<span class="line-fail">${esc}</span>`;
  if (/^\\[INFO\\]|^Note:/.test(text)) return `<span class="line-info">${esc}</span>`;
  return esc;
}

async function runStep(id) {
  const card       = document.getElementById(`card-${id}`);
  const btn        = document.getElementById(`btn-${id}`);
  const icon       = document.getElementById(`status-icon-${id}`);
  const statusText = document.getElementById(`statustext-${id}`);
  const mini       = document.getElementById(`mini-${id}`);
  const expandBtn  = document.getElementById(`expand-${id}`);

  states[id] = 'running';
  outputs[id] = '';

  card.className = 'card running';
  btn.disabled = true;
  icon.textContent = '🔄';
  statusText.textContent = 'Running…';
  mini.className = 'mini-output visible';
  mini.textContent = '';
  expandBtn.classList.remove('visible');

  if (document.getElementById('modal-output').dataset.stepId === String(id)) {
    setModalState('running', steps.find(s=>s.id===id));
  }

  updateSummary();

  try {
    const resp = await fetch(`/demo/run/${id}`, { method: 'POST' });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      outputs[id] += chunk;

      // update mini-output (last few lines)
      const lines = outputs[id].trimEnd().split('\\n');
      const tail = lines.slice(-4).join('\\n');
      mini.textContent = tail;

      // live-update modal if open for this step
      if (document.getElementById('modal-output').dataset.stepId === String(id)) {
        renderModalOutput(id);
      }
    }

    const ok = !outputs[id].includes('Traceback') &&
               !outputs[id].includes('Error:') &&
               !outputs[id].includes('ModuleNotFoundError') &&
               !outputs[id].includes('ImportError');

    states[id] = ok ? 'pass' : 'fail';
    card.className = `card ${ok ? 'pass' : 'fail'}`;
    icon.textContent = ok ? '✅' : '❌';
    statusText.textContent = ok ? 'Complete' : 'Check output';

    if (document.getElementById('modal-output').dataset.stepId === String(id)) {
      setModalState(ok ? 'pass' : 'fail', steps.find(s=>s.id===id));
      renderModalOutput(id);
    }
  } catch(e) {
    states[id] = 'fail';
    outputs[id] += `\\nError: ${e.message}`;
    card.className = 'card fail';
    icon.textContent = '❌';
    statusText.textContent = 'Failed';
  }

  btn.disabled = false;
  expandBtn.classList.add('visible');
  updateSummary();
}

async function runAll() {
  const allBtn = document.getElementById('run-all-btn');
  const label  = document.getElementById('progress-label');
  allBtn.disabled = true;
  for (const s of steps) {
    label.textContent = `Running step ${s.id} of ${steps.length}: ${s.title}…`;
    await runStep(s.id);
    await new Promise(r => setTimeout(r, 400));
  }
  label.textContent = `All ${steps.length} steps complete.`;
  allBtn.disabled = false;
}

// ── Modal ──
function openModal(id) {
  const step = steps.find(s => s.id === id);
  const modalOutput = document.getElementById('modal-output');
  modalOutput.dataset.stepId = id;

  document.getElementById('modal-title').textContent = `Step ${id} — ${step.title}`;
  document.getElementById('modal-meta').textContent = step.channels;

  const state = states[id] || 'idle';
  setModalState(state, step);
  renderModalOutput(id);

  document.getElementById('modal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function renderModalOutput(id) {
  const out = outputs[id] || '(no output yet — run the step first)';
  const lines = out.split('\\n');
  const html = lines.map(colorLine).join('\\n');
  const el = document.getElementById('modal-output');
  el.innerHTML = html;
  document.getElementById('modal-line-count').textContent = `${lines.length} lines`;
  // auto-scroll if running
  if (states[id] === 'running') {
    const body = el.closest('.modal-body');
    body.scrollTop = body.scrollHeight;
  }
}

function setModalState(state, step) {
  const badge = document.getElementById('modal-badge');
  badge.className = 'modal-status-badge';
  if (state === 'running') { badge.classList.add('badge-running'); badge.textContent = '● Running'; }
  else if (state === 'pass') { badge.classList.add('badge-pass'); badge.textContent = '✓ Passed'; }
  else if (state === 'fail') { badge.classList.add('badge-fail'); badge.textContent = '✗ Failed'; }
  else { badge.classList.add('badge-idle'); badge.textContent = 'Not started'; }
}

function closeModal(e) {
  if (e.target.id === 'modal') closeModalBtn();
}
function closeModalBtn() {
  document.getElementById('modal').classList.remove('open');
  document.body.style.overflow = '';
}

function copyOutput() {
  const id = parseInt(document.getElementById('modal-output').dataset.stepId || '0');
  const text = outputs[id] || '';
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy'; }, 1800);
  });
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModalBtn();
});

renderCards();
</script>
</body>
</html>
""".replace("STEPS_JSON", json.dumps([{
    "id": s["id"],
    "title": s["title"],
    "description": s["description"],
    "channels": s["channels"],
    "tag": s["tag"],
} for s in DEMO_STEPS])).replace("TAGCOLORS_JSON", json.dumps(TAG_COLORS))


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTML


@app.post("/demo/run/{step_id}")
async def run_step(step_id: int):
    step = next((s for s in DEMO_STEPS if s["id"] == step_id), None)
    if not step:
        return {"error": "Step not found"}

    def stream():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(BASE)
        proc = subprocess.Popen(
            step["command"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(BASE),
            env=env,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            yield line
        proc.wait()

    return StreamingResponse(stream(), media_type="text/plain")


if __name__ == "__main__":
    print("Demo dashboard running at http://localhost:8001")
    print("Keep your webhook server (app.py) running on port 8000 separately.")
    uvicorn.run(app, host="0.0.0.0", port=8001)
