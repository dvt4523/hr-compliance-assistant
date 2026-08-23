"""Guardrails (deterministic): scope/privacy, citation fidelity, conflict flag."""
from src import data_loader
from src.guardrails import check_citation_fidelity, check_input_scope, detect_conflict
from src.schemas import Citation, GroundedDetermination


def test_scope_blocks_other_employee_by_name():
    assert check_input_scope("Is Marcus Bello eligible?", gated_id="E001").passed is False


def test_scope_blocks_other_employee_by_id():
    assert check_input_scope("What about E003?", gated_id="E001").passed is False


def test_scope_allows_generic_question():
    assert check_input_scope("Is this employee eligible for leave?", gated_id="E001").passed is True


def _policy_chunk(section, text):
    return {"doc_type": "policy", "citation": f"Handbook §{section}", "section": section, "text": text}


def test_conflict_flag_fires_below_floor():
    retrieved = [_policy_chunk("LV-4.2", "up to 8 weeks of unpaid family and medical leave")]
    cf = detect_conflict(retrieved, "fmla")
    assert cf is not None and cf.policy_value == "8 weeks" and cf.law_floor == "12 workweeks"


def test_no_conflict_when_more_generous():
    retrieved = [_policy_chunk("LV-4.3", "up to 12 weeks of paid parental leave")]
    assert detect_conflict(retrieved, "fmla") is None


def test_no_conflict_outside_fmla():
    retrieved = [_policy_chunk("LV-4.2", "up to 8 weeks")]
    assert detect_conflict(retrieved, "flsa_overtime") is None


def test_citation_fidelity_pass_and_fail():
    # a real law chunk + its verbatim anchor -> passes
    law = next(c for c in data_loader.load_corpus() if c.get("section") == "825.200")
    good = GroundedDetermination(status="answered", answer="ok", citations=[Citation(
        doc_type="law", source=law["source"], citation=law["citation"], section="825.200",
        revision=law["revision"], span=law["verbatim_anchor"], url=law.get("url"))])
    assert check_citation_fidelity(good).passed is True

    bad = good.model_copy(deep=True)
    bad.citations[0].span = "a fabricated phrase not in the source"
    assert check_citation_fidelity(bad).passed is False
