# Question — Rahel Samson, Day 3

**Topic:** Training and post-training mechanics
**Partner:** Charlie Lijalem

---

## Final Sharpened Question

In `training/hyperparams.json`, I set SimPO's γ=0.3 instead of the paper default 0.5 because γ=0.5 was unstable on my weakly-discriminating preference pairs — pairs where chosen and rejected responses are close in quality. The calibration sweep confirms the choice but I cannot explain the mechanism: what does γ actually control in the SimPO gradient update, and why does a higher γ cause instability specifically when chosen and rejected responses are close in quality? Without understanding this I cannot defend the γ choice to a client or know which direction to tune it when adapting to a new domain.

**Artifact:** `training/hyperparams.json` (γ_rationale and calibration_sweep_results fields) and `model_card.md` Limitations — both document the observation, neither explains the mechanism.
