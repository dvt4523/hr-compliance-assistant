"""Graph wiring: the privacy-decline path is terminal and calls no LLM.

(Full end-to-end behaviour with a live model is exercised by the eval harness;
this guards the load_profile -> guard_input -> END wiring without a network.)
"""
import pytest

from src.graph import build_graph, run_turn


class _NoCallLLM:
    """Fails loudly if any node tries to call the model on the decline path."""
    usage_log: list = []

    def generate_json(self, *a, **k):
        raise AssertionError("no LLM call expected on the privacy-decline path")

    def generate(self, *a, **k):
        raise AssertionError("no LLM call expected on the privacy-decline path")

    def total_tokens(self):
        return 0


def test_privacy_decline_is_terminal_without_llm():
    graph = build_graph(llm=_NoCallLLM())
    result = run_turn(
        graph, "E001", "Is Marcus Bello eligible for FMLA?",
        on_interrupt=lambda req: {"choice": "approve"}, turn=0,
    )
    assert result["status"] == "declined"
    assert "case is open" in result["draft"]["answer"]
