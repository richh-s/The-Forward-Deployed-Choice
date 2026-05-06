# Morning Call Summary — Day 2

**Date:** 2026-05-06
**Topic:** Agent and Tool-Use Internals
**Participants:** Lidya Dagnew & Rahel Samson

## Ambiguity & Sharpening

### Lidya's Question:
- **Initial:** I use prompt-stuffing instead of tools. How does tool-use work?
- **Sharpening:** We focused on the **token-level mechanics**. We realized the question isn't just about API syntax, but how the `tools` parameter actually restricts or shifts the probability distribution compared to raw text prompting.

### Rahel's Question:
- **Initial:** My agent fails to write to HubSpot. Why?
- **Sharpening:** The question was sharpened to focus on **Structured Output vs. Native Tool-Use**. Rahel is using JSON mode to simulate decisions, but attributing failures (like double-booking or bad CRM writes) to the model. We redefined the gap to ask: what is the token-level difference between generating a JSON field (constrained decoding) and a function call, so she can attribute failures correctly (scaffolding vs. model).

## Final Questions Finalized
Both partners confirmed that the questions are unambiguous and hit the "resolvable in one explainer" criteria.
