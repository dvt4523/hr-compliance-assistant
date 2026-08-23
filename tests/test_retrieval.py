"""Pure retrieval steps (no LLM): keyword prefilter + stale-revision filter."""
from src import data_loader
from src.retrieval import drop_superseded, keyword_prefilter


def test_drop_superseded_keeps_current_lv42():
    corpus = data_loader.load_corpus()
    lv42 = [c for c in corpus if c["section"] == "LV-4.2"]
    assert len(lv42) == 2  # 2024-06 (6wk) superseded + 2026-01 (8wk) current
    kept = drop_superseded(lv42, as_of="2026-08-23")
    assert len(kept) == 1
    assert kept[0]["revision"] == "2026-01"
    assert "8 weeks" in kept[0]["text"]


def test_drop_superseded_ignores_future_effective():
    chunks = [
        {"section": "X", "effective": "2030-01-01", "revision": "future", "text": "a"},
        {"section": "X", "effective": "2020-01-01", "revision": "old", "text": "b"},
    ]
    kept = drop_superseded(chunks, as_of="2026-08-23")
    assert len(kept) == 1 and kept[0]["revision"] == "old"


def test_keyword_prefilter_finds_worksite_rule():
    corpus = data_loader.load_corpus()
    hits = keyword_prefilter("how many employees within 75 miles of the worksite", corpus)
    assert any(c["section"] == "825.110(a)(3)" for c in hits)


def test_keyword_prefilter_finds_section_by_id():
    corpus = data_loader.load_corpus()
    hits = keyword_prefilter("what does LV-4.2 say", corpus)
    assert any(c["section"] == "LV-4.2" for c in hits)
