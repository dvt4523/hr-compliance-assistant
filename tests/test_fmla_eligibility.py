"""FMLA eligibility: each persona isolates one rule."""
import pytest

from src.tools.fmla import check_fmla_eligibility_by_id


@pytest.mark.parametrize(
    "emp_id, eligible, deciding",
    [
        ("E001", True, None),        # all three pass
        ("E002", False, "tenure"),   # 8 months < 12
        ("E003", False, "hours"),    # 900 < 1250
        ("E004", False, "worksite"), # site has 18 within 75mi < 50
        ("E005", True, None),        # eligible (has a policy-conflict, not an eligibility fail)
        ("E006", True, None),        # eligible
    ],
)
def test_eligibility_outcomes(emp_id, eligible, deciding):
    r = check_fmla_eligibility_by_id(emp_id)
    assert r.eligible is eligible
    assert r.deciding_rule == deciding


def test_entitlement_balance_e005():
    # E005 already took 10 of 12 weeks -> 2 remain (not zero, despite the 8wk handbook cap)
    r = check_fmla_eligibility_by_id("E005")
    assert r.weeks_entitled == 12
    assert r.weeks_remaining == 2


def test_failing_rule_carries_citation():
    r = check_fmla_eligibility_by_id("E004")
    worksite = next(rc for rc in r.per_rule if rc.rule == "worksite")
    assert worksite.passed is False
    assert worksite.citation == "29 CFR §825.110(a)(3)"
