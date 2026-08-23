"""Headless CLI runner for the HR compliance assistant.

    python -m src.cli                      # interactive: pick a case, chat, approve at the gate
    python -m src.cli --auto E002 "Is this employee eligible for FMLA leave?"

The graph is driven exactly as the eval harness and Gradio UI drive it.
"""
from __future__ import annotations

import argparse
import sys

from . import config, data_loader
from .graph import build_graph, run_turn


def render(result: dict) -> None:
    det = result.get("draft", {})
    print(f"\n[{result.get('status','?')}] {det.get('answer','')}")
    for c in det.get("citations", []):
        url = f"  ({c['url']})" if c.get("url") else ""
        print(f'   [{c["doc_type"].upper()}] {c["citation"]} rev {c["revision"]} — "{c["span"]}"{url}')
    cf = det.get("conflict_flag")
    if cf:
        print(f'   [CONFLICT] policy {cf["policy_value"]} < law {cf["law_floor"]} — {cf["resolution"]}')
    if det.get("basis"):
        print(f"   basis: {det['basis']}")
    if det.get("disclaimer"):
        print(f"   — {det['disclaimer']}")


def auto_approver(req: dict) -> dict:
    return {"choice": "approve", "reviewer": "auto", "decided_at": config.TODAY}


def interactive_approver(req: dict) -> dict:
    print("\n--- APPROVAL REQUIRED (HR admin) ---")
    print("action     :", req["action"])
    print("reason     :", req["reason_for_gate"])
    print("effect     :", req["effect"])
    print("reversible :", req["reversibility"])
    choice = (input("approve / edit / deny > ").strip().lower() or "approve")
    decision = {"choice": choice, "reviewer": "hr-admin", "decided_at": config.TODAY}
    if choice == "edit":
        decision["edited_answer"] = input("edited answer > ").strip()
    return decision


def _print_profile(eid: str) -> None:
    emp = data_loader.load_employees()[eid]
    site = data_loader.site_for_employee(emp)
    print(f"\nCase: {eid} — {emp['name']}, {emp['job_title']} @ {site['name']} ({site['state']})")
    print(f"  tenure {emp['tenure_months']}mo · {emp['hours_last_12mo']}h/12mo · "
          f"{emp['classification']} · leave taken {emp['leave_taken_weeks_ytd']}wk")


def main(argv=None):
    ap = argparse.ArgumentParser(description="HR compliance assistant (headless CLI).")
    ap.add_argument("--auto", action="store_true", help="auto-approve at the HITL gate")
    ap.add_argument("employee_id", nargs="?", help="e.g. E002")
    ap.add_argument("question", nargs="?", help="one question (else interactive)")
    args = ap.parse_args(argv)

    graph = build_graph()
    approver = auto_approver if args.auto else interactive_approver

    if args.employee_id and args.question:
        _print_profile(args.employee_id)
        print(f"Q: {args.question}")
        render(run_turn(graph, args.employee_id, args.question, approver, turn=0))
        return

    # interactive
    ids = list(data_loader.load_employees())
    print("Employees:", ", ".join(ids))
    eid = (input("Pick a case (employee id) > ").strip() or ids[0]).upper()
    _print_profile(eid)
    turn = 0
    while True:
        try:
            q = input("\nQ (blank to quit) > ").strip()
        except EOFError:
            break
        if not q:
            break
        render(run_turn(graph, eid, q, approver, turn=turn))
        turn += 1


if __name__ == "__main__":
    sys.exit(main())
