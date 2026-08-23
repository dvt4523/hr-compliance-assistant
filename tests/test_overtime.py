"""Overtime: CA daily overlay, federal weekly, correct-exempt, and misclassification."""
from src.tools.overtime import compute_overtime_by_id


def test_ca_daily_overtime_e001():
    # 40h week but a 10h day -> 2h CA daily OT; federal alone would owe 0
    r = compute_overtime_by_id("E001")
    assert r.ot_hours_1_5 == 2
    assert r.ot_hours_2_0 == 0
    assert r.basis == "state"
    assert r.ot_pay == round(2 * 22.0 * 1.5, 2)   # 66.0


def test_federal_weekly_overtime_e002():
    # TX, 44h -> 4h federal weekly OT, no daily
    r = compute_overtime_by_id("E002")
    assert r.ot_hours_1_5 == 4
    assert r.basis == "federal"
    assert r.ot_pay == round(4 * 9.0 * 1.5, 2)    # 54.0


def test_correctly_exempt_e004():
    # $98k exempt in TX -> above threshold -> no OT
    r = compute_overtime_by_id("E004")
    assert r.misclassified is False
    assert r.classification_effective == "exempt"
    assert r.ot_pay == 0.0


def test_misclassified_e006():
    # labeled exempt, $62,400 > federal $35,568 but < CA $70,304 -> misclassified -> owed OT
    r = compute_overtime_by_id("E006")
    assert r.misclassified is True
    assert r.classification_effective == "non-exempt"
    assert r.regular_rate == 30.0                 # 62400 / 2080
    assert r.ot_hours_1_5 == 6
    assert r.ot_pay == round(6 * 30.0 * 1.5, 2)   # 270.0
