# Discovery Call Transcript 04 — Specialized Capability Gap (Segment 4)

**Synthetic transcript.** Composed from the Tenacious sales team's style. Not a real call.

**Prospect:** Jordan Okafor, Head of Data, synthetic mid-market loyalty and rewards platform (~350 employees, AI-maturity score 2).
**Tenacious lead:** Yabebal Fantaye, Co-founder and Scientific Director.
**Length:** ~29 minutes.
**Outcome:** Agreed to a fixed-scope 6-week scoping phase at $[SCOPING_PHASE_COST] to produce a working prototype and an honest build/buy recommendation.

---

**Yabebal:** Jordan, thanks for making time. The email thread referenced your open MLOps-platform-engineer role and the fact that it's been open 70 days. Before I say anything about us — what's the real story on that role?

**Jordan:** We can't find the person. We've interviewed 14 candidates in two months. Two made it to final round; both took offers elsewhere. The problem isn't compensation, it's that the people who can do the job are being fought over by companies with better recognition than ours.

**Yabebal:** What's the work the role is supposed to do? Paint me a picture of what the first 90 days look like if you'd hired in January.

**Jordan:** We have a recommendation model running in production. It works. The pipeline is fragile — retraining is manual, evaluation is ad-hoc, we don't have a good way to catch data drift before customers start complaining. The MLOps hire was supposed to build the infrastructure around the model — CI/CD for the model, automated retraining, drift detection, shadow deployment for the next version we're scoping.

**Yabebal:** OK. And the second version you're scoping — is that an evolution of the current model, or a fundamentally different approach?

**Jordan:** Different approach. We're evaluating an agentic architecture for the cross-sell recommendations — an LLM-driven reasoning layer over the existing embedding model. That's where I'm most uncertain. I don't know if we should build it ourselves, buy it, or park it.

**Yabebal:** That's a good question to be honest about. Let me ask two things before I propose anything. One — is the MLOps work urgent, meaning the current pipeline is going to fail in a specific timeframe? Or is it important-but-not-burning?

**Jordan:** Important. We can keep the current thing alive for another quarter without new infrastructure. But the second version can't ship without the MLOps layer, so the cost of the delay is the cost of not shipping V2.

**Yabebal:** Two — when you think about build versus buy for the agentic layer, what's the thing you'd want to know before you could make that call?

**Jordan:** Whether the agentic architecture actually beats our current embedding model on the cross-sell metric we care about. Right now it's a theoretical bet. The engineering team says it'll work, the data-science lead is skeptical. I want a small working version we can run against our test set, and an honest assessment from someone who has built these systems in production.

**Yabebal:** That's where we'd be useful. Here's what I'd propose, roughly. Two phases. Phase one, six weeks: we build the MLOps pipeline for your current model — CI/CD, retraining, drift detection, shadow deployment. That's straightforward engineering with our ML and infrastructure team members, and it de-risks V1 immediately. Phase two, separately scoped: we build a working prototype of the agentic layer against your test set, with explicit evaluation criteria you define, and deliver an honest report on whether the architecture actually beats the baseline.

**Jordan:** I like the separation. What's the pricing shape?

**Yabebal:** Phase one is project consulting at fixed price. For six weeks with two engineers — one senior ML-infrastructure and one mid-level — figure in the $[PHASE_ONE_MIN] to $[PHASE_ONE_MAX] range depending on the specific integrations with your existing stack. I'd tighten that number after a technical walkthrough of your current pipeline. Phase two is harder to fix-price because the answer is the deliverable, not a feature build; I'd scope it as a four-to-six-week engagement with a specific evaluation protocol, probably $[PHASE_TWO_MIN] to $[PHASE_TWO_MAX].

**Jordan:** And the phase-two deliverable is what exactly?

**Yabebal:** A working prototype — runnable code, not a slide deck — plus an evaluation report with three possible conclusions: "the architecture works, here's how to productionize it"; "the architecture works in specific segments but not broadly, here's the tradeoff"; or "the architecture does not beat your baseline on the metric that matters." The third conclusion is as valuable as the first two. I'd rather tell you it doesn't work than sell you the build.

**Jordan:** I need that framing. My engineering team wants to build it because building is fun. I need an outside view.

**Yabebal:** One thing to name — we have specific experience with agentic architectures on recommendation and ranking problems. Not unlimited experience; I'd share two specific pattern examples we've worked through on the next call if useful. Also one thing we are not — we're not a recommendation-systems research lab. If the evaluation in phase two turns up a research-novel challenge, we'd flag it and suggest where to go next rather than pretending we can solve it.

**Jordan:** That's fair. What's the failure mode of this kind of engagement on your side?

**Yabebal:** Two. One — if your in-house data-science lead resists the engagement for status reasons, we can build the pipeline but we can't build trust. So I'd want to meet with her before committing. Two — the evaluation is only as good as the test set. If your test-set representativeness is weak, the phase-two conclusion will be weak. So the first thing we'd do in phase two is stress-test the test set.

**Jordan:** Both of those are real. Kira is reasonable — she'd welcome the second opinion if it's framed as partnership not replacement.

**Yabebal:** Good. Next steps. One, we set up a 45-minute technical walkthrough with Kira and one of our ML leads — I'd suggest Nesrin from our team; she did an agentic-ranking engagement for an AdTech client last year. Two, we'd send a phase-one proposal with named engineers and a tightened number within 48 hours of that walkthrough. Phase two we scope separately after phase-one completes.

**Jordan:** Let's do the walkthrough next week. I'll include Kira. Can you send the Cal link for three times Wednesday or Thursday?

**Yabebal:** Will do. One last thing — the honest version of our pricing sheet for this kind of work is at gettenacious.com, but the bands there are for talent outsourcing. Project consulting lands in the $[PROJECT_ACV_MIN] to $[PROJECT_ACV_MAX] range depending on scope. I don't want any surprises on commercial terms.

**Jordan:** Appreciated.

**Yabebal:** Talk next week.

---

## What the call demonstrates

- **Grounded on the specific capability gap.** Yabebal opens with the 70-day-open MLOps role — the public signal from the enrichment pipeline.
- **The "what would you need to know before you could make the call" question.** This is the central Segment 4 move — it surfaces what the prospect is actually uncertain about and lets Tenacious shape the engagement around that uncertainty.
- **Honest framing of the deliverable.** Phase two's "three possible conclusions, and the third is as valuable as the first two" is a specific Tenacious move. Segment 4 buyers are skeptical of vendors who have already decided the answer.
- **Specific experience claim with a named engineer.** Yabebal references Nesrin's past engagement — a specific, verifiable past project rather than "we've done lots of these."
- **Naming the failure modes on Tenacious's side.** This is rare in vendor outreach and builds trust fast with senior technical leaders.

## Agent-usable phrases from this call

- "A working prototype — runnable code, not a slide deck."
- "The third conclusion is as valuable as the first two. I'd rather tell you it doesn't work than sell you the build."
- "We're not a recommendation-systems research lab. If the evaluation turns up a research-novel challenge, we'd flag it."
- "The evaluation is only as good as the test set. If your test-set representativeness is weak, the phase-two conclusion will be weak."

## Agent-NOT-usable phrases

- "We can definitely make the agentic layer work" — false certainty before evaluation.
- "Our ML team is world-class" — marketing language.
- "Guaranteed lift on your cross-sell metric" — unsubstantiated.
