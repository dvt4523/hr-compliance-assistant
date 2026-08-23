"""Computed domains must not be gated behind retrieval recall.

If retrieval finds nothing (all candidates below the relevance bar), an FMLA/FLSA
question must still reach the deterministic tool (which injects its own governing
citations) and finalize — not abstain. Benefits (retrieval-only) still abstains.
"""
from src.graph import build_graph, run_turn
from src.retrieval import _RerankResult
from src.schemas import DraftOutput, RerankScore, RouteDecision, UsedCite


class _ThinRetrievalLLM:
    """Routes fmla, reranks EVERYTHING to 0.0 (retrieval abstains), then drafts a
    grounded answer citing whatever chunk lands at index 0 (the compute-injected rule)."""
    usage_log: list = []

    def generate_json(self, prompt, schema, **k):
        if schema is RouteDecision:
            return RouteDecision(domain="fmla", intent="eligibility", confidence=0.95)
        if schema is _RerankResult:
            return _RerankResult(scores=[RerankScore(id=i, relevance=0.0) for i in range(8)])
        if schema is DraftOutput:
            return DraftOutput(status="answered", answer="Not eligible.",
                               used=[UsedCite(chunk_index=0, span="x")])
        raise AssertionError(f"unexpected schema {schema}")

    def generate(self, *a, **k):
        return ""

    def total_tokens(self):
        return 0


def test_computed_domain_reaches_tool_despite_thin_retrieval():
    graph = build_graph(llm=_ThinRetrievalLLM())
    result = run_turn(graph, "E002", "Is this employee eligible for FMLA leave?",
                      on_interrupt=lambda req: {"choice": "approve"}, turn=0)
    # retrieval scored 0 for everything, but the compute tool still ran and grounded
    # the answer with its injected citation -> finalized, not abstained.
    assert result["status"] == "finalized"
    assert result["tool_result"]["eligible"] is False
    assert any(c["section"].startswith("825.110") for c in result["draft"]["citations"])
