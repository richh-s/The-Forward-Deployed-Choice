# Sign-off — Rahel Samson

**Gap closure status: CLOSED**

---

## What I Understand Now That I Did Not Before

Before this explainer I could say "my probes test HubSpot writes and Cal.com bookings" without being able to explain who is actually responsible for those actions. I described P-023 and P-026 as model failures because the model produced output that led to the wrong action. The explainer closed two things precisely.

**The mechanism:** When I use `Return valid JSON only` in my system prompt, the model produces text. My Python code reads that text and decides whether to write to HubSpot. The model has no awareness that HubSpot exists, no ability to check delivery status, and no responsibility for what Python does after parsing its output. The "decision" to write to HubSpot is made by the scaffolding, not the model. The model's contribution ends at the JSON string.

**The specific concept that landed:** Logit masking. Lidya's explainer named that grammar-based constrained decoding mechanically prevents the model from generating invalid syntax — and that means if the JSON is valid but the *logic* is wrong (writing to HubSpot before email delivery is confirmed), that is definitionally a scaffolding failure. The model passed its check. The scaffolding failed its check.

This directly changes P-023 and P-026 in `probes/probe_library.md`. Both probes currently read as model failures. After this explainer, I can rewrite them to correctly name the scaffolding as the responsible layer, which makes the probe descriptions accurate and makes the failure mode actionable — you fix scaffolding failures differently from model failures.

See `grounding_commit.md` for the actual edits made to `probes/probe_library.md`.
