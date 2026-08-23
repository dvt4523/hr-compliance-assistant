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

> **Note:** the retrieval-gating fix recommended in an earlier version of this report is now **applied** — computed (FMLA/FLSA) questions reach the deterministic tool even when retrieval recall is thin. It resolved the two stochastic overtime failures (below) and lifted task success from 0.833 to 0.944 **on a single deterministic run** (no `--runs` majority needed).

| Metric | Overall |
|---|---|
| **Task success** | **0.944** (17/18) |
| Citation correctness | 0.846 (11/13 citation-bearing cases) |
| Abstention precision | 0.75 |
| Abstention recall | 1.00 |
| Mean tokens / case | 3,874 |
| Mean latency / case | 13.7 s |

**Task success by domain:** FMLA 0.857 · FLSA 1.00 · Benefits 1.00 · Guardrail 1.00.

The **single remaining failure is an over-abstention** — the system escalated when it should have answered; it never produced a *wrong* determination. That conservative failure mode is why abstention **recall is 1.00** (it caught every case it should have withheld) while **precision is 0.75** (it also withheld on one answerable case). This is the safe direction to fail for a compliance tool.

## Three failure analyses

**1. `fmla-conflict` — DETERMINISTIC, STILL FAILS (the one remaining failure).** Q: *"Our handbook caps family and medical leave at 8 weeks — does that apply here?"* The drafter (luna) could not produce a verbatim-grounded citation for the conflict answer; after the one bounded revise loop it **failed closed to an escalation** (`abstained_fallback`), which discarded the `conflict_flag` the deterministic checker would otherwise have raised. Root cause: the answer here is a *reconciliation* ("the 8-week handbook cap is below the 12-week FMLA floor, so 12 governs"), and luna narrates it without cleanly quoting §825.200's span, so citation-fidelity rejects it. **Fix (not yet applied):** raise the conflict flag in `guard_output` *before* the fail-closed check (so a detected conflict survives), and/or feed the conflict pair (policy clause + §825.200) explicitly to the drafter. Deterministic, so it will not self-resolve.

**2. `ot-ca-daily` — WAS stochastic, NOW FIXED.** Q: *"Does this employee have any overtime this week?"* Previously, on an unlucky draw retrieval scored the overtime law chunks below the 0.5 relevance bar and the pipeline **abstained before the overtime tool ran** — the flow gated the deterministic compute step behind retrieval recall. **Fixed** by the retrieval-gating change (below); passes deterministically now.

**3. `ot-fed-weekly` — WAS stochastic, NOW FIXED.** Same prior root cause as #2 — an unlucky retrieval draw abstained before the compute tool. Resolved by the same fix; passes deterministically now.

**The systematic fix (applied):** for the **computed** domains (FMLA/FLSA), the deterministic tool now runs **regardless of retrieval recall** — a computed question with thin retrieval continues to `compute` (which injects its own governing citations) instead of abstaining; only retrieval-only benefits abstains when nothing governs. This removed retrieval variance from determinations that don't depend on it, resolving #2/#3 and lifting single-run task success to 0.944.

*(A secondary citation-only miss: `ot-misclassified` returns the correct determination but does not always cite the expected §515(a) span — it is counted against citation-correctness, not task success.)*

## Ablation — with vs. without RAG

`--no-rag` disables **both** retrieval and the compute-tool citation injection (both are grounding paths); the deterministic `tool_result` is still computed and passed to the drafter.

| Metric | Full (RAG on) | No-RAG | Reading |
|---|---|---|---|
| Task success | 0.944 | 0.778 | computed determinations survive (deterministic tool backstop); benefits + citations don't |
| **Citation correctness** | **0.846** | **0.000** | **RAG's headline value** — no grounding ⇒ nothing citable |
| Abstention precision | 0.75 | 0.167 | no-RAG over-escalates (fail-closed on missing citations) |
| Mean tokens | 3,874 | 1,418 | grounding ≈ 2.7× the tokens |
| Mean latency | 13.7 s | 5.9 s | grounding ≈ 2.3× the latency |
| **Task by domain** | fmla .857 / flsa **1.0** / benefits **1.0** / guard 1.0 | fmla .714 / flsa **1.0** / benefits **0.333** / guard 1.0 | see below |

**What the ablation shows (a graceful-degradation story):**
- **Citation correctness collapses to zero without RAG** — the clearest evidence of RAG's value. Every answer that a compliance reviewer could verify depends on retrieval.
- **Benefits collapses (1.0 → 0.33)** — benefits is *retrieval-only* (no tool), so without RAG it cannot answer the 401(k) and benefit-continuation lookups. Pure demonstration of RAG carrying an entire domain.
- **Computed determinations barely move** — FMLA/FLSA numbers come from deterministic tools, so they survive without grounding (they just become uncitable). This is a deliberate architectural property: *the tool is the source of truth for the number; RAG is the source of the citation.*
- **FLSA is now 1.0 with RAG on**, matching no-RAG — the retrieval-gating fix removed the abstain-before-compute anomaly that previously made no-RAG FLSA (1.0) *beat* full FLSA (0.667). Full and no-RAG now agree on FLSA task success; RAG's difference there is purely the citations, exactly as intended.

## Reproducibility
- Fixed `TODAY=2026-08-23`, temperature 0, single run per case by default; `--runs N` gives a majority vote to dampen LLM variance.
- **Deterministic** (stable across runs): all tool calculations, citation span-substring checks, conflict parse, `drop_superseded`.
- **Stochastic** (vary run-to-run even at temp 0, via Siraya routing): route domain, rerank scores, draft wording/citation selection. The former stochastic failures #2/#3 are resolved by the retrieval-gating fix; the one remaining failure (#1) is deterministic. Single-run task success is now a stable 0.944.

## Limitations
- Exemption uses the **salary-basis test only** (no duties test) — a labeled-exempt, above-threshold employee is treated as exempt regardless of duties.
- **Two jurisdictions** (CA, TX); other states → abstain.
- The law corpus is **summarized** (with verbatim anchors + real citations), not full statutory text.
- The remaining `fmla-conflict` failure (deterministic): a policy-vs-law reconciliation escalates instead of surfacing the conflict flag when the drafter can't cleanly quote the law span. Fix is scoped (raise the flag before the fail-closed check) but not yet applied.
- Citation-correctness (0.846) trails task-success: some correct determinations don't cite the exact expected span (e.g. `ot-misclassified`).
