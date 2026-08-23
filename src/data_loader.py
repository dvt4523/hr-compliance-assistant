"""Load the committed offline corpus + structured DB. No runtime network access.

Merges legal/*.json + policy/*.json into one flat chunk list (lab08-style), and
exposes the employee, site, and state-rule tables the deterministic tools read.
"""
from __future__ import annotations

import glob
import json
from functools import lru_cache

from . import config


def _load(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_corpus() -> list[dict]:
    """Flat list of all law + policy chunks (each carries doc_type/domain/etc.)."""
    chunks: list[dict] = []
    for pattern in (str(config.LEGAL_DIR / "*.json"), str(config.POLICY_DIR / "*.json")):
        for path in sorted(glob.glob(pattern)):
            data = _load(path)
            chunks.extend(data.get("chunks", []))
    return chunks


@lru_cache(maxsize=1)
def load_employees() -> dict[str, dict]:
    """employee_id -> record."""
    data = _load(config.EMPLOYEES_FILE)
    return {e["employee_id"]: e for e in data["employees"]}


@lru_cache(maxsize=1)
def load_sites() -> dict[str, dict]:
    """site_id -> record."""
    data = _load(config.SITES_FILE)
    return {s["site_id"]: s for s in data["sites"]}


@lru_cache(maxsize=1)
def load_state_rules() -> dict[str, dict]:
    """jurisdiction code (US/CA/TX) -> params."""
    return _load(config.STATE_RULES_FILE)["jurisdictions"]


def get_chunks_by_citation(citations: list[str]) -> list[dict]:
    """Return corpus chunks whose `citation` is in the given list (order follows `citations`).

    Used to inject a computed determination's own governing law chunks into the
    drafter's context, so the deciding rule is always available to cite.
    """
    by_cite: dict[str, dict] = {}
    for c in load_corpus():
        by_cite.setdefault(c.get("citation", ""), c)
    seen, out = set(), []
    for cite in citations:
        chunk = by_cite.get(cite)
        if chunk and chunk["id"] not in seen:
            seen.add(chunk["id"])
            out.append(chunk)
    return out


def site_for_employee(employee: dict) -> dict:
    """Join an employee to their worksite via site_id."""
    return load_sites()[employee["site_id"]]


def state_rules_for(jurisdiction: str) -> dict:
    """State params with the US federal floor always available as a fallback."""
    rules = load_state_rules()
    return rules.get(jurisdiction, rules["US"])
