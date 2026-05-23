"""Search and document listing endpoints running on Modal.

Architecture for a single /search call:

  Client request
    -> Modal container (compute)
      -> OpenAI Embeddings API  (embed the query — external service #1)
      -> Supabase RPC           (pgvector search — external service #2)
    <- Response

Architecture for GET /documents:

  Client request
    -> Modal container (compute)
      -> Supabase query         (external service #2)
    <- Response

Every read path goes through two network hops.  Modal contributes
the container runtime; the data lives entirely elsewhere.
"""

from __future__ import annotations

from typing import Literal

import modal
from pydantic import BaseModel, Field

from app import app, get_openai_client, get_supabase_client, image, secrets

EMBEDDING_MODEL = 'text-embedding-3-small'


# ---------------------------------------------------------------------------
# Pydantic models matching the shared API contract
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str = Field(..., description='Natural-language search query')
    limit: int = Field(10, ge=1, le=100, description='Max results to return')


class SearchResult(BaseModel):
    content: str
    source: str
    similarity: float
    modality: Literal['text', 'image']


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str


class DocumentInfo(BaseModel):
    id: str
    source: str
    modality: Literal['text', 'image']
    created_at: str | None = None


class DocumentsResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------

@app.function(image=image, secrets=[secrets])
@modal.fastapi_endpoint(method='POST')
def search(request: SearchRequest) -> SearchResponse:
    """POST /search — Semantic search across the knowledge base.

    Step 1: Embed the query via OpenAI (external service #1)
      - Modal container -> OpenAI Embeddings API over the network.

    Step 2: Query Supabase pgvector via RPC (external service #2)
      - Modal container -> Supabase Postgres over the network.
      - Uses the search_documents() stored procedure defined in schema.sql.

    Two network round-trips for every search.  Platforms with built-in
    vector search (Pixeltable, Convex) do this in-process.
    """
    # --- Step 1: Embed query via OpenAI (external service #1) ---
    openai_client = get_openai_client()
    embed_response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=request.query)
    query_embedding = embed_response.data[0].embedding

    # --- Step 2: Search via Supabase RPC (external service #2) ---
    # Modal has no query engine — delegate to Postgres.
    db = get_supabase_client()
    result = db.rpc(
        'search_documents',
        {'query_embedding': query_embedding, 'match_count': request.limit},
    ).execute()

    results = [
        SearchResult(
            content=row['content'],
            source=row['source'],
            similarity=row['similarity'],
            modality=row['modality'],
        )
        for row in result.data
    ]

    return SearchResponse(results=results, query=request.query)


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------

@app.function(image=image, secrets=[secrets])
@modal.fastapi_endpoint(method='GET')
def documents() -> DocumentsResponse:
    """GET /documents — List all documents in the knowledge base.

    Even a simple "list all rows" query must leave the Modal container
    and round-trip to Supabase over the network.
    """
    # --- Query Supabase (external service #2) ---
    db = get_supabase_client()
    result = (
        db.table('documents')
        .select('id, source, modality, created_at')
        .order('created_at', desc=True)
        .execute()
    )

    docs = [
        DocumentInfo(
            id=row['id'],
            source=row['source'],
            modality=row['modality'],
            created_at=row.get('created_at'),
        )
        for row in result.data
    ]

    return DocumentsResponse(documents=docs, total=len(docs))
