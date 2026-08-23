"""Gradio Blocks UI — a THIN layer over the headless LangGraph pipeline.

The graph is driven exactly as the CLI/eval drive it (same build_graph + invoke +
Command(resume=...)), only split across two handlers because a web request/response
UI cannot block inside run_turn's HITL callback:

    Ask  -> graph.invoke(state)         -> if it interrupts at approval_gate,
                                            show the drafted determination + approve/edit/deny
    Decide -> graph.invoke(Command(resume=decision))  -> finalize

This module imports (never modifies) src.graph / src.config / src.data_loader.
Graph + LLM client are built lazily so `import src.app_gradio` needs no API key.
"""
from __future__ import annotations

import time
import uuid

import gradio as gr
from langgraph.types import Command

from . import config, data_loader
from .graph import build_graph
from .llm import LLMClient

_GRAPH = None
_LLM = None


def _ensure():
    """Build the graph + a shared LLM client once (needs the API key at first use)."""
    global _GRAPH, _LLM
    if _GRAPH is None:
        _LLM = LLMClient()
        _GRAPH = build_graph(_LLM)   # pass our client so we can read token usage
    return _GRAPH, _LLM


# --- rendering helpers ------------------------------------------------------
def _employee_choices():
    emps = data_loader.load_employees()
    return [(f"{e['employee_id']} — {e['name']}, {e['job_title']}", eid)
            for eid, e in emps.items()]


def _profile_md(emp_id: str) -> str:
    emp = data_loader.load_employees()[emp_id]
    site = data_loader.site_for_employee(emp)
    pay = (f"${emp['pay_rate_hourly']}/hr" if emp.get("pay_rate_hourly")
           else f"${emp.get('annual_salary','?'):,}/yr")
    return (
        f"### Case open — {emp['name']}  \n"
        f"**{emp['job_title']}** · {site['name']} ({site['state']}) · "
        f"headcount within 75mi: {site['headcount_within_75mi']}  \n"
        f"tenure **{emp['tenure_months']}mo** · **{emp['hours_last_12mo']}h**/12mo · "
        f"**{emp['classification']}** {pay} · FMLA leave taken **{emp['leave_taken_weeks_ytd']}wk**  \n"
        f"_Leave request on file: {emp.get('leave_reason','—')}_"
    )


_STATUS_BADGE = {
    "finalized": "✅ Finalized", "denied": "🚫 Denied",
    "declined": "⛔ Declined", "abstained": "🤷 Not covered",
    "abstained_fallback": "🤷 Escalated", "needs_clarification": "❓ Needs clarification",
    "error": "⚠️ Error", "ok": "…",
}


def _answer_md(result: dict, pending: bool = False) -> str:
    det = result.get("draft", {}) or {}
    badge = "⏸️ Awaiting your approval" if pending else _STATUS_BADGE.get(
        result.get("status", ""), result.get("status", ""))
    return f"**{badge}**\n\n{det.get('answer','')}"


def _side_md(result: dict, tokens: int, seconds: float) -> str:
    det = result.get("draft", {}) or {}
    route = result.get("route", {}) or {}
    lines = ["#### Evidence"]
    if route.get("domain"):
        lines.append(f"**Domain:** `{route['domain']}`  ·  **confidence:** {route.get('confidence','?')}")
    if det.get("basis"):
        lines.append(f"**Jurisdiction basis:** {det['basis']}")
    cites = det.get("citations") or []
    if cites:
        lines.append("\n**Citations**")
        for c in cites:
            tag = c.get("doc_type", "").upper()
            head = f"[{c.get('citation','')}]({c['url']})" if c.get("url") else c.get("citation", "")
            rev = f" rev {c['revision']}" if c.get("revision") else ""
            lines.append(f"- **[{tag}]** {head}{rev} — \"{c.get('span','')}\"")
    cf = det.get("conflict_flag")
    if cf:
        lines.append(f"\n⚠️ **Policy-vs-law conflict:** handbook {cf['policy_value']} "
                     f"< legal floor {cf['law_floor']}.  \n_{cf['resolution']}_")
    lines.append(f"\n---\n_{det.get('disclaimer','')}_")
    lines.append(f"\n`~{tokens} tokens · {seconds:.1f}s`")
    return "\n".join(lines)


def _contract_md(req: dict) -> str:
    return (
        f"**Approval required** — {req.get('action','')}  \n"
        f"- **Why:** {req.get('reason_for_gate','')}  \n"
        f"- **Effect:** {req.get('effect','')}  \n"
        f"- **Reversibility:** {req.get('reversibility','')}"
    )


