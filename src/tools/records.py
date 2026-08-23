"""Read tools: employee record + leave history. Scoped to the gated employee.

The scope check is a privacy guardrail at the tool boundary: a case is gated to
one employee_id, so a request for any other id is refused rather than served.
"""
from __future__ import annotations

from .. import data_loader


class ScopeViolation(Exception):
    """Raised when a tool is asked for an employee outside the gated case."""


def get_employee_record(employee_id: str, *, gated_id: str | None = None) -> dict:
    """Return the employee record. If gated_id is set, only that id is allowed."""
    if gated_id is not None and employee_id != gated_id:
        raise ScopeViolation(
            f"Refused: this session is scoped to {gated_id}, not {employee_id}."
        )
    employees = data_loader.load_employees()
    if employee_id not in employees:
        raise KeyError(f"No employee {employee_id}")
    return employees[employee_id]


def get_leave_history(employee_id: str, *, gated_id: str | None = None) -> dict:
    """Return FMLA leave usage for the gated employee (weeks taken this period)."""
    emp = get_employee_record(employee_id, gated_id=gated_id)
    return {
        "employee_id": employee_id,
        "leave_taken_weeks_ytd": emp.get("leave_taken_weeks_ytd", 0),
        "employment_status": emp.get("employment_status"),
    }
