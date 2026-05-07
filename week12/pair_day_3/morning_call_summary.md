# Morning Call Summary — Day 3

**Date:** 2026-05-07
**Topic:** Training and Post-Training Mechanics
**Participants:** Charlie Lijalem & Rahel Samson

## Ambiguity & Sharpening

### Rahel's Question:
- **Initial:** "In my hyperparams.json I set SimPO's γ=0.3 instead of the paper default 0.5 because γ=0.5 was unstable. Why?"
- **Interrogation from Charlie:**
  - "What do you mean by unstable — loss divergence, or something else?"
  - "What is γ actually doing to each gradient update — is it a threshold, a penalty, or a scaling term?"
  - "What would you change in your training config if you understood this?"
- **Movement:** The original draft described the symptom (instability) but not the mechanism. After interrogation, Rahel named the specific observable — "unstable on weakly-discriminating boundary pairs where chosen and rejected responses are close in quality" — and the specific consequence: being unable to tune γ for a new domain or defend the choice to a client. The question moved from "why was γ=0.5 unstable" to "what does γ control in the SimPO gradient update that makes it sensitive to pair discriminability."

### Charlie's Question:
- **Initial (two-part draft):** "Why does low-rank matrix approximation work for behavioral alignment, and how does ORPO's odds ratio penalty differ from DPO and SimPO?"
- **Interrogation from Rahel:**
  - "That's two questions — which one would change something concrete in your training config?"
  - "Does understanding ORPO vs DPO vs SimPO change anything in your existing artifacts, or is it just taxonomy?"
  - "What specific artifact would you edit if you understood the LoRA rank mechanics?"
- **Movement:** The two-part question was reduced to one. The ORPO vs DPO comparison was set aside — interesting but no named artifact consequence. The LoRA part was sharpened: Charlie named `training/hyperparams.json` (lora.r=32, lora_alpha=32) as the specific artifact, and the consequence — knowing whether to tune rank up or down if the adapter fails to generalise to new failure dimensions — as the stake.

## Final Questions Finalized
Both partners confirmed that the questions are unambiguous and hit the "resolvable in one explainer" criteria.
