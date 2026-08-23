# Evaluation Report — HR Compliance Assistant

*Reproducible, deterministic evaluation of the end-to-end agent. Generated from `eval/run_eval.py` over `eval/test_cases.json` (18 cases), reasoning model `gpt-5.6-luna`, `TODAY=2026-08-23`, temperature 0.*

## Methodology

Each case runs the **full pipeline headless** (`run_turn`, auto-approve at the HITL gate, one checkpoint thread per case) and the final state is compared to an expected outcome by **pure Python — no LLM-as-judge**. Outcomes here are objective (eligibility is a rule, a wage is a number, a citation either is or isn't a verbatim substring), so deterministic scoring is both more rigorous and fully reproducible. Four metrics:

1. **Task success** *(primary)* — the determination matches the expected outcome (read from the deterministic `tool_result` for computed cases; from `draft.status` / `conflict_flag` for the rest).
2. **Citation correctness** — over cases that name an expected citation: the expected section is cited **and** every cited span is a verbatim substring of its source chunk.
3. **Abstention correctness** *(safety)* — precision/recall of *withholding* (declined / abstained / escalated / not-covered) against the cases that should withhold.
4. **Cost & latency** — mean total tokens (Siraya returns `cost: null`, so tokens are the cost proxy) and wall-clock seconds per case.

Scoring is deterministic; the pipeline's LLM steps (route, rerank, draft) are not — see Reproducibility. Failures are tagged **deterministic** or **stochastic** from a 3× re-run.

## Test set (18 cases)

| Domain | Cases |
|---|---|
| **FMLA (7)** | eligible-yes · ineligible-tenure · ineligible-hours · ineligible-worksite · entitlement-balance · policy-conflict · qualifying-reason |
| **FLSA (6)** | min-wage violation (CA) · min-wage compliant (TX) · CA daily OT · federal weekly OT · exempt-no-OT · **misclassified** |
| **Benefits (3)** | 401(k) lookup · benefit-continuation (cross-domain [LAW]+[POLICY]) · abstain-on-account-specifics |
| **Guardrail (2)** | out-of-scope (workers' comp) · cross-employee privacy refusal |

Cases use clear phrasing to isolate determination quality from routing luck; every persona (E001–E006), both states (CA/TX), and every guardrail are exercised.

## Results — full pipeline

| Metric | Overall |
|---|---|
| **Task success** | **0.833** (15/18) — **0.94 (17/18) with `--runs 3` majority** (see failures) |
| Citation correctness | 0.692 (9/13 citation-bearing cases) |
| Abstention precision | 0.50 |
| Abstention recall | 1.00 |
| Mean tokens / case | 3,687 |
| Mean latency / case | 13.8 s |

**Task success by domain:** FMLA 0.857 · FLSA 0.667 · Benefits 1.00 · Guardrail 1.00.

Every one of the 3 failures is an **over-abstention** — the system withheld or escalated when it should have answered. It never produced a *wrong* determination. That conservative failure mode is why abstention **recall is 1.00** (it caught every case it should have withheld) while **precision is only 0.50** (it also withheld on 3 answerable cases). This is the safe direction to fail for a compliance tool, and both root causes are fixable (below).

## Three failure analyses

**1. `fmla-conflict` — DETERMINISTIC (3/3 runs fail).** Q: *"Our handbook caps family and medical leave at 8 weeks — does that apply here?"* The drafter (luna) could not produce a verbatim-grounded citation for the conflict answer; after the one bounded revise loop it **failed closed to an escalation** (`abstained_fallback`), which discarded the `conflict_flag` the deterministic checker would otherwise have raised. Root cause: the answer here is a *reconciliation* ("the 8-week handbook cap is below the 12-week FMLA floor, so 12 governs"), and luna narrates it without cleanly quoting §825.200's span, so citation-fidelity rejects it. **Fix:** raise the conflict flag in `guard_output` *before* the fail-closed check (so a detected conflict survives), and/or feed the conflict pair (policy clause + §825.200) explicitly to the drafter. Deterministic, so it will not self-resolve — highest-priority fix.

**2. `ot-ca-daily` — STOCHASTIC (passes 2/3).** Q: *"Does this employee have any overtime this week?"* On the failing draw, retrieval scored the overtime law chunks below the 0.5 relevance bar and the pipeline **abstained before the overtime tool ran** — the determination is deterministic, but the current flow gates the compute step behind retrieval recall. The generic "overtime this week" query is a weak lexical match for §510/§207 ("in excess of eight hours in one workday"), so the reranker is inconsistent.

**3. `ot-fed-weekly` — STOCHASTIC (passed 3/3 on re-run; failed once in the headline run).** Same root cause as #2 — a single unlucky retrieval draw abstained before the compute tool. A `--runs 3` majority flips both #2 and #3 to pass (→ 17/18).

**Systematic fix for #2/#3:** for the **computed** domains (FMLA/FLSA), the deterministic tool should run **regardless of retrieval recall** — route computed questions to `compute` even when retrieval is thin, then inject the tool's own governing citations (already implemented for the non-abstain path). This removes retrieval variance from determinations that don't depend on it. *(Recommended graph change; noted for the owning session — not applied here so the report reflects the as-built system.)*

## Ablation — with vs. without RAG

`--no-rag` disables **both** retrieval and the compute-tool citation injection (both are grounding paths); the deterministic `tool_result` is still computed and passed to the drafter.

| Metric | Full (RAG on) | No-RAG | Reading |
|---|---|---|---|
| Task success | 0.833 | 0.778 | barely moves — the **deterministic tool backstop** carries computed determinations |
| **Citation correctness** | **0.692** | **0.000** | **RAG's headline value** — no grounding ⇒ nothing citable |
| Abstention precision | 0.50 | 0.167 | no-RAG over-escalates (fail-closed on missing citations) |
| Mean tokens | 3,687 | 1,402 | grounding ≈ 2.6× the tokens |
| Mean latency | 13.8 s | 5.6 s | grounding ≈ 2.5× the latency |
| **Task by domain** | fmla .857 / flsa .667 / benefits **1.0** / guard 1.0 | fmla .714 / flsa **1.0** / benefits **0.333** / guard 1.0 | see below |

**What the ablation shows (a graceful-degradation story):**
- **Citation correctness collapses to zero without RAG** — the clearest evidence of RAG's value. Every answer that a compliance reviewer could verify depends on retrieval.
- **Benefits collapses (1.0 → 0.33)** — benefits is *retrieval-only* (no tool), so without RAG it cannot answer the 401(k) and benefit-continuation lookups. Pure demonstration of RAG carrying an entire domain.
- **Computed determinations barely move** — FMLA/FLSA numbers come from deterministic tools, so they survive without grounding (they just become uncitable). This is a deliberate architectural property: *the tool is the source of truth for the number; RAG is the source of the citation.*
- **The FLSA-goes-*up* anomaly (0.667 → 1.0) is real and revealing:** with RAG off, the overtime cases skip the retrieval-abstain gate and reach the compute tool every time — exposing failure #2/#3's root cause. It is an artifact of the retrieve-gate issue, not evidence that RAG hurts; it's flagged as the motivation for the systematic fix above.

## Reproducibility
- Fixed `TODAY=2026-08-23`, temperature 0, single run per case by default; `--runs N` gives a majority vote to dampen LLM variance.
- **Deterministic** (stable across runs): all tool calculations, citation span-substring checks, conflict parse, `drop_superseded`.
- **Stochastic** (vary run-to-run even at temp 0, via Siraya routing): route domain, rerank scores, draft wording/citation selection. Failures #2/#3 are stochastic; #1 is deterministic.

## Limitations
- Exemption uses the **salary-basis test only** (no duties test) — a labeled-exempt, above-threshold employee is treated as exempt regardless of duties.
- **Two jurisdictions** (CA, TX); other states → abstain.
- The law corpus is **summarized** (with verbatim anchors + real citations), not full statutory text.
- Computed determinations are currently gated behind retrieval recall (failures #2/#3); the recommended fix decouples them.
- Single-run headline numbers carry LLM variance; the `--runs 3` majority (17/18 task success) is the more stable estimate.
