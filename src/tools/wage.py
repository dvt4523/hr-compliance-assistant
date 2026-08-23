"""Minimum-wage calculator (deterministic). Applies max(federal, state)."""
from __future__ import annotations

from .. import data_loader, jurisdiction
from ..schemas import WageResult


def check_minimum_wage(employee: dict, site: dict) -> WageResult:
    rules = data_loader.load_state_rules()
    state = site.get("state", "US")
    applicable_min, basis, citations = jurisdiction.applicable_min_wage(rules, state)

    pay_rate = employee.get("pay_rate_hourly")
    if pay_rate is None:
        # Salaried: compare an effective hourly rate for context (informational).
        rate = jurisdiction.regular_rate(employee)
        compliant = rate >= applicable_min if rate else None
        return WageResult(
            applicable=False,
            compliant=compliant,
            pay_rate=rate or None,
            applicable_min=applicable_min,
            basis=basis,
            shortfall=0.0,
            citations=citations,
        )

    compliant = pay_rate >= applicable_min
    shortfall = round(max(0.0, applicable_min - pay_rate), 2)
    return WageResult(
        applicable=True,
        compliant=compliant,
        pay_rate=pay_rate,
        applicable_min=applicable_min,
        basis=basis,
        shortfall=shortfall,
        citations=citations,
    )


def check_minimum_wage_by_id(employee_id: str) -> WageResult:
    emp = data_loader.load_employees()[employee_id]
    return check_minimum_wage(emp, data_loader.site_for_employee(emp))
