"""Shared API contract for all platform implementations.

Every implementation (Pixeltable, Supabase, Convex, Modal) must expose HTTP
endpoints that accept and return these models. The equivalence test harness
validates all four against this contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# -- Requests --


class UploadRequest(BaseModel):
    """Upload a text document or image to the knowledge base."""

    content: str | None = Field(None, description='Text content of the document')
    image_url: str | None = Field(None, description='URL of an image to index')
    source: str = Field(..., description='Source filename or identifier')
    metadata: dict = Field(default_factory=dict, description='Arbitrary metadata')


class SearchRequest(BaseModel):
    """Semantic search across the knowledge base."""

    query: str = Field(..., description='Natural-language search query')
    limit: int = Field(10, ge=1, le=100, description='Max results to return')


class AgentRequest(BaseModel):
    """Send a message to the knowledge-base agent."""

    message: str = Field(..., description='User message')
    conversation_id: str | None = Field(None, description='Thread ID for multi-turn')


# -- Responses --


class DocumentInfo(BaseModel):
    """Summary of an ingested document."""

    id: str
    source: str
    modality: Literal['text', 'image']
    created_at: str | None = None


class SearchResult(BaseModel):
    """A single search hit."""

    content: str = Field(..., description='Matching text or image description')
    source: str = Field(..., description='Source filename')
    similarity: float = Field(..., ge=0, le=1, description='Cosine similarity score')
    modality: Literal['text', 'image']


class SearchResponse(BaseModel):
    """Response from the /search endpoint."""

    results: list[SearchResult]
    query: str


class AgentResponse(BaseModel):
    """Response from the /agent/query endpoint."""

    answer: str
    sources: list[str] = Field(default_factory=list, description='Source documents used')
    conversation_id: str | None = None


class UploadResponse(BaseModel):
    """Response from the /upload endpoint."""

    id: str
    source: str
    modality: Literal['text', 'image']


class DocumentsResponse(BaseModel):
    """Response from GET /documents."""

    documents: list[DocumentInfo]
    total: int


# -- Endpoint contract summary --
#
# POST /upload          UploadRequest   -> UploadResponse
# POST /search          SearchRequest   -> SearchResponse
# POST /agent/query     AgentRequest    -> AgentResponse
# GET  /documents                       -> DocumentsResponse
