"""Semantic search endpoint."""

from __future__ import annotations

import pixeltable as pxt
from fastapi import APIRouter

from api_contract import SearchRequest, SearchResponse, SearchResult

router = APIRouter()


@router.post('/search', response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    docs = pxt.get_table('kb.documents')
    sim = docs.embed_text.similarity(string=req.query)
    rows = (
        docs.order_by(sim, asc=False)
        .limit(req.limit)
        .select(docs.text, docs.source, docs.modality, docs.description, score=sim)
        .collect()
    )
    results = [
        SearchResult(
            content=r['text'] if r['modality'] == 'text' else (r['description'] or ''),
            source=r['source'],
            similarity=float(r['score']),
            modality=r['modality'],
        )
        for r in rows.to_dicts()
    ]
    return SearchResponse(results=results, query=req.query)
