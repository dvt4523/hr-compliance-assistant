"""FMLA eligibility calculator (deterministic). Three rules, each isolable.

Reads the employee record + their worksite. Returns a typed result naming the
first failing rule and the governing citation for each prong.
"""
from __future__ import annotations

from .. import config, data_loader
from ..schemas import EligibilityResult, RuleCheck

# Citations for each eligibility prong (match data/legal/fmla.json).
CITE_TENURE = "29 CFR §825.110(a)(1)"
CITE_HOURS = "29 CFR §825.110(a)(2)"
CITE_WORKSITE = "29 CFR §825.110(a)(3)"
CITE_ENTITLEMENT = "29 CFR §825.200"


def check_fmla_eligibility(employee: dict, site: dict) -> EligibilityResult:
    tenure = employee.get("tenure_months", 0)
    hours = employee.get("hours_last_12mo", 0)
    headcount = site.get("headcount_within_75mi", 0)
    taken = employee.get("leave_taken_weeks_ytd", 0)

    per_rule = [
        RuleCheck(
            rule="tenure",
            passed=tenure >= config.FMLA_TENURE_MONTHS,
            detail=f"{tenure} months employed (requires >= {config.FMLA_TENURE_MONTHS}).",
            citation=CITE_TENURE,
        ),
        RuleCheck(
            rule="hours",
            passed=hours >= config.FMLA_HOURS,
            detail=f"{hours} hours in last 12 months (requires >= {config.FMLA_HOURS}).",
            citation=CITE_HOURS,
        ),
        RuleCheck(
            rule="worksite",
            passed=headcount >= config.FMLA_WORKSITE_HEADCOUNT,
            detail=(
                f"{headcount} employees within {config.FMLA_WORKSITE_MILES} miles of the "
                f"worksite (requires >= {config.FMLA_WORKSITE_HEADCOUNT})."
            ),
            citation=CITE_WORKSITE,
        ),
    ]

    eligible = all(r.passed for r in per_rule)
    deciding = next((r.rule for r in per_rule if not r.passed), None)
    remaining = max(0.0, config.FMLA_ENTITLEMENT_WEEKS - taken)

    citations = [r.citation for r in per_rule if r.citation]
    if eligible:
        citations.append(CITE_ENTITLEMENT)

    return EligibilityResult(
        eligible=eligible,
        per_rule=per_rule,
        deciding_rule=deciding,
        weeks_entitled=config.FMLA_ENTITLEMENT_WEEKS,
        weeks_remaining=remaining,
        citations=citations,
    )


def check_fmla_eligibility_by_id(employee_id: str) -> EligibilityResult:
    emp = data_loader.load_employees()[employee_id]
    return check_fmla_eligibility(emp, data_loader.site_for_employee(emp))
