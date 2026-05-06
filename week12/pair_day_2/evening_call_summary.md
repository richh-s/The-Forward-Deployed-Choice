# Evening Call Summary — Day 2

**Date:** 2026-05-06
**Topic:** Agent and Tool-Use Internals
**Participants:** Lidya Dagnew & Rahel Samson

## Feedback & Revisions

### Explainer for Rahel (written by Lidya):
- **Lidya's delivery:** Rahel confirmed that the explanation of **Logit Masking** was the "missing link" for her. She now understands that grammar-based decoding mechanically prevents the model from generating invalid syntax, which shifts the blame to the scaffolding if the JSON is valid but the logic is wrong.
- **Revision:** No major revisions requested. The explanation of "Control Tokens" helped anchor the concept to the Toolformer paper she's reading.

### Explainer from Rahel (written by Rahel, for Lidya):
- **Rahel's delivery:** Her explainer showed that function-calling is essentially a fine-tuned token sequence in a hidden namespace.
- **Feedback:** Lidya requested clarification on the `tool_choice` parameter, which Rahel added. Lidya now understands that "auto" is a probabilistic decision while forced tool-choice is a hard constraint.

## Sign-off
Both partners are satisfied that the day's gaps are closed.
