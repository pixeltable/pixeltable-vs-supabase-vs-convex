"""UDFs and query functions for the knowledge-base app."""

from __future__ import annotations

import pixeltable as pxt


@pxt.udf
def web_search(query: str, num_results: int = 3) -> list[dict]:
    """Search the web with DuckDuckGo and return the top results."""
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        return [r for r in ddgs.text(query, max_results=num_results)]


@pxt.query
def search_documents(query_text: str, limit: int = 5):
    """Semantic similarity search over the knowledge base."""
    docs = pxt.get_table('kb.documents')
    sim = docs.embed_text.similarity(string=query_text)
    return (
        docs.order_by(sim, asc=False)
        .limit(limit)
        .select(docs.text, docs.source, docs.modality, docs.description, score=sim)
    )
