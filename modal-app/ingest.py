"""Document ingestion endpoint running on Modal.

Architecture for a single /upload call:

  Client request
    -> Modal container (compute)
      -> OpenAI Vision API   (if image — external service #1)
      -> OpenAI Embeddings   (external service #1)
      -> Supabase pgvector   (external service #2 — INSERT)
    <- Response

Three services wired together for one upload.  Modal provides the
container; you provide and pay for everything else.
"""

from __future__ import annotations

from typing import Literal

import modal
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app import app, get_supabase_client, image, secrets
from embeddings import Embeddings


# ---------------------------------------------------------------------------
# Pydantic models matching the shared API contract
# ---------------------------------------------------------------------------

class UploadRequest(BaseModel):
    content: str | None = Field(None, description='Text content of the document')
    image_url: str | None = Field(None, description='URL of an image to index')
    source: str = Field(..., description='Source filename or identifier')
    metadata: dict = Field(default_factory=dict, description='Arbitrary metadata')


class UploadResponse(BaseModel):
    id: str
    source: str
    modality: Literal['text', 'image']


# ---------------------------------------------------------------------------
# Modal function with FastAPI endpoint
# ---------------------------------------------------------------------------

@app.function(image=image, secrets=[secrets])
@modal.fastapi_endpoint(method='POST')
def upload(request: UploadRequest) -> UploadResponse:
    """POST /upload — Ingest a document into the knowledge base.

    This single endpoint requires orchestrating two external services:

    Step 1: Call OpenAI (via Modal compute) to generate embedding
      - For images: Vision API -> description, then Embeddings API -> vector
      - For text: Embeddings API -> vector directly

    Step 2: Call Supabase (external DB) to store the document + vector
      - Modal has no database — every row goes over the network to Supabase

    Step 3: Return the response
    """
    if not request.content and not request.image_url:
        raise HTTPException(status_code=400, detail='Either content or image_url is required')

    # --- Step 1: Embed via OpenAI (external service #1) ---
    embedder = Embeddings()
    text_to_store, embedding = embedder.embed.local(
        content=request.content,
        image_url=request.image_url,
    )

    modality: Literal['text', 'image'] = 'image' if request.image_url else 'text'

    # --- Step 2: Insert into Supabase pgvector (external service #2) ---
    # Modal has no data layer, so this is a network call to an external Postgres.
    db = get_supabase_client()
    result = (
        db.table('documents')
        .insert({
            'content': text_to_store,
            'source': request.source,
            'modality': modality,
            'image_url': request.image_url,
            'metadata': request.metadata,
            'embedding': embedding,
        })
        .execute()
    )

    row = result.data[0]

    return UploadResponse(
        id=row['id'],
        source=row['source'],
        modality=row['modality'],
    )
