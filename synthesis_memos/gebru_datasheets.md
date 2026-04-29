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

## Application to Tenacious-Bench

- We follow the full seven-section structure in `datasheet.md`.
- Pushkarna et al.'s "Data Cards" layered documentation model supplements Gebru by adding per-field lineage and per-partition context (applied to train/dev sections of our datasheet).
- Motivation section documents the τ²-Bench retail gap and the four structural failure modes that justify building a new benchmark.
- Distribution section explicitly discloses the embargo protocol and the held_out release schedule.
