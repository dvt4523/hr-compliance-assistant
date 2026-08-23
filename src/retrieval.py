"""Rerank-free retrieval (Siraya has no embeddings / no rerank vendor).

Pipeline (lab08 LLM-reranker path only):
  keyword_prefilter  -> LLM rerank -> drop_superseded -> relevance gate -> top-k

keyword_prefilter and drop_superseded are pure (unit-tested without any LLM);
rerank is the one LLM step.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from . import config
from .llm import LLMClient
from .schemas import RerankScore

_TOKEN = re.compile(r"[a-z0-9.\-/§]+")


class _RerankResult(BaseModel):
    scores: list[RerankScore]


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def keyword_prefilter(query: str, chunks: list[dict], domain: str | None = None,
                      k: int = config.PREFILTER_K) -> list[dict]:
    """Cheap lexical overlap over section id + title + text; small domain boost."""
    q = _tokenize(query)
    scored = []
    for c in chunks:
        toks = _tokenize(f"{c.get('section','')} {c.get('title','')} {c.get('text','')}")
        overlap = len(q & toks)
        if domain and c.get("domain") == domain:
            overlap += 1  # soft boost, not a hard filter
        if overlap > 0:
            scored.append((overlap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


def drop_superseded(chunks: list[dict], as_of: str = config.TODAY) -> list[dict]:
    """Per section, keep only the newest revision effective on/before as_of."""
    best: dict[str, dict] = {}
    for c in chunks:
        if c.get("effective", "0000-00-00") > as_of:
            continue
        sec = c.get("section", c.get("id"))
        cur = best.get(sec)
        if cur is None or c.get("effective", "") > cur.get("effective", ""):
            best[sec] = c
    return list(best.values())


def rerank(llm: LLMClient, query: str, candidates: list[dict]) -> list[tuple[float, dict]]:
    """LLM scores each candidate 0..1; return (score, chunk) sorted best-first."""
    if not candidates:
        return []
    listing = "\n".join(
        f"[{i}] {c.get('citation', c.get('section',''))}: {c.get('text','')}"
        for i, c in enumerate(candidates)
    )
    result = llm.generate_json(
        prompt=(
            f"Question: {query}\n\n"
            "Score each passage from 0.0 (irrelevant) to 1.0 (directly answers the "
            f"question). Return one score per passage id.\n{listing}"
        ),
        schema=_RerankResult,
        model=config.RERANK_MODEL,
        system="You are a senior retrieval reranker. Judge only whether each passage answers the question.",
    )
    by_id = {s.id: s.relevance for s in result.scores}
    ranked = [(by_id.get(i, 0.0), c) for i, c in enumerate(candidates)]
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def retrieve(llm: LLMClient, query: str, chunks: list[dict], domain: str | None = None,
             k: int = config.RETRIEVE_K) -> tuple[list[dict], float]:
    """Full pipeline. Returns (top-k chunks, top relevance). Empty list => abstain."""
    candidates = keyword_prefilter(query, chunks, domain)
    candidates = drop_superseded(candidates)
    ranked = rerank(llm, query, candidates)
    if not ranked or ranked[0][0] < config.RELEVANCE_BAR:
        return [], (ranked[0][0] if ranked else 0.0)
    top = [c for _, c in ranked[:k]]
    return top, ranked[0][0]