# --- handlers ---------------------------------------------------------------
def open_case(emp_id, session):
    session = session or uuid.uuid4().hex[:8]
    if not emp_id:
        return session, None, "_Pick an employee case to begin._", 0, None, "", ""
    return (session, emp_id, _profile_md(emp_id), 0, None,
            "", "")  # reset turn, clear pending cfg, clear answer/side


def on_ask(question, emp_id, session, turn):
    if not emp_id:
        return ("_Open an employee case first._", "", gr.update(visible=False),
                "", gr.update(value=""), None, turn)
    if not (question or "").strip():
        return ("_Type a question._", "", gr.update(visible=False),
                "", gr.update(value=""), None, turn)
    graph, llm = _ensure()
    cfg = {"configurable": {"thread_id": f"{session}:{emp_id}:{turn}"}}
    t0, s0 = llm.total_tokens(), time.time()
    state = {"employee_id": emp_id, "user_message": question, "turn": turn}
    try:
        result = graph.invoke(state, cfg)
    except Exception as e:  # noqa: BLE001
        result = {"status": "error",
                  "draft": {"answer": f"Error: {e}", "disclaimer": config.DISCLAIMER,
                            "citations": []}}
    toks, secs = llm.total_tokens() - t0, time.time() - s0

    if result.get("__interrupt__"):
        req = result["__interrupt__"][0].value
        det = result.get("draft", {}) or {}
        return (_answer_md(result, pending=True), _side_md(result, toks, secs),
                gr.update(visible=True), _contract_md(req),
                gr.update(value=det.get("answer", "")), cfg, turn)
    # terminal without a gate (declined / abstained / needs_clarification / error)
    return (_answer_md(result), _side_md(result, toks, secs),
            gr.update(visible=False), "", gr.update(value=""), None, turn + 1)


def on_decide(choice, edited, cfg, turn):
    if not cfg:
        return "", gr.update(visible=False), turn
    graph, _ = _ensure()
    decision = {"choice": choice, "reviewer": "hr-admin", "decided_at": config.TODAY}
    if choice == "edit":
        decision["edited_answer"] = edited
    result = graph.invoke(Command(resume=decision), cfg)
    note = {"approve": "approved", "edit": "edited & approved", "deny": "denied"}[choice]
    return (_answer_md(result) + f"\n\n_Decision: **{note}** — recorded to the case log._",
            gr.update(visible=False), turn + 1)


# --- Blocks -----------------------------------------------------------------
def build_blocks():
    with gr.Blocks(title="HR Compliance Assistant") as demo:
        session = gr.State(None)
        emp_state = gr.State(None)
        turn_state = gr.State(0)
        cfg_state = gr.State(None)

        gr.Markdown("# HR Compliance Assistant\n"
                    "_HR-admin assistant for FMLA leave, FLSA pay, and benefits — "
                    "grounded in company policy + law, with a human approval gate. "
                    "Not legal advice._")

        with gr.Row():
            emp_dd = gr.Dropdown(choices=_employee_choices(), label="Employee case",
                                 scale=4)
            open_btn = gr.Button("Open case", variant="primary", scale=1)
        profile_md = gr.Markdown("_Pick an employee case to begin._")

        with gr.Row():
            with gr.Column(scale=3):
                question = gr.Textbox(label="Ask about this employee",
                                      placeholder="e.g. Is this employee eligible for FMLA leave?")
                ask_btn = gr.Button("Ask", variant="primary")
                answer_md = gr.Markdown()
                with gr.Group(visible=False) as approval_row:
                    contract_md = gr.Markdown()
                    edit_box = gr.Textbox(label="Edit the answer (used only if you click "
                                          "'Edit & approve')", lines=3)
                    with gr.Row():
                        approve_btn = gr.Button("Approve", variant="primary")
                        edit_btn = gr.Button("Edit & approve")
                        deny_btn = gr.Button("Deny", variant="stop")
            with gr.Column(scale=2):
                side_md = gr.Markdown()

        open_btn.click(open_case, [emp_dd, session],
                       [session, emp_state, profile_md, turn_state, cfg_state,
                        answer_md, side_md])
        ask_btn.click(on_ask, [question, emp_state, session, turn_state],
                      [answer_md, side_md, approval_row, contract_md, edit_box,
                       cfg_state, turn_state])
        approve_btn.click(lambda cfg, t: on_decide("approve", "", cfg, t),
                          [cfg_state, turn_state], [answer_md, approval_row, turn_state])
        edit_btn.click(lambda ed, cfg, t: on_decide("edit", ed, cfg, t),
                       [edit_box, cfg_state, turn_state],
                       [answer_md, approval_row, turn_state])
        deny_btn.click(lambda cfg, t: on_decide("deny", "", cfg, t),
                       [cfg_state, turn_state], [answer_md, approval_row, turn_state])
    return demo


if __name__ == "__main__":
    build_blocks().launch(theme=gr.themes.Soft())
