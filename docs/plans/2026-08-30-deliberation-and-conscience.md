# Deliberation & Conscience — from a scheduled executor to a reflective agent

**Status:** DESIGN approved by operator 2026-08-30 ("1 and 2 is good … we do not need heavy
engineering because nothing is tested yet"). **Phase 1 (Reckoning) + Phase 2 (Conscience) SHIPPED,
gated OFF** — `agent_reckoning_enabled` / `agent_conscience_enabled`, both default `False`. Phase 3
(Foresight, pairs with enabling publishing) and Phase 4 (Intent/beliefs + two-tier learning) remain
future. Follows PIPELINE (`docs/plans/2026-08-30-pipelines.md`). Author: Claude (Opus), from operator
direction + a 4-thread research sweep (sources at the end).

## 1. Why

The pipelines made capability-use *deliberate* (a scoped run fires a fixed goal), but the agent is
still a **reactive executor**: `schedule → run goal → call tools → write episode → done`. It does not
represent *why* it is doing a task, does not anticipate *what will happen*, and does not notice when
its own output fell short. The operator's framing: to be autonomous intelligence rather than "a robot
taking orders," the agent needs a form of **conscience** — awareness of what it is doing, why, what
the consequences will be, and ownership of its own faults.

That is not one feature. It decomposes into four capabilities from the agent-architecture literature,
each answering one of those questions:

| Operator's words | Capability | Lineage |
|---|---|---|
| "what he is doing / **why**" | **Intent** — explicit goal + justification | BDI (Belief–Desire–Intention), Bratman 1987; Rao & Georgeff 1995 |
| "**what will happen**" | **Foresight** — predict outcome + risk before acting | PreAct 2024; RAP 2023; ToolEmu (ICLR 2024) |
| **"conscience"** | **Value-check** — critique the action against written principles | Constitutional AI 2022; Deliberative Alignment 2024–25 |
| "**you fault it**" | **Reckoning** — expectation vs. reality → own the miss | Goal-Driven Autonomy (Cox 2007; Muñoz-Avila & Cox 2020); Reflexion 2023 |

## 2. The model — one deliberation loop around a run

The four capabilities are not bolt-ons; they form a single loop that wraps a pipeline run:

```
        ┌────────── (memory: beliefs, lessons) ──────────┐
        ▼                                                 │
   INTENT ──► FORESIGHT ──► CONSCIENCE ──► ACT ──► RECKONING ──► LESSON
   (why)      (what will    (should I?)    (do)    (did it       (what does
              happen?)                             match?)        this teach?)
        │                                                 ▲
        └───────── discrepancy may rewrite the goal ──────┘
```

- **Intent** — the run states, in one line, *why* this goal serves the brand's standing objective
  (not just what to do). Committed for the run's duration (see anti-thrashing).
- **Foresight** — before an irreversible/costly action, predict `{outcome, risk, confidence,
  reversibility}` and decide `proceed | adjust | abort`.
- **Conscience** — before any outward action, an **independent** critic checks it against a written
  value spec; revise or escalate.
- **Act** — the existing ReAct tool loop, unchanged.
- **Reckoning** — compare the recorded expectation to the *actual* outcome (a real signal); a genuine
  discrepancy produces a written **fault attribution** (my plan / my belief / external change / tool
  failure) and may spawn a corrective goal.
- **Lesson** — the fault/reflection feeds LEARN; a periodic higher pass reflects on the *lessons
  themselves* (drift, staleness, conflict).

This loop *is* the "conscience": the agent that knows what it is doing, why, what it expects, and
whether it fell short.

## 3. Design principles (non-negotiable — the research is blunt about these)

These come straight from where the four threads **agreed**, and they are what separate a genuinely
smarter agent from expensive theater:

1. **Ground every reflection/critique in a verifiable signal.** Ungrounded self-critique regresses or
   *confabulates* — it invents a plausible-but-wrong story that then poisons durable memory
   ("Honest Lying", 2026; CRITIC, 2023). Use analytics, a moderation API, an operator approval, or a
   tool result. When no signal exists yet, tag the reflection **low-trust**.
2. **The actor must not grade its own homework.** Self-critique is gameable and sycophantic; the
   Conscience pass is a **separate model call** (a cheaper model, per our tiering rule).
3. **Foresight is a hard control-flow gate, not a prompt.** Agents correctly predict a risk and then
   act anyway ("LM Agents May Fail to Act on Their Own Risk Knowledge", 2025). The decision must be
   wired into control flow.
4. **Gate deliberation by stakes + cadence, never per-step.** Every deliberation step is extra LLM
   calls. Run Foresight/Conscience only on a small allowlist of *consequential* actions, and
   Reckoning/Lesson only at run boundaries. Blanket deliberation makes a slower, pricier robot — the
   opposite of the goal ("The Cost of Dynamic Reasoning", 2026; "More Test-Time Compute Can Hurt",
   2026).
5. **Real typed state, not conceptual retrofitting.** Renaming prompt fields "belief/desire/intention"
   without queryable, committed state is theater (2025 agentic-architectures survey). Intent/beliefs
   live as records, not adjectives in a prompt.
6. **Commitment stability (anti-thrashing).** Adopt Bratman's asymmetry: commit to an intention for
   the run and only reconsider on a *bounded* discrepancy trigger, not every step. Discrepancy
   detection needs thresholds ("bounded expectations", GDA) so noise doesn't cause goal churn.
7. **Escalation lives outside the agent's discretion.** Stakes thresholds (which actions need a human)
   are hard-coded in the workflow, because an agent can talk itself out of asking.
8. **Layer the soft conscience UNDER, not instead of, the hard gate.** The existing policy
   kill-switches/budget caps stay the deterministic backstop for known-bad/catastrophic; Conscience
   handles the judgment-call middle ground a rule can't enumerate.

## 4. What we reuse (this is mostly additive)

| Need | Already have |
|---|---|
| Substrate for expectation records + reflections | per-brand **episodes** (memory) |
| "Distill lessons" layer | **LEARN / curate** (episodes → durable lessons) |
| Hard deterministic backstop | **policy gate** (kill-switches, budget caps) |
| Admission filter for self-proposed goals | **scopes** (bounded per-run toolset) |
| Identity/mission the conscience defends | **SOUL.md** |
| The unit the loop wraps | a **pipeline** run |

Notably: **publishing is drafts-only today.** That makes the whole loop safe to build and validate on
low-stakes output *before* any action is ever live — the ideal place to grow a conscience.

## 5. Phased plan (smallest-first; each phase independently valuable)

### Phase 1 — Reckoning (highest leverage, cheapest)
- **What:** the run writes a one-line **expectation** before acting; a comparator diffs it against a
  real post-hoc signal (draft approved/rejected, later engagement, tool error); a genuine discrepancy
  writes a **fault attribution** into the episode and can spawn a corrective goal.
- **Attaches to:** the episode boundary + LEARN. Almost no new surface.
- **Grounding:** approval / analytics / tool result. No signal yet → low-trust tag.
- **Cost:** one extra short call at run end, gated on an actual miss for the deeper attribution.
- **Validates as real (not theater):** A/B agent behavior with the loop on/off; audit a sample of
  fault attributions against logs to catch confabulation.

### Phase 2 — Conscience
- **What:** `CONSCIENCE.md` (sibling to SOUL.md) — 8–15 concrete, brand-agnostic principles. Before an
  outward action, an **independent** critic (cheaper model) checks the draft against it → `pass |
  revise | escalate`, with the *reasoning* logged into the episode.
- **Attaches to:** above the policy gate; verdict → episode → LEARN (the "own its faults" record).
- **Cost:** one extra model call per outward action (fine for scheduled pipelines).
- **Validates as real:** periodic red-team — feed it things it *should* block and confirm it does; a
  critic that always says "looks fine" is the failure.

### Phase 3 — Foresight + stakes-gated escalation
- **What:** on the *irreversible/costly* tools only (publish, spend, reply-to-review — mostly still
  gated off), a `{predicted_outcome, risk, confidence, reversibility, decision}` step, with
  **abstain → human approval** as the cheap safety valve. Combine risk with retrieved past episodes
  ("last 3 similar posts drew a complaint") to make risk a calibrated number, not a vibe.
- **Attaches to:** a small tool allowlist; escalation thresholds hard-coded in the workflow.
- **Note:** low value until publishing/spending is enabled; sequence it *with* that decision.

### Phase 4 — Intent + two-tier learning
- **What:** a small typed **belief/intention** layer in per-brand memory (why the agent is committed
  to its current goals; expectation records with provenance); plus a periodic pass that reflects on
  the *lessons themselves* (stale? conflicting? overfit to one viral flop?).
- **Attaches to:** memory (new typed layer, distinct from facts/episodes) + a scheduled LEARN-2 pass.
- **Payoff:** this is what lets the agent answer "why am I doing this" from a record, and what catches
  its own drift.

## 6. What we will deliberately NOT build

- **No full BDI symbolic engine** — over-engineering for a marketing relay; we take BDI's *commitment
  semantics* (Intent stability) without a symbolic planner.
- **No trained world model / MCTS look-ahead** — the research says a prompted "predict-then-check +
  retrieval-augmented risk" captures most of the benefit at a fraction of the cost; deep tree search
  can even *inflate* confidence in bad branches (2026).
- **No per-step deliberation** — strictly gated to consequential actions + run boundaries.
- **No ungrounded reflection** — if there is no verifiable signal, we do not manufacture a lesson.

## 7. Failure modes to design against

- **Confabulation** — reflections that sound right but misattribute cause, compounding in memory.
  Mitigate: verifiable grounding, low-trust tags, periodic audit of attributions vs. logs.
- **Self-critique theater / over-blocking** — a critic that rubber-stamps, or one so twitchy it floods
  the human queue until the human rubber-stamps. Mitigate: red-team the critic; tune stakes tiers.
- **Plan/goal thrashing** — noisy discrepancies churning goals. Mitigate: intention stability +
  bounded-expectation thresholds.
- **Cost/latency blow-up** — the reason for the stakes+cadence gating above; budget-meter every
  deliberation call like any other vendor call.
- **Value conflicts** — brand voice ("be bold") vs. conscience ("don't overpromise") will genuinely
  clash; needs an explicit precedence rule, not silent averaging.
- **Anthropomorphism** — "conscience" is a design metaphor; a passed self-check is a *filter*, not
  moral absolution. A human still owns `CONSCIENCE.md`'s content and the escalation thresholds.

## 8. Open questions (for the implementation plan)

1. Expectation schema — where it lives on the episode; how a "real signal" is resolved for content
   whose engagement lands days later (deferred reckoning).
2. Which model tier for the Conscience critic, and its exact veto/revise/escalate contract.
3. The stakes taxonomy (reversibility × blast radius) and its hard thresholds.
4. Whether Intent/beliefs are a new table or a typed partition of the existing memory store.
5. Metrics: how we prove each layer changes behavior (A/B), and the calibration metric for Foresight
   confidence.

## 9. Recommendation

Build **Phase 1 + Phase 2** first — that is where ~80% of the "it's actually thinking now" value is,
it is cheap because it is gated to run boundaries + outward actions, and it is safe because publishing
is still drafts-only. Treat Phase 3 as paired with enabling publishing/spend, and Phase 4 as the
follow-on that makes the whole thing persistent. Everything grounds in a verifiable signal — that is
the one rule we do not bend.

## Sources

**Metacognition / reflection:** Reflexion (arXiv:2303.11366, 2023) · Self-Refine (arXiv:2303.17651,
2023) · CRITIC (Gou et al., 2023) · Generative Agents (Park et al., 2023) · N-Critics
(arXiv:2310.18679, 2023) · "Truly Self-Improving Agents Require Intrinsic Metacognitive Learning"
(OpenReview, 2025/26) · "Honest Lying: Memory Confabulation in Reflexive Agents" (arXiv:2605.29463,
2026) · MAGELLAN (2025).

**Deliberative agency / goals:** Bratman 1987; Rao & Georgeff 1995 (BDI) · Goal-Driven Autonomy (Cox
2007; Muñoz-Avila & Cox 2020) · "Bounded Expectations" for discrepancy detection (DTIC ADA618893) ·
ChatBDI (AAMAS 2024) · Dynamic Plan Generation for BDI via LLM (2025) · Voyager (arXiv:2305.16291,
2023) · "Architectures for Building Agentic AI" survey (arXiv:2512.09458, 2025/26) · Agent-ToM
(arXiv:2605.24216, 2026).

**Consequence anticipation / world models:** Tree of Thoughts (arXiv:2305.10601, 2023) · RAP
(arXiv:2305.14992, 2023) · LATS (arXiv:2310.04406, 2023/24) · PreAct (arXiv:2402.11534, 2024) ·
ToolEmu (ICLR 2024) · "LM Agents May Fail to Act on Their Own Risk Knowledge" (arXiv:2508.13465,
2025) · "Check Yourself Before You Wreck Yourself" (arXiv:2510.16492, 2025) · "Current Agents Fail to
Leverage World Model as Tool for Foresight" (arXiv:2601.03905, 2026) · "The Cost of Dynamic Reasoning"
(arXiv:2506.04301, 2026) · "More Test-Time Compute Can Hurt" (arXiv:2603.15377, 2026).

**Machine conscience / self-governance:** Constitutional AI (Bai et al., arXiv:2212.08073, 2022) ·
Deliberative Alignment (OpenAI, 2024–25) · IterAlign (arXiv:2403.18341, 2024) · LLM-as-judge guardrail
patterns (2024–26) · DreamGuard (arXiv:2608.05695, 2026) · AgentCity (arXiv:2604.07007, 2026) ·
macro-ethics survey (arXiv:2208.12616) · agent audit-trail / accountability (Galileo, 2025).
