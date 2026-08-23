# Architecture — HR Compliance Assistant

An HR-admin assistant that, for one selected employee, answers FMLA / FLSA / benefits
questions by retrieving the governing policy + law (RAG), computing determinations with
deterministic tools, drafting a **cited** answer, flagging policy-vs-law conflicts, and
routing it through a **human approval gate** before finalizing. Educational demo over a
fictional employer (Northwind Engineering). **Not legal advice.**

## System diagram

```
              PERSONA GATE (pre-chat): HR admin picks an employee case
                          -> seed {employee_id};  thread_id = employee_id
                                        |
  load_profile -> guard_input -> route -> retrieve -> compute -> draft
   (DB read)     (scope/priv)  (domain+  (keyword ->  (calc     (grounded,
                                conf.)    LLM-rerank   tool if   cite-or-
                                          -> drop_     computed) abstain)
   declined <------+  escalate            superseded            |
   (terminal)      |  / out-of-scope      -> gate)              v
                   |                        | below bar     guard_output
   clarify --------+  (ask HR, loop)        v abstain       (cite-fidelity +
                                        (abstain)          conflict-flag +
                                                            grounding; fail
                                                            CLOSED -> escalate)
                                                                 |
                    finalize (append case log) <-- approval_gate | ok
                    (episodic; idempotent)   approve/edit  interrupt()
                                             /deny (HITL)        |
                                                            ask -> loop
```

The graph is **headless** — the CLI, the eval harness, and the Gradio UI all drive it
through one `run_turn` entrypoint (`invoke`, catch `__interrupt__`, resume with
`Command(resume=...)`), so the UI cannot break the graded core. Built on **LangGraph**
(`StateGraph`, typed `CaseState`, conditional edges, `interrupt()`, `MemorySaver`
checkpointer per `thread_id`).

## Components

| Module | Responsibility |
|---|---|
| `src/config.py` | env, Siraya model tiers, pinned constants (`TODAY`, gates), `RAG_ENABLED` |
| `src/llm.py` | Siraya (OpenAI-compatible) client; `generate` / `generate_json`; **`build_strict_schema`** (inlines `$defs`, enforces strict — required for nested structured output on flash-tier models); token-usage ledger |
| `src/schemas.py` | every inter-node payload as a typed Pydantic contract |
| `src/data_loader.py` | loads + merges the committed corpus (16 law + 20 policy chunks) and the employee / site / state-rule tables |
| `src/retrieval.py` | rerank-free pipeline: keyword prefilter → LLM reranker → `drop_superseded` → relevance gate |
| `src/jurisdiction.py` | resolvers: min-wage `max(fed,state)`, exemption threshold, overtime (federal weekly + CA daily overlay, no pyramiding) |
| `src/tools/` | read (`search_policy`, `get_employee_record` [scoped], `get_leave_history`) + compute (`check_fmla_eligibility`, `check_minimum_wage`, `compute_overtime`) + HITL-gated write (`append_case_log`, idempotent) |
| `src/guardrails.py` | scope/privacy, citation fidelity, grounding, policy-vs-law conflict |
| `src/graph.py` | the 9-node StateGraph, edges, HITL interrupt, checkpointer, `run_turn` |
| `src/prompts.py` | Role/Context/Task prompt builders |
| `src/cli.py`, `src/app_gradio.py` | thin runners over the headless graph |

## Patterns implemented (7)

| Pattern | Where |
|---|---|
| **RAG / grounding** | `retrieve` node + `retrieval.py` (cite-the-span-or-abstain) |
| **Routing** | `route` node — typed domain + confidence gate |
| **Tool use (≥2)** | 3 read + 3 compute tools; `search_policy` is where RAG and Tool-Use overlap |
| **Memory (≥2 types)** | working (checkpointed graph state) + episodic (case log) + external structured (DB) |
| **Guardrails** | `guard_input` + `guard_output`: scope/privacy, cite-or-abstain, citation fidelity, conflict flag, fail-closed |
| **Human-in-the-loop** | `approval_gate` — `interrupt()` with an approval contract; approve/edit/ask/deny |
| **Evaluation** | `eval/` — 18 cases, 4 metrics, RAG ablation, deterministic scoring |

## Design decisions (why)

1. **The model classifies; code computes.** All eligibility/wage/OT arithmetic is deterministic Python; the LLM only routes, reranks, and drafts prose. → correctness + auditability; eval task-success is objective, and the numeric determination is robust even when retrieval is weak (shown in the ablation).
2. **Rerank-free LLM-as-reranker retrieval.** Siraya exposes no embeddings and no rerank vendor on our key, so we use lab08's LLM-reranker path only — fine for a 36-chunk curated corpus. Honest limit: won't scale to large corpora.
3. **Fail-closed guardrails + citation fidelity.** A compliance answer must quote its load-bearing phrase verbatim; law spans are set from each chunk's `verbatim_anchor` (fidelity by construction), and an ungrounded "answered" determination is downgraded to a human escalation rather than shown. Every non-answerable exit routes the HR admin to a person.
4. **HR-admin operator + persona-gated threads + HITL.** Separates execution from authority (the reviewer approves before the case log is written), and enables the cross-employee **privacy guardrail** (one checkpointed thread per employee).
5. **More-protective-of-federal-vs-state resolver.** FLSA/FMLA are floors a state may exceed; the tools apply `max(federal, state)` (+ CA daily-OT overlay, + the CA salary-basis threshold for misclassification), not a naive state pick.

## Model / provider

**Siraya** model router (OpenAI-compatible, base `https://llm.siraya.ai/v1`, `openai` SDK).
Role-based tiering: routing + reranking on `gemini-2.5-flash-lite` (cheap, stable); the
grounded determination on **`gpt-5.6-luna`** (chosen over `claude-sonnet-4.5` — ~2× faster
and ~half the tokens at equal quality on our benchmark). **DeepSeek is ruled out** on our
key (json_object-only; fails the strict-json_schema backbone). Structured output uses
`response_format` json_schema throughout.

## Secret handling
`SIRAYA_API_KEY` is read from `.env` (git-ignored); `.env.example` ships fake placeholders.
No key appears in code, tests, data, or the corpus. The case log (`data/case_log.jsonl`) is a
runtime artifact and is git-ignored.

## Limitations
Exemption = salary-basis test only (no duties test); two jurisdictions (CA/TX); summarized law
corpus (verbatim anchors, not full text); computed determinations are currently gated behind
retrieval recall (eval failures #2/#3 — recommended fix: run the compute tool regardless of
retrieval for computed domains); LLM routing/rerank/draft vary run-to-run even at temp 0.
