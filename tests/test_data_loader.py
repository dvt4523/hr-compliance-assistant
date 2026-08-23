"""Data layer loads and cross-links as expected."""
from src import data_loader


def test_corpus_size_and_types():
    corpus = data_loader.load_corpus()
    assert len(corpus) == 36  # 16 law + 20 policy
    law = [c for c in corpus if c["doc_type"] == "law"]
    policy = [c for c in corpus if c["doc_type"] == "policy"]
    assert len(law) == 16 and len(policy) == 20
    # law chunks carry a verifiable anchor; policy chunks do not
    assert all("verbatim_anchor" in c and "url" in c for c in law)
    assert all("verbatim_anchor" not in c for c in policy)


def test_employees_and_sites():
    emps = data_loader.load_employees()
    sites = data_loader.load_sites()
    assert set(emps) == {"E001", "E002", "E003", "E004", "E005", "E006"}
    assert set(sites) == {"NW-HQ-TX", "NW-OFF-CA", "NW-PROJ-TX"}
    # every employee links to a real site
    for e in emps.values():
        assert e["site_id"] in sites


def test_state_rules_present():
    rules = data_loader.load_state_rules()
    assert set(rules) >= {"US", "CA", "TX"}
    assert rules["US"]["min_wage"] == 7.25
    assert rules["CA"]["min_wage"] == 16.90
    assert rules["CA"]["exempt_salary_threshold_annual"] == 70304
