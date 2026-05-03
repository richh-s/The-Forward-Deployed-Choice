---
title: Gebru et al. — Datasheets for Datasets
paper: Gebru et al. "Datasheets for Datasets" (2018, CACM 2021)
---

## Summary

Gebru et al. propose a standardized documentation format — "datasheets" — for machine learning datasets, modeled after electronics component datasheets. The framework covers seven sections: Motivation, Composition, Collection Process, Preprocessing/Cleaning, Uses, Distribution, and Maintenance. The goal is to improve transparency, reproducibility, and responsible use of datasets.

## Key Claims

1. Undocumented datasets are a primary source of harm in ML deployments; documentation forces dataset creators to surface assumptions and limitations.
2. Datasheets should be written at time of dataset creation (not post-hoc) and updated with every major revision.
3. Full public documentation should accompany every dataset release to enable third-party auditing.

## Disagreement

Gebru et al. assume that all documentation should be fully public at time of release. Their framework has no mechanism for partial disclosure — the assumption is that transparency is always better than secrecy.

**Why we disagree for competitive evaluation benchmarks:** Tenacious-Bench v0.1 seals the held_out partition (AES-256 at rest; released only alongside leaderboard publication). If the held_out tasks were publicly documented at time of release — even without the answers — competitors could construct near-duplicate tasks, study the distribution, and overfit to the benchmark before evaluation. The Gebru framework treats datasets as artifacts for model *training*; it does not account for evaluation benchmarks where the test set must remain adversarially sealed. We extend their framework with an **embargo protocol** for the held_out section, releasing a partial datasheet (covering only train and dev partitions) at publication and the full datasheet at leaderboard close. We believe this is a necessary extension, not a violation of their spirit — the goal is still transparency, but staged.

**Evidence from this project:** The contamination_check.json results demonstrate exactly why the embargo matters. The n-gram overlap check found that 4 of the initial 247 tasks had >8-gram overlap with training partition tasks — these were excluded from the held_out before sealing. If the held_out distribution had been published in full at time of dataset creation (as Gebru et al. recommend), the 4 removed tasks would have been visible, and an adversary could infer that the remaining held_out tasks are *systematically different* from those near-duplicates — leaking structural information about the difficulty profile. The Chen et al. (2024) contamination survey we read concurrently covers exactly this vector ("indirect contamination via distribution leakage") and is not addressed in the Gebru framework at all, confirming that the Gebru protocol was designed before dynamic adversarial benchmark construction was a practical concern.

## Application to Tenacious-Bench

- We follow the full seven-section structure in `datasheet.md`.
- Pushkarna et al.'s "Data Cards" layered documentation model supplements Gebru by adding per-field lineage and per-partition context (applied to train/dev sections of our datasheet).
- Motivation section documents the τ²-Bench retail gap and the four structural failure modes that justify building a new benchmark.
- Distribution section explicitly discloses the embargo protocol and the held_out release schedule.

**Concrete design decision shaped by this paper:** Gebru et al.'s requirement to document the *preprocessing and cleaning* steps at dataset creation time (not retrospectively) directly drove the decision to commit contamination_check.json and inter_rater_agreement.md alongside the dataset rather than generating them post-hoc. During Day 3 dataset authoring, there was a temptation to run the contamination check after the held_out was sealed (simpler pipeline). Gebru et al.'s principle — documentation must accompany the dataset at creation time to be trustworthy — overrode this: the contamination check is now part of the generation pipeline in generation_scripts/contamination_check.py, runs automatically before any task enters the held_out, and its output is committed in the same commit as the dataset. A reviewer can verify that contamination_check.json timestamps predate the held_out sealing date, meeting the "created at time of release" requirement even though the full held_out datasheet is embargoed.
