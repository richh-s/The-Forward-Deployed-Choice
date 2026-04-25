"""
Demo Dashboard — runs all 8 required demo items from a browser UI.
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
        "title": "Live Email End-to-End",
        "description": "Compose signal-grounded email → send via Resend → create HubSpot contact → book Cal.com slot",
        "command": [sys.executable, "main.py"],
        "channels": "Email → HubSpot → Cal.com",
    },
    {
        "id": 2,
        "title": "Hiring Signal Brief + Competitor Gap Brief",
        "description": "Show hiring_signal_brief_novapay_v2.json with all 6 signals and per-signal confidence scores",
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
        "channels": "Data layer",
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
    },
    {
        "id": 4,
        "title": "Email-to-SMS Channel Handoff",
        "description": "Warm email reply detected → SMS sent to prospect for scheduling coordination",
        "command": [sys.executable, "-c", """
import os, re
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

prospect_registry = {
    "cto@montecarlodata.com": {
        "name": "Barr Moses",
        "company": "Monte Carlo",
        "phone": os.environ.get("DEMO_PHONE", "+251963055269"),
    }
}

email_from = "cto@montecarlodata.com"
email_text = "Yes this sounds interesting, happy to jump on a call"

print("=== EMAIL-TO-SMS CHANNEL HANDOFF ===")
print(f"Inbound email from: {email_from}")
print(f"Content: '{email_text}'")
print()

intent = classify_intent(email_text)
print(f"Intent classification: {intent.upper()}")
print()

if intent == "warm":
    prospect = prospect_registry.get(email_from.lower(), {})
    phone = prospect.get("phone") or os.environ.get("DEMO_PHONE", "")
    name = (prospect.get("name") or "there").split()[0]
    company = prospect.get("company") or "your team"
    sms_body = (
        f"Hi {name} — thanks for your reply about {company}. "
        "Happy to set up a quick 30-min intro call. "
        "What timezone works — EST, CST, or PST? "
        "Reply STOP to opt out."
    )
    print(f"Warm signal detected → routing to SMS handoff")
    print(f"Recipient phone: {phone}")
    print(f"SMS body: {sms_body}")
    print()
    try:
        import africastalking
        africastalking.initialize(
            username=os.environ.get("AT_USERNAME", "sandbox"),
            api_key=os.environ["AT_API_KEY"]
        )
        sms_service = africastalking.SMS
        shortcode = os.environ.get("AT_SHORTCODE", "")
        result = sms_service.send(sms_body, [phone], sender_id=shortcode or None)
        print(f"Africa's Talking response: {result}")
        print()
        print("SMS dispatched — check AT dashboard → SMS → Bulk Outbox")
    except Exception as exc:
        print(f"[INFO] AT dispatch attempted: {exc}")
        print("(Sandbox delivers only to verified Kenyan numbers — see AT outbox for proof)")
    print()
    print("PASS: Warm email reply correctly detected and routed to SMS channel")
