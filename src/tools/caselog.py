"""Case log — episodic memory. The ONLY write tool; reachable only from finalize,
after HITL approval. Append-only JSONL with an idempotency key so a double-resume
cannot double-log (Week 7: idempotency protects the real-world effect).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .. import config


def _idempotency_key(employee_id: str, turn: int, determination: str) -> str:
    h = hashlib.sha256(f"{employee_id}|{turn}|{determination}".encode()).hexdigest()
    return h[:16]


def _existing_keys() -> set[str]:
    if not config.CASE_LOG_FILE.exists():
        return set()
    keys = set()
    with open(config.CASE_LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                keys.add(json.loads(line).get("idempotency_key"))
    return keys


def append_case_log(employee_id: str, turn: int, determination: str,
                    decision: dict, evidence: dict | None = None) -> dict:
    """Append one audited case record. Idempotent on (employee_id, turn, determination)."""
    key = _idempotency_key(employee_id, turn, determination)
    if key in _existing_keys():
        return {"logged": False, "reason": "duplicate", "idempotency_key": key}

    record = {
        "idempotency_key": key,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "employee_id": employee_id,
        "turn": turn,
        "determination": determination,
        "decision": decision,          # HumanDecision incl. reviewer/timestamp (audit trail)
        "evidence": evidence or {},
    }
    config.CASE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.CASE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return {"logged": True, "idempotency_key": key}
