"""search_policy read tool — the retrieval capability, exposed as a tool.

This is where RAG and Tool-Use overlap (retrieval IS a read tool). Thin wrapper
over retrieval.retrieve against the committed corpus.
"""
from __future__ import annotations

from .. import data_loader, retrieval
from ..llm import LLMClient


def search_policy(llm: LLMClient, query: str, domain: str | None = None, k: int = 4):
    """Return (top chunks, top_relevance) from the offline policy+law corpus."""
    corpus = data_loader.load_corpus()
    return retrieval.retrieve(llm, query, corpus, domain=domain, k=k)
