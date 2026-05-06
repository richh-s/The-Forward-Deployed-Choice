# Question — Rahel Samson, Day 2

**Topic:** Agent and tool-use internals

**Partner:** Lidya Dagnaw

---

## Final Sharpened Question

My agent in `agent/email_agent.py` uses `Return valid JSON only` to get structured output — fields like `variant_tag` and `mode_used` which the pipeline treats as decisions the agent made. But probes P-023 (HubSpot write) and P-026 (Cal.com double-booking) describe these as model failures, when the model has no tool to call — Python parses a string and acts on it. I cannot explain what the model is actually doing at the token level when it generates a JSON field versus what it would do if it were calling a real function. Knowing this would let me correctly rewrite P-023 and P-026 to attribute failure to the scaffolding, not the model.

**Artifact:** `agent/email_agent.py` and `probes/probe_library.md` P-023, P-026.
