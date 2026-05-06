# Grounding Commit — Rahel Samson

**Artifact edited:** `probes/probe_library.md`

**Edit locations:** P-023 and P-026 — both probes in the `dual_control_coordination` and `scheduling_edge_cases` categories.

---

## What Changed and Why

Both probes previously described the failure as the "agent" taking a wrong action, with the hypothesis framed as model behaviour. P-023 said "Agent writes to HubSpot before email confirmed delivered." P-026 said "Agent double-books a slot already taken in Cal.com."

Neither description was accurate. The model never writes to HubSpot. The model never books a Cal.com slot. The model outputs a JSON string. Python code in `agent/hubspot_writer.py` and `agent/calendar.py` reads that string and calls the external APIs. The model's job ends at generating valid JSON — and in both traces it did. The failure is that the scaffolding layer executed the action without checking preconditions.

**Specific changes made to each probe:**

- `hypothesis` field: reworded to name the scaffolding as the responsible layer
- Added `failure_layer` field: "scaffolding (not model)" with a one-sentence explanation of which file and which missing check causes the failure
- Added `fix_layer` field: names the file to fix (`hubspot_writer.py`, `calendar.py`) and confirms the model prompt does not need to change

**Why this matters:** Probes that misattribute failures produce wrong fix strategies. If P-023 is read as a model failure, an engineer adds instructions to the system prompt. The right fix is adding a delivery-confirmation gate in `hubspot_writer.py` before the API call. The probe description now makes this unambiguous. Same logic applies to P-026 — the fix is an availability check in `calendar.py`, not a prompt change.

**Commit message:** `fix: reattribute P-023 and P-026 failures to scaffolding layer (Week 12 Day 2 grounding)`
