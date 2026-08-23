"""LangGraph control spine (mirrors lab07): typed state, conditional edges,
interrupt() for HITL, checkpointer per thread_id = employee_id.

Nodes are closures over one LLMClient. The graph is headless — CLI, eval, and
the Gradio UI all drive it through `run_turn`.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import config, data_loader, guardrails, prompts
from .llm import LLMClient
from .schemas import (
    ApprovalRequest,
    Citation,
    DraftOutput,
    GroundedDetermination,
    GuardrailReport,
    RouteDecision,
)
from .tools.fmla import check_fmla_eligibility
from .tools.overtime import compute_overtime
from .tools.records import ScopeViolation, get_employee_record
from .tools.search import search_policy
from .tools.wage import check_minimum_wage
from .tools.caselog import append_case_log

COMPUTED = {"fmla", "flsa_minwage", "flsa_overtime"}
INFORMATIONAL = {"benefits"}


class CaseState(TypedDict, total=False):
    employee_id: str
    turn: int
    user_message: str
    employee: dict
    site: dict
    route: dict
    retrieved: list[dict]
    top_relevance: float
    tool_result: Optional[dict]
    draft: dict                 # GroundedDetermination.model_dump()
    guardrail_report: dict
    approval: dict
    status: str
    revise_count: int
    clarify_count: int


def _decline(msg: str) -> dict:
    return GroundedDetermination(
        status="declined", answer=msg, disclaimer=config.DISCLAIMER
    ).model_dump()


def _fallback(lead: str, status: str = "not_covered") -> dict:
    """A non-answerable exit that routes the HR admin to a human (escalation)."""
    return GroundedDetermination(
        status=status, answer=f"{lead} {config.ESCALATE_MSG}", disclaimer=config.DISCLAIMER
    ).model_dump()


def build_graph(llm: Optional[LLMClient] = None):
    llm = llm or LLMClient()

    # --- nodes -------------------------------------------------------------
    def load_profile(state: CaseState) -> dict:
        eid = state["employee_id"]
        emp = get_employee_record(eid, gated_id=eid)
        return {"employee": emp, "site": data_loader.site_for_employee(emp),
                "revise_count": 0, "clarify_count": 0, "status": "ok"}

    def guard_input(state: CaseState) -> dict:
        check = guardrails.check_input_scope(state["user_message"], state["employee_id"])
        if not check.passed:
            return {"status": "declined",
                    "draft": _decline(
                        "I can only discuss the employee whose case is open. "
                        f"({check.detail})")}
        return {"status": "ok"}

    def route_node(state: CaseState) -> dict:
        rd: RouteDecision = llm.generate_json(
            prompts.route_prompt(state["user_message"]),
            RouteDecision, model=config.ROUTER_MODEL, system=prompts.ROUTE_SYSTEM,
        )
        if rd.domain == "out_of_scope":
            return {"route": rd.model_dump(), "status": "declined",
                    "draft": _fallback(
                        "That's outside what I handle (FMLA leave, FLSA pay, and benefits).",
                        status="declined")}
        if rd.needs_clarification or rd.confidence < config.CONF_BAR:
            q = rd.clarifying_question or "Could you clarify exactly what you'd like to know?"
            return {"route": rd.model_dump(), "status": "needs_clarification",
                    "draft": GroundedDetermination(
                        status="needs_clarification", answer=q,
                        disclaimer=config.DISCLAIMER).model_dump()}
        return {"route": rd.model_dump(), "status": "ok"}

    def retrieve_node(state: CaseState) -> dict:
        # Ablation: with RAG disabled the drafter gets no grounding context, but the
        # flow continues (compute + draft) rather than abstaining, so we can measure
        # what the deterministic tool backstop alone produces.
        if not config.RAG_ENABLED:
            return {"retrieved": [], "top_relevance": 0.0, "status": "ok"}
        domain = state["route"]["domain"]
        chunks, rel = search_policy(llm, state["user_message"], domain=domain,
                                    k=config.RETRIEVE_K)
        if not chunks:
            # Computed domains have a deterministic tool backstop and inject their own
            # governing citations in compute_node — so thin retrieval must NOT abstain
            # here; let the flow reach compute. Only retrieval-only domains (benefits)
            # abstain when nothing governs.
            if domain in COMPUTED:
                return {"retrieved": [], "top_relevance": rel, "status": "ok"}
            return {"retrieved": [], "top_relevance": rel, "status": "abstained",
                    "draft": _fallback(
                        "No policy or law passage on file governs this question.")}
        return {"retrieved": chunks, "top_relevance": rel, "status": "ok"}

    def compute_node(state: CaseState) -> dict:
        domain = state["route"]["domain"]
        emp, site = state["employee"], state["site"]
        if domain == "fmla":
            res = check_fmla_eligibility(emp, site)
        elif domain == "flsa_minwage":
            res = check_minimum_wage(emp, site)
        else:  # flsa_overtime
            res = compute_overtime(emp, site)
        result = res.model_dump()
        # Inject the determination's own governing chunks so the drafter always sees
        # the deciding rule (generic retrieval doesn't reliably surface the exact prong).
        # This injection is itself a grounding path, so it's disabled under the no-RAG ablation.
        gov = data_loader.get_chunks_by_citation(result.get("citations", [])) if config.RAG_ENABLED else []
        gov_ids = {c["id"] for c in gov}
        merged = gov + [c for c in state.get("retrieved", []) if c["id"] not in gov_ids]
        return {"tool_result": result, "retrieved": merged}

    def draft_node(state: CaseState) -> dict:
        domain = state["route"]["domain"]
        retrieved = state["retrieved"]
        out: DraftOutput = llm.generate_json(
            prompts.draft_prompt(state["user_message"], retrieved,
                                 state.get("tool_result"), domain),
            DraftOutput, model=config.REASONING_MODEL, system=prompts.DRAFT_SYSTEM,
        )
        citations = []
        for u in out.used:
            if 0 <= u.chunk_index < len(retrieved):
                c = retrieved[u.chunk_index]
                # For LAW chunks the verbatim_anchor is the authoritative governing phrase;
                # use it as the span so fidelity holds regardless of how the model transcribed
                # it. Policy chunks (no anchor) keep the model's quoted span (fidelity-checked).
                span = c.get("verbatim_anchor") or u.span
                citations.append(Citation(
                    doc_type=c.get("doc_type", "policy"), source=c.get("source", ""),
                    citation=c.get("citation", ""), section=c.get("section", ""),
                    revision=c.get("revision", ""), span=span, url=c.get("url"),
                ))
        conflict = guardrails.detect_conflict(retrieved, domain)
        det = GroundedDetermination(
            status="answered" if out.status == "answered" else "not_covered",
            answer=out.answer, citations=citations, basis=out.basis,
            conflict_flag=conflict, disclaimer=config.DISCLAIMER,
        )
        return {"draft": det.model_dump(), "status": "ok"}

    def guard_output_node(state: CaseState) -> dict:
        domain = state["route"]["domain"]
        det = GroundedDetermination(**state["draft"])
        fidelity = guardrails.check_citation_fidelity(det)
        grounding = guardrails.check_grounding(det, domain)
        report = GuardrailReport(checks=[fidelity, grounding])
        ok = fidelity.passed and grounding.passed
        if not ok and state.get("revise_count", 0) < config.MAX_REVISE:
            # one bounded reconcile loop (reviewer != author): redraft once
            return {"guardrail_report": report.model_dump(),
                    "revise_count": state.get("revise_count", 0) + 1, "status": "revise"}
        if not ok:
            # fail closed: never present an ungrounded compliance answer -> escalate
            return {"guardrail_report": report.model_dump(), "status": "abstained_fallback",
                    "draft": _fallback("I don't have a well-grounded answer for this.")}
        return {"guardrail_report": report.model_dump(), "status": "ok"}

    def approval_gate_node(state: CaseState) -> dict:
        det = state["draft"]
        req = ApprovalRequest(
            action=f"Finalize {state['route']['domain']} determination for {state['employee_id']}",
            reason_for_gate="A compliance determination affects an employee's legal rights.",
            evidence={"answer": det["answer"], "citations": det["citations"],
                      "tool_result": state.get("tool_result"),
                      "conflict_flag": det.get("conflict_flag")},
            effect="Records the determination in the case log.",
            reversibility="Reversible: a log entry can be superseded.",
        )
        decision = interrupt(req.model_dump())     # pauses; resume value returned here
        return {"approval": decision}

    def finalize_node(state: CaseState) -> dict:
        decision = state.get("approval") or {"choice": "approve"}
        det = dict(state["draft"])
        if decision.get("choice") == "edit" and decision.get("edited_answer"):
            det["answer"] = decision["edited_answer"]
        status = "denied" if decision.get("choice") == "deny" else "finalized"
        append_case_log(
            employee_id=state["employee_id"], turn=state.get("turn", 0),
            determination=det["answer"][:200], decision=decision,
            evidence={"citations": det["citations"], "tool_result": state.get("tool_result")},
        )
        return {"draft": det, "status": status}

    # --- edges -------------------------------------------------------------
    def after_guard_input(s):  return "end" if s["status"] == "declined" else "route"
    def after_route(s):        return "retrieve" if s["status"] == "ok" else "end"
    def after_retrieve(s):
        if s["status"] == "abstained":
            return "end"
        return "compute" if s["route"]["domain"] in COMPUTED else "draft"
    def after_guard_output(s):
        if s["status"] == "revise":
            return "draft"
        if s["status"] == "abstained_fallback":
            return "end"          # nothing to finalize/approve on a fallback abstention
        return "approve"
    def after_approval(s):
        choice = (s.get("approval") or {}).get("choice", "approve")
        if choice == "ask":
            return "retrieve"
        return "finalize"

    g = StateGraph(CaseState)
    for name, fn in [
        ("load_profile", load_profile), ("guard_input", guard_input), ("route", route_node),
        ("retrieve", retrieve_node), ("compute", compute_node), ("draft", draft_node),
        ("guard_output", guard_output_node), ("approval_gate", approval_gate_node),
        ("finalize", finalize_node),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "load_profile")
    g.add_edge("load_profile", "guard_input")
    g.add_conditional_edges("guard_input", after_guard_input, {"route": "route", "end": END})
    g.add_conditional_edges("route", after_route, {"retrieve": "retrieve", "end": END})
    g.add_conditional_edges("retrieve", after_retrieve,
                            {"compute": "compute", "draft": "draft", "end": END})
    g.add_edge("compute", "draft")
    g.add_edge("draft", "guard_output")
    g.add_conditional_edges("guard_output", after_guard_output,
                            {"draft": "draft", "approve": "approval_gate", "end": END})
    g.add_conditional_edges("approval_gate", after_approval,
                            {"finalize": "finalize", "retrieve": "retrieve"})
    g.add_edge("finalize", END)

    return g.compile(checkpointer=MemorySaver())


def run_turn(graph, employee_id: str, user_message: str,
             on_interrupt: Callable[[dict], dict], turn: int = 0) -> dict:
    """Drive one turn to completion, handling the HITL interrupt via callback."""
    cfg = {"configurable": {"thread_id": f"{employee_id}:{turn}"}}
    state: dict[str, Any] = {"employee_id": employee_id, "user_message": user_message,
                             "turn": turn}
    try:
        result = graph.invoke(state, cfg)
        while result.get("__interrupt__"):
            req = result["__interrupt__"][0].value
            decision = on_interrupt(req)
            result = graph.invoke(Command(resume=decision), cfg)
        return result
    except Exception as e:  # noqa: BLE001 - graceful terminal fallback, never crash a turn
        return {"status": "error", "error": str(e),
                "draft": _fallback("I hit an unexpected error handling this.", status="declined")}
