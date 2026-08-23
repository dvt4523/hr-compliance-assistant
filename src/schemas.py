"""Typed contracts — every inter-node payload and every structured LLM output.

Pydantic v2. LLM structured outputs use model_json_schema() via Siraya's
response_format; results are parsed with model_validate_json (never json.loads).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Domain = Literal["fmla", "flsa_minwage", "flsa_overtime", "benefits", "out_of_scope"]


# --- Routing ---------------------------------------------------------------
class RouteDecision(BaseModel):
    domain: Domain = Field(description="Which compliance domain the question falls in.")
    intent: str = Field(description="Short phrase naming what the HR admin is asking.")
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = Field(
        default=False,
        description="True if the question is in scope but too ambiguous to answer as-is.",
    )
    clarifying_question: Optional[str] = None


# --- Retrieval -------------------------------------------------------------
class RerankScore(BaseModel):
    id: int = Field(description="The candidate number shown in the prompt.")
    relevance: float = Field(ge=0.0, le=1.0)


# --- Citations & grounded answer ------------------------------------------
class Citation(BaseModel):
    doc_type: Literal["law", "policy"]
    source: str
    citation: str
    section: str
    revision: str
    span: str = Field(description="Exact text relied on; for law, echoes verbatim_anchor.")
    url: Optional[str] = None


class ConflictFlag(BaseModel):
    policy_cite: str
    law_cite: str
    policy_value: str
    law_floor: str
    resolution: str = Field(description="Which controls and why (law floor wins).")


class GroundedDetermination(BaseModel):
    status: Literal["answered", "not_covered", "declined", "needs_clarification"]
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    basis: Optional[str] = Field(
        default=None, description="'federal' or 'state' when a jurisdiction rule applied."
    )
    conflict_flag: Optional[ConflictFlag] = None
    disclaimer: str = ""


# --- Drafter output (LLM) -> assembled into GroundedDetermination ----------
# The model returns only the chunk index + the exact span it used; we build the
# Citation deterministically from the matched chunk so metadata can't drift.
class UsedCite(BaseModel):
    chunk_index: int = Field(description="Index of the passage relied on, as shown in the prompt.")
    span: str = Field(description="The exact text quoted from that passage (verbatim).")


class DraftOutput(BaseModel):
    status: Literal["answered", "not_covered"]
    answer: str
    used: list[UsedCite] = Field(default_factory=list)
    basis: Optional[str] = Field(default=None, description="'federal' or 'state' if a jurisdiction rule applied.")


# --- Deterministic tool results -------------------------------------------
class RuleCheck(BaseModel):
    rule: str
    passed: bool
    detail: str
    citation: Optional[str] = None


class EligibilityResult(BaseModel):
    eligible: bool
    per_rule: list[RuleCheck]
    deciding_rule: Optional[str] = Field(
        default=None, description="First failing rule; None if eligible."
    )
    weeks_entitled: int
    weeks_remaining: float
    citations: list[str] = Field(default_factory=list)


class WageResult(BaseModel):
    applicable: bool = Field(description="False when the min-wage test does not apply.")
    compliant: Optional[bool] = None
    pay_rate: Optional[float] = None
    applicable_min: float = 0.0
    basis: str = ""  # "federal" | "state"
    shortfall: float = 0.0
    citations: list[str] = Field(default_factory=list)


class OvertimeResult(BaseModel):
    classification_label: str          # what the employer called it
    classification_effective: str      # what the law makes it
    misclassified: bool
    regular_rate: float
    ot_hours_1_5: float
    ot_hours_2_0: float
    ot_pay: float
    rules_applied: list[str] = Field(default_factory=list)
    basis: str = ""                    # "federal" | "state"
    citations: list[str] = Field(default_factory=list)


# --- Guardrails ------------------------------------------------------------
class GuardrailCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class GuardrailReport(BaseModel):
    checks: list[GuardrailCheck] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


# --- HITL (Week 7 approval contract) --------------------------------------
class ApprovalRequest(BaseModel):
    action: str
    reason_for_gate: str
    evidence: dict
    effect: str
    reversibility: str
    options: list[str] = Field(default_factory=lambda: ["approve", "edit", "ask", "deny"])


class HumanDecision(BaseModel):
    choice: Literal["approve", "edit", "ask", "deny"]
    edited_answer: Optional[str] = None
    question: Optional[str] = None
    note: Optional[str] = None
    # audit (stamped at resume / when logged)
    reviewer: Optional[str] = None
    decided_at: Optional[str] = None
