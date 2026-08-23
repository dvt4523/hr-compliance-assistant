"""Deterministic guardrails (Week 4: safety is architecture, not a prompt).

1. input scope/privacy  — refuse questions about other employees
2. citation fidelity     — a cited span must be verbatim in its source chunk
3. policy-vs-law conflict — handbook clause below the legal floor -> flag
(The cite-or-abstain relevance gate lives in retrieval.)
"""
from __future__ import annotations

import re

from . import config, data_loader
from .schemas import Citation, ConflictFlag, GroundedDetermination, GuardrailCheck

_EMP_ID = re.compile(r"\bE0\d\d\b")


def check_input_scope(user_message: str, gated_id: str) -> GuardrailCheck:
    """Block references to any employee other than the gated one (privacy)."""
    employees = data_loader.load_employees()
    msg = user_message.lower()

    # explicit ids
    for eid in _EMP_ID.findall(user_message.upper()):
        if eid != gated_id:
            return GuardrailCheck(name="scope_privacy", passed=False,
                                  detail=f"References another employee id {eid}.")
    # other employees' names
    for eid, emp in employees.items():
        if eid == gated_id:
            continue
        first = emp["name"].split()[0].lower()
        last = emp["name"].split()[-1].lower()
        if re.search(rf"\b{re.escape(last)}\b", msg) or re.search(rf"\b{re.escape(first)}\b", msg):
            return GuardrailCheck(name="scope_privacy", passed=False,
                                  detail=f"References another employee ({emp['name']}).")
    return GuardrailCheck(name="scope_privacy", passed=True)


def check_citation_fidelity(det: GroundedDetermination) -> GuardrailCheck:
    """Every cited span must be a verbatim substring of its source chunk text/anchor.

    (Citations are built from matched chunks, so we re-verify the span the model quoted.)
    """
    for cit in det.citations:
        haystack = f"{cit.span}"  # span was taken from the chunk; re-check against source text
        chunk = _find_chunk(cit)
        if chunk is None:
            return GuardrailCheck(name="citation_fidelity", passed=False,
                                  detail=f"Cited chunk not found: {cit.citation}.")
        source_text = f"{chunk.get('text','')} {chunk.get('verbatim_anchor','')}"
        if cit.span and cit.span not in source_text:
            return GuardrailCheck(name="citation_fidelity", passed=False,
                                  detail=f"Span not verbatim in {cit.citation}: \"{cit.span[:50]}\".")
    return GuardrailCheck(name="citation_fidelity", passed=True)


def _find_chunk(cit: Citation) -> dict | None:
    for c in data_loader.load_corpus():
        if c.get("section") == cit.section and c.get("citation") == cit.citation:
            return c
    return None


# Domains whose "answered" determinations MUST be grounded in a citation.
_GROUNDING_REQUIRED = {"fmla", "flsa_minwage", "flsa_overtime"}


def check_grounding(det: GroundedDetermination, domain: str) -> GuardrailCheck:
    """An answered determination in a law/computed domain must carry >= 1 citation.

    This closes the 'answered but ungrounded' hole that citation-fidelity (which only
    checks the citations that exist) can't catch on its own.
    """
    if det.status == "answered" and domain in _GROUNDING_REQUIRED and not det.citations:
        return GuardrailCheck(name="grounding", passed=False,
                              detail="Answered determination carries no citation.")
    return GuardrailCheck(name="grounding", passed=True)


def detect_conflict(retrieved: list[dict], domain: str) -> ConflictFlag | None:
    """Policy clause below the FMLA legal floor -> conflict (defer to law)."""
    if domain != "fmla":
        return None
    for c in retrieved:
        if c.get("doc_type") != "policy":
            continue
        m = re.search(r"(\d+)\s*weeks", c.get("text", "").lower())
        if m and int(m.group(1)) < config.FMLA_ENTITLEMENT_WEEKS:
            return ConflictFlag(
                policy_cite=c["citation"],
                law_cite="29 CFR §825.200",
                policy_value=f"{m.group(1)} weeks",
                law_floor="12 workweeks",
                resolution=(
                    "FMLA is a federal floor an employer cannot reduce; the 12-workweek "
                    "entitlement controls over the lower handbook cap."
                ),
            )
    return None
