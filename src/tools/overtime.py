"""Overtime calculator (deterministic), including the misclassification gate.

An employee LABELED exempt is only truly exempt if paid at least the applicable
salary threshold (max of federal vs state). Below it -> misclassified -> treated
as non-exempt and owed overtime. (Salary-basis test only; the duties test is a
documented limitation.)
"""
from __future__ import annotations

from .. import data_loader, jurisdiction
from ..schemas import OvertimeResult


def compute_overtime(employee: dict, site: dict) -> OvertimeResult:
    rules = data_loader.load_state_rules()
    state = site.get("state", "US")
    label = employee.get("classification", "non-exempt")
    rate = jurisdiction.regular_rate(employee)

    misclassified = False
    effective = label

    if label == "exempt":
        threshold, _basis, cites = jurisdiction.exemption_threshold(rules, state)
        salary = employee.get("annual_salary") or 0
        if salary < threshold:
            misclassified = True
            effective = "non-exempt"
        else:
            # Correctly exempt: no overtime owed.
            return OvertimeResult(
                classification_label=label,
                classification_effective="exempt",
                misclassified=False,
                regular_rate=rate,
                ot_hours_1_5=0.0,
                ot_hours_2_0=0.0,
                ot_pay=0.0,
                rules_applied=[],
                basis="",
                citations=cites,
            )

    # Non-exempt (by label or by misclassification) -> compute overtime.
    daily = employee.get("daily_hours_last_week")
    weekly = employee.get("hours_last_week", 0)
    h_1_5, h_2_0, rules_applied, basis = jurisdiction.overtime_hours(daily, weekly, rules, state)
    ot_pay = round(h_1_5 * rate * 1.5 + h_2_0 * rate * 2.0, 2)

    citations = list(rules_applied)
    if misclassified:
        threshold, _b, cites = jurisdiction.exemption_threshold(rules, state)
        citations = cites + citations

    return OvertimeResult(
        classification_label=label,
        classification_effective=effective,
        misclassified=misclassified,
        regular_rate=rate,
        ot_hours_1_5=h_1_5,
        ot_hours_2_0=h_2_0,
        ot_pay=ot_pay,
        rules_applied=rules_applied,
        basis=basis,
        citations=citations,
    )


def compute_overtime_by_id(employee_id: str) -> OvertimeResult:
    emp = data_loader.load_employees()[employee_id]
    return compute_overtime(emp, data_loader.site_for_employee(emp))
