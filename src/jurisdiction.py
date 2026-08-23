"""Jurisdiction resolvers — the 'more-protective of federal vs state' core.

Pure functions over the state_rules table. No LLM. These are the load-bearing
compliance calculations; keeping them deterministic makes eval task-success
objective and the answers auditable.
"""
from __future__ import annotations

from . import config


def applicable_min_wage(rules: dict, state: str) -> tuple[float, str, list[str]]:
    """Return (applicable_min, basis, citations). Applicable = max(federal, state)."""
    us = rules["US"]
    st = rules.get(state, us)
    if st["min_wage"] > us["min_wage"]:
        return st["min_wage"], "state", [st["min_wage_citation"], us["min_wage_citation"]]
    return us["min_wage"], "federal", [us["min_wage_citation"]]


def exemption_threshold(rules: dict, state: str) -> tuple[float, str, list[str]]:
    """Return (annual_threshold, basis, citations). Threshold = max(federal, state)."""
    us = rules["US"]
    st = rules.get(state, us)
    us_t = us["exempt_salary_threshold_annual"]
    st_t = st.get("exempt_salary_threshold_annual", us_t)
    if st_t > us_t:
        return st_t, "state", [st["exempt_threshold_citation"], us["exempt_threshold_citation"]]
    return us_t, "federal", [us["exempt_threshold_citation"]]


def overtime_hours(daily_hours: list[float] | None, weekly_hours: float,
                   rules: dict, state: str) -> tuple[float, float, list[str], str]:
    """Return (hours_at_1.5x, hours_at_2x, rules_applied, basis).

    Federal weekly (>40h x1.5) always applies. A daily-overtime state (e.g. CA)
    adds daily x1.5 over 8h and x2 over 12h. California forbids pyramiding
    (counting the same hour twice); we approximate that by taking the GREATER of
    the daily-1.5x total and the federal weekly-1.5x total, plus double-time
    hours separately. This is a documented simplification of the full DLSE rules.
    """
    us = rules["US"]
    st = rules.get(state, us)
    rules_applied: list[str] = []

    fed_weekly = max(0.0, weekly_hours - us["weekly_ot_threshold"])
    if fed_weekly > 0:
        rules_applied.append(us["ot_citation"])

    daily_1_5 = 0.0
    daily_2_0 = 0.0
    if st.get("daily_ot") and daily_hours:
        d1 = st["daily_ot_threshold"]
        d2 = st["double_time_threshold"]
        for h in daily_hours:
            if h > d2:
                daily_2_0 += h - d2
                daily_1_5 += d2 - d1
            elif h > d1:
                daily_1_5 += h - d1
        if daily_1_5 > 0 or daily_2_0 > 0:
            rules_applied.append(st["ot_citation"])

    # No pyramiding: the 1.5x premium is the greater of daily vs weekly (not both).
    h_1_5 = max(daily_1_5, fed_weekly)
    h_2_0 = daily_2_0
    basis = "state" if (daily_1_5 >= fed_weekly and (daily_1_5 > 0 or daily_2_0 > 0)) else "federal"
    return h_1_5, h_2_0, rules_applied, basis


def regular_rate(employee: dict) -> float:
    """Hourly regular rate: pay_rate_hourly, or salary / 2080 for salaried."""
    if employee.get("pay_rate_hourly") is not None:
        return float(employee["pay_rate_hourly"])
    if employee.get("annual_salary"):
        return round(employee["annual_salary"] / config.HOURS_PER_YEAR, 2)
    return 0.0
