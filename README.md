# HR Compliance Assistant

Final project — UCSD *Building Agentic AI Systems*.

An HR-admin assistant that, for one selected employee, answers **FMLA** (leave), **FLSA**
(minimum wage + overtime), and **benefits** questions. It retrieves the governing company
policy + public law (RAG), computes determinations with deterministic tools, drafts a
**cited** answer, flags policy-vs-law conflicts, and routes every determination through a
**human approval gate** before it's recorded. Built on **LangGraph**.

> Educational demo over a fictional employer (Northwind Engineering). **Not legal advice.**

## Setup
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set SIRAYA_API_KEY (never commit .env)
```

## Run
```bash
# Interactive: pick an employee case, chat, approve at the HITL gate
python -m src.cli

# One-shot (auto-approve)
python -m src.cli --auto E005 "How many more weeks of FMLA leave can this employee take?"

# Web UI (persona gate -> scoped chat -> evidence panel -> HITL controls)
python -m src.app_gradio

# Tests (LLM mocked / deterministic; no key needed)
python -m pytest -q

# Evaluation + ablation
python eval/run_eval.py                 # full pipeline
python eval/run_eval.py --no-rag        # ablation (no grounding context)
python eval/run_eval.py --runs 3        # majority vote (dampens LLM variance)
```

## LLM provider & models
- **Siraya** model router (OpenAI-compatible), base `https://llm.siraya.ai/v1`, `openai` SDK, env `SIRAYA_API_KEY`.
- Role-based tiering (override via `.env`): routing + reranking `gemini-2.5-flash-lite`; grounded determination **`gpt-5.6-luna`** (chosen over `claude-sonnet-4.5` — ~2× faster, ~half the tokens, equal quality on our benchmark).
- **Retrieval is rerank-free** — Siraya has no embeddings endpoint and no rerank vendor on our key, so retrieval is keyword prefilter → LLM-as-reranker → stale-filter → relevance gate (no FAISS/embeddings).
- **DeepSeek is not usable here** — json_object-only on our key; it fails the strict-json_schema structured-output backbone.
- Siraya returns `cost: null`; the eval uses **token usage** as the cost proxy.

## Layout
```
src/     config, llm, schemas, data_loader, retrieval, jurisdiction, tools/, guardrails, graph, prompts, cli, app_gradio
data/    committed corpus (legal/ + policy/) + employees / sites / state_rules  (case_log.jsonl is a runtime artifact, git-ignored)
tests/   39 unit tests (deterministic; LLM mocked)
eval/    test_cases.json (18), run_eval.py, eval_report.md
docs/    architecture.md
```

## Model limitations
Exemption uses the salary-basis test only (no duties test); two jurisdictions (CA/TX; others abstain);
the law corpus is summarized with verbatim anchors + real citations (not full statutory text);
LLM routing/rerank/draft vary run-to-run even at temperature 0 (see `eval/eval_report.md`).

## AI-assistance disclosure
Built with AI coding assistants (Claude Code). AI was used for scaffolding, code generation,
synthetic-data authoring, and drafting docs; all law figures were verified against primary
sources (eCFR / Cornell LII / CA leginfo / DOL / CA DIR), the design and decisions were
author-directed and reviewed, and the evaluation is deterministic and reproducible.
