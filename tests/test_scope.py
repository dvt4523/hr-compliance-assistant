"""Privacy guardrail at the tool boundary: a case is scoped to one employee."""
import pytest

from src.tools.records import ScopeViolation, get_employee_record


def test_gated_id_allows_self():
    rec = get_employee_record("E001", gated_id="E001")
    assert rec["employee_id"] == "E001"


def test_gated_id_refuses_other_employee():
    with pytest.raises(ScopeViolation):
        get_employee_record("E002", gated_id="E001")


def test_no_gate_allows_lookup():
    # eval/admin path (no gate) can still read any record
    assert get_employee_record("E003")["name"] == "Lena Vasquez"
