"""Fallback / fail-closed guardrails for out-of-answer-scope situations."""
from src import config
from src.graph import build_graph, run_turn
from src.guardrails import check_grounding
from src.retrieval import _RerankResult
from src.schemas import DraftOutput, GroundedDetermination, RerankScore, RouteDecision


# --- unit: grounding guard -------------------------------------------------
def test_grounding_requires_citation_for_computed_domain():
    det = GroundedDetermination(status="answered", answer="Eligible.", citations=[])
    assert check_grounding(det, "fmla").passed is False


def test_grounding_not_required_for_benefits():
    det = GroundedDetermination(status="answered", answer="See the plan.", citations=[])
    assert check_grounding(det, "benefits").passed is True


def test_grounding_ok_when_abstained():
    det = GroundedDetermination(status="not_covered", answer="No passage governs.", citations=[])
    assert check_grounding(det, "fmla").passed is True


# --- integration: guard_output fails closed on a bad citation --------------
class _BadCiteLLM:
    """Routes fmla, reranks everything relevant, then drafts an UNGROUNDED answer
    (answered but with NO citation) — which the grounding guard must reject."""
    usage_log: list = []

    def generate_json(self, prompt, schema, **k):
        if schema is RouteDecision:
            return RouteDecision(domain="fmla", intent="eligibility", confidence=0.95)
        if schema is _RerankResult:
            return _RerankResult(scores=[RerankScore(id=i, relevance=1.0) for i in range(8)])
        if schema is DraftOutput:
            return DraftOutput(status="answered", answer="Eligible.", used=[])
        raise AssertionError(f"unexpected schema {schema}")

    def generate(self, *a, **k):
        return ""

    def total_tokens(self):
        return 0


def test_ungrounded_answer_fails_closed_to_escalation():
    graph = build_graph(llm=_BadCiteLLM())
    result = run_turn(graph, "E001", "Is this employee eligible for FMLA leave?",
                      on_interrupt=lambda req: {"choice": "approve"}, turn=0)
    # never reaches HITL/finalize; ends in a safe escalation fallback
    assert result["status"] == "abstained_fallback"
    assert config.ESCALATE_MSG in result["draft"]["answer"]
