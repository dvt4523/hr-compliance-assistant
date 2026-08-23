"""Case log is append-only and idempotent (double-resume can't double-log)."""
from src import config
from src.tools.caselog import append_case_log


def test_append_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CASE_LOG_FILE", tmp_path / "case_log.jsonl")
    first = append_case_log("E001", 0, "Eligible for 12 weeks.", {"choice": "approve"})
    assert first["logged"] is True

    dup = append_case_log("E001", 0, "Eligible for 12 weeks.", {"choice": "approve"})
    assert dup["logged"] is False and dup["reason"] == "duplicate"

    # a different turn is a distinct entry
    other = append_case_log("E001", 1, "Eligible for 12 weeks.", {"choice": "approve"})
    assert other["logged"] is True

    lines = (tmp_path / "case_log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