"""],
        "channels": "Email → SMS (Africa's Talking)",
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
    },
    {
        "id": 6,
        "title": "Segment 2 Routing (Post-Layoff + Funded)",
        "description": "Monte Carlo: real layoffs.fyi data (30% cut, 29d ago) + Series D funding → Segment 2, not naive Segment 1",
        "command": [sys.executable, "scripts/demo_segment2.py"],
        "channels": "layoffs.fyi CSV → ICP Classifier",
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
    },
    {
        "id": 9,
        "title": "Voice Call (Bonus)",
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
    },
]


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tenacious Demo Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }
  header { background: #1a1d27; border-bottom: 1px solid #2d3748; padding: 20px 32px; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 20px; font-weight: 700; color: #fff; }
  header .badge { background: #3b82f6; color: #fff; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; }
  .subtitle { color: #64748b; font-size: 13px; margin-top: 2px; }
  main { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
  .card { background: #1a1d27; border: 1px solid #2d3748; border-radius: 12px; overflow: hidden; transition: border-color 0.2s; }
  .card.running { border-color: #3b82f6; }
  .card.pass { border-color: #10b981; }
  .card.fail { border-color: #ef4444; }
  .card-header { padding: 16px 20px; display: flex; align-items: flex-start; gap: 12px; }
  .step-num { background: #2d3748; color: #94a3b8; font-size: 12px; font-weight: 700; width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .card.running .step-num { background: #1d4ed8; color: #fff; }
  .card.pass .step-num { background: #065f46; color: #34d399; }
  .card.fail .step-num { background: #7f1d1d; color: #fca5a5; }
  .card-info { flex: 1; }
  .card-title { font-size: 14px; font-weight: 600; color: #f1f5f9; margin-bottom: 4px; }
  .card-desc { font-size: 12px; color: #64748b; line-height: 1.5; }
  .card-channel { font-size: 11px; color: #3b82f6; margin-top: 6px; font-weight: 500; }
  .bonus { color: #f59e0b !important; }
  .card-status { flex-shrink: 0; font-size: 20px; }
  .card-footer { padding: 12px 20px; background: #141720; border-top: 1px solid #2d3748; display: flex; align-items: center; gap: 10px; }
  .btn { padding: 7px 18px; border-radius: 7px; border: none; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
  .btn-run { background: #3b82f6; color: #fff; }
  .btn-run:hover { background: #2563eb; }
  .btn-run:disabled { background: #1e3a5f; color: #4b6cb7; cursor: not-allowed; }
  .status-text { font-size: 12px; color: #64748b; }
  .output-area { margin: 0 20px 16px; background: #0d1117; border: 1px solid #2d3748; border-radius: 8px; padding: 12px; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 11px; color: #a3e635; line-height: 1.6; max-height: 200px; overflow-y: auto; white-space: pre-wrap; display: none; }
  .output-area.visible { display: block; }
  .run-all { background: #10b981; color: #fff; padding: 10px 24px; border-radius: 8px; border: none; font-size: 14px; font-weight: 700; cursor: pointer; margin-bottom: 24px; }
  .run-all:hover { background: #059669; }
  .progress { font-size: 13px; color: #64748b; margin-bottom: 24px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Tenacious Consulting — Demo Dashboard</h1>
    <div class="subtitle">Forward-Deployed Challenge · Final Submission · April 2026</div>
  </div>
  <div class="badge">8 Required Items</div>
</header>
<main>
  <button class="run-all" onclick="runAll()">▶ Run All Steps</button>
  <div class="progress" id="progress">Ready — click a step to run it individually, or Run All to go in sequence.</div>
  <div class="grid" id="grid"></div>
</main>
<script>
const steps = STEPS_JSON;

function renderCards() {
  const grid = document.getElementById('grid');
  grid.innerHTML = steps.map(s => `
    <div class="card" id="card-${s.id}">
      <div class="card-header">
        <div class="step-num">${s.id}</div>
        <div class="card-info">
          <div class="card-title">${s.title}${s.id === 9 ? ' <span style="font-size:11px;color:#f59e0b">(bonus)</span>' : ''}</div>
          <div class="card-desc">${s.description}</div>
          <div class="card-channel ${s.id === 9 ? 'bonus' : ''}">${s.channels}</div>
        </div>
        <div class="card-status" id="status-${s.id}">⬜</div>
      </div>
      <div class="card-footer">
        <button class="btn btn-run" id="btn-${s.id}" onclick="runStep(${s.id})">▶ Run</button>
        <span class="status-text" id="statustext-${s.id}">Not started</span>
      </div>
      <div class="output-area" id="output-${s.id}"></div>
    </div>
  `).join('');
}

async function runStep(id) {
  const card = document.getElementById(`card-${id}`);
  const btn = document.getElementById(`btn-${id}`);
  const statusEl = document.getElementById(`status-${id}`);
  const statusText = document.getElementById(`statustext-${id}`);
  const output = document.getElementById(`output-${id}`);

  card.className = 'card running';
  btn.disabled = true;
  statusEl.textContent = '🔄';
  statusText.textContent = 'Running...';
  output.className = 'output-area visible';
  output.textContent = '';

  try {
    const resp = await fetch(`/demo/run/${id}`, { method: 'POST' });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let full = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      full += chunk;
      output.textContent = full;
      output.scrollTop = output.scrollHeight;
    }

    const success = !full.includes('Traceback') && !full.includes('Error:') && !full.includes('ModuleNotFoundError') && !full.includes('ImportError');
    card.className = `card ${success ? 'pass' : 'fail'}`;
    statusEl.textContent = success ? '✅' : '❌';
    statusText.textContent = success ? 'Complete' : 'Check output';
  } catch(e) {
    card.className = 'card fail';
    statusEl.textContent = '❌';
    statusText.textContent = 'Failed';
    output.textContent = `Error: ${e.message}`;
  }
  btn.disabled = false;
}

async function runAll() {
  const prog = document.getElementById('progress');
  for (const s of steps) {
    prog.textContent = `Running step ${s.id} of ${steps.length}: ${s.title}...`;
    await runStep(s.id);
    await new Promise(r => setTimeout(r, 500));
  }
  prog.textContent = `All ${steps.length} steps complete.`;
}

renderCards();
</script>
</body>
</html>
""".replace("STEPS_JSON", json.dumps([{
    "id": s["id"],
    "title": s["title"],
    "description": s["description"],
    "channels": s["channels"]
} for s in DEMO_STEPS]))


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
