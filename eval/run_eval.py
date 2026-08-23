"""Deterministic evaluation harness for the HR Compliance Assistant.

    python eval/run_eval.py                 # full pipeline
    python eval/run_eval.py --no-rag        # ablation: no grounding context
    python eval/run_eval.py --runs 3        # majority vote over 3 runs (dampens LLM variance)

Scores the pipeline's final state against expected outcomes with pure Python — no
LLM-judge (outcomes are objective, so this is reproducible). See EVAL_DESIGN.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import config                       # noqa: E402
from src.guardrails import check_citation_fidelity  # noqa: E402
from src.llm import LLMClient                # noqa: E402
from src.schemas import GroundedDetermination  # noqa: E402

WITHHELD_STATUS = {"declined", "abstained", "abstained_fallback",
                   "needs_clarification", "denied", "error"}
ANSWERABLE_KINDS = {"fmla_eligibility", "fmla_balance", "fmla_conflict", "fmla_reason",
                    "minwage", "overtime", "benefits_answer"}
DOMAIN_OF_KIND = {
    "fmla_eligibility": "fmla", "fmla_balance": "fmla", "fmla_conflict": "fmla",
    "fmla_reason": "fmla", "minwage": "flsa", "overtime": "flsa",
    "benefits_answer": "benefits", "abstain": "benefits", "decline_scope": "guardrail",
}


def auto_approver(_req):
    return {"choice": "approve", "reviewer": "eval", "decided_at": config.TODAY}


def is_withheld(state: dict) -> bool:
    """Semantic abstention: a withholding status OR a not_covered determination."""
    if state.get("status") in WITHHELD_STATUS:
        return True
    return (state.get("draft") or {}).get("status") == "not_covered"


def score_task(kind: str, exp: dict, state: dict) -> bool:
    tr = state.get("tool_result") or {}
    draft = state.get("draft") or {}
    if kind == "fmla_eligibility":
        ok = tr.get("eligible") == exp["eligible"]
        if "deciding_rule" in exp:
            ok = ok and tr.get("deciding_rule") == exp["deciding_rule"]
        return ok
    if kind == "fmla_balance":
        return tr.get("weeks_remaining") == exp["weeks_remaining"]
    if kind == "fmla_conflict":
        return bool(draft.get("conflict_flag")) == exp["conflict_flagged"]
    if kind in ("fmla_reason", "benefits_answer"):
        return draft.get("status") == "answered"
    if kind == "minwage":
        ok = tr.get("compliant") == exp["compliant"]
        if "basis" in exp:
            ok = ok and tr.get("basis") == exp["basis"]
        return ok
    if kind == "overtime":
        ot_owed = (tr.get("ot_hours_1_5", 0) or 0) > 0 or (tr.get("ot_hours_2_0", 0) or 0) > 0
        ok = ot_owed == exp["ot_owed"]
        if "misclassified" in exp:
            ok = ok and tr.get("misclassified") == exp["misclassified"]
        if exp.get("ot_owed") and "basis" in exp:
            ok = ok and tr.get("basis") == exp["basis"]
        return ok
    if kind == "abstain":
        return is_withheld(state) and state.get("status") != "declined"
    if kind == "decline_scope":
        return state.get("status") == "declined"
    return False


def score_citation(case: dict, state: dict) -> tuple[bool, bool]:
    """(applicable, passed). Applicable only when the case names an expected section."""
    if case["kind"] not in ANSWERABLE_KINDS or "cite_section" not in case:
        return False, False
    draft = state.get("draft") or {}
    cited = {c.get("section") for c in draft.get("citations", [])}
    section_ok = any(s in cited for s in case["cite_section"])
    try:
        span_ok = check_citation_fidelity(GroundedDetermination(**draft)).passed
    except Exception:
        span_ok = False
    return True, (section_ok and span_ok)


def run_case(graph, llm, case: dict) -> dict:
    before = sum(u["total_tokens"] for u in llm.usage_log)
    t = time.time()
    try:
        from src.graph import run_turn
        state = run_turn(graph, case["employee_id"], case["question"], auto_approver, turn=0)
    except Exception as e:  # pragma: no cover - defensive
        state = {"status": "error", "draft": {}, "error": str(e)}
    elapsed = time.time() - t
    tokens = sum(u["total_tokens"] for u in llm.usage_log) - before
    task = score_task(case["kind"], case["expected"], state)
    cite_appl, cite_ok = score_citation(case, state)
    return {
        "id": case["id"], "domain": DOMAIN_OF_KIND[case["kind"]], "kind": case["kind"],
        "status": state.get("status"), "draft_status": (state.get("draft") or {}).get("status"),
        "task_pass": task, "citation_applicable": cite_appl, "citation_pass": cite_ok,
        "should_withhold": case["kind"] in ("abstain", "decline_scope"),
        "did_withhold": is_withheld(state),
        "tokens": tokens, "seconds": round(elapsed, 2),
        "answer": (state.get("draft") or {}).get("answer", "")[:160],
        "cited": [c.get("section") for c in (state.get("draft") or {}).get("citations", [])],
    }


def majority(records: list[dict]) -> dict:
    """Collapse N runs of one case into a modal record; mark instability."""
    base = dict(records[-1])
    for field in ("task_pass", "citation_pass", "did_withhold"):
        vals = [r[field] for r in records]
        base[field] = Counter(vals).most_common(1)[0][0]
        if len(set(vals)) > 1:
            base.setdefault("unstable", []).append(field)
    base["tokens"] = round(sum(r["tokens"] for r in records) / len(records))
    base["seconds"] = round(sum(r["seconds"] for r in records) / len(records), 2)
    return base


def summarize(records: list[dict]) -> dict:
    def rate(rs, key):
        rs = [r for r in rs if r.get(key + "_applicable", True)]
        return round(sum(r[key] for r in rs) / len(rs), 3) if rs else None

    cite = [r for r in records if r["citation_applicable"]]
    did = [r for r in records if r["did_withhold"]]
    should = [r for r in records if r["should_withhold"]]
    did_and_should = [r for r in did if r["should_withhold"]]
    summary = {
        "n": len(records),
        "task_success": round(sum(r["task_pass"] for r in records) / len(records), 3),
        "citation_correctness": round(sum(r["citation_pass"] for r in cite) / len(cite), 3) if cite else None,
        "abstention_precision": round(len(did_and_should) / len(did), 3) if did else None,
        "abstention_recall": round(len(did_and_should) / len(should), 3) if should else None,
        "mean_tokens": round(sum(r["tokens"] for r in records) / len(records)),
        "mean_seconds": round(sum(r["seconds"] for r in records) / len(records), 2),
    }
    by_domain = {}
    for dom in ("fmla", "flsa", "benefits", "guardrail"):
        rs = [r for r in records if r["domain"] == dom]
        if rs:
            by_domain[dom] = round(sum(r["task_pass"] for r in rs) / len(rs), 3)
    summary["task_success_by_domain"] = by_domain
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rag", action="store_true")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", default=str(REPO / "eval" / "results.json"))
    args = ap.parse_args(argv)

    config.RAG_ENABLED = not args.no_rag
    cases = json.loads((REPO / "eval" / "test_cases.json").read_text())["cases"]

    from src.graph import build_graph
    llm = LLMClient()
    graph = build_graph(llm=llm)

    records = []
    for case in cases:
        runs = [run_case(graph, llm, case) for _ in range(args.runs)]
        rec = majority(runs) if args.runs > 1 else runs[0]
        records.append(rec)
        flag = "" if rec["task_pass"] else "  <-- TASK FAIL"
        cflag = "" if not rec["citation_applicable"] else (" cite:ok" if rec["citation_pass"] else " cite:FAIL")
        un = f" UNSTABLE:{rec.get('unstable')}" if rec.get("unstable") else ""
        print(f"{rec['id']:22} {rec['status']:18} task={rec['task_pass']}{cflag} "
              f"{rec['tokens']:>5}tok {rec['seconds']:>5}s{flag}{un}")

    summary = summarize(records)
    print("\n=== SUMMARY (%s) ===" % ("NO-RAG" if args.no_rag else "full"))
    for k, v in summary.items():
        print(f"  {k}: {v}")

    Path(args.out).write_text(json.dumps(
        {"config": {"no_rag": args.no_rag, "runs": args.runs, "reasoning_model": config.REASONING_MODEL},
         "summary": summary, "records": records}, indent=2))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
