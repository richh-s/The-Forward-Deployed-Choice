# Evening Call Summary — Day 1

*Written by: Rahel Samson | Confirmed by: Zemzem Hibet*

## What Happened

Zemzem's feedback on the KV cache explainer was specific: the initial draft named the bytes-per-token formula but did not show the actual numbers for the Qwen2.5-7B architecture used in the project, making the derivation feel abstract. The draft was revised to include the full Python computation with layer count, KV head count, and head dimension filled in, producing the concrete 137 MB figure. Zemzem confirmed that seeing the architecture-specific number — not a generic formula — was what closed the gap.

Rahel's feedback on the verbosity bias explainer: the swap test section initially used placeholder pseudocode. The writer (Zemzem) revised it to use the actual email text from `training_data/preference_pairs.jsonl` (a real chosen email and its rejected counterpart), making the test immediately runnable rather than illustrative. The grounding in the specific artifact made the method concrete.

Both explainers were signed off as revised and ready for publication.
