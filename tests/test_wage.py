"""Minimum wage: max(federal, state); CA violation vs TX compliant."""
from src.tools.wage import check_minimum_wage_by_id


def test_ca_violation_e003():
    r = check_minimum_wage_by_id("E003")           # $15.00 in CA (min $16.90)
    assert r.applicable is True
    assert r.compliant is False
    assert r.applicable_min == 16.90
    assert r.basis == "state"
    assert r.shortfall == 1.90


def test_tx_compliant_e002():
    r = check_minimum_wage_by_id("E002")           # $9.00 in TX (min $7.25)
    assert r.compliant is True
    assert r.applicable_min == 7.25
    assert r.basis == "federal"
    assert r.shortfall == 0.0


def test_ca_compliant_e001():
    r = check_minimum_wage_by_id("E001")           # $22.00 in CA
    assert r.compliant is True
    assert r.basis == "state"
