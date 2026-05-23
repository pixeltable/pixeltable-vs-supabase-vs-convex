"""RAG agent endpoint running on Modal.

Architecture for a single /agent/query call:

  Client request
    -> Modal container (compute)
      -> OpenAI Embeddings API  (embed the question  — external service #1)
      -> Supabase RPC           (retrieve context     — external service #2)
      -> OpenAI Chat API        (generate answer      — external service #1)
    <- Response

Three external API calls for one agent turn.  Modal orchestrates the
calls but stores nothing and caches nothing — it's pure compute glue.
"""

from __future__ import annotations

import uuid
from typing import Literal

import modal
from pydantic import BaseModel, Field

from app import app, get_openai_client, get_supabase_client, image, secrets

EMBEDDING_MODEL = 'text-embedding-3-small'
CHAT_MODEL = 'gpt-4o-mini'
CONTEXT_LIMIT = 5


# ---------------------------------------------------------------------------
# Pydantic models matching the shared API contract
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    message: str = Field(..., description='User message')
    conversation_id: str | None = Field(None, description='Thread ID for multi-turn')


class AgentResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list, description='Source documents used')
    conversation_id: str | None = None


# ---------------------------------------------------------------------------
# POST /agent/query
# ---------------------------------------------------------------------------

@app.function(image=image, secrets=[secrets])
@modal.fastapi_endpoint(method='POST')
def agent_query(request: AgentRequest) -> AgentResponse:
    """POST /agent/query — RAG agent chat.

    This is the most complex endpoint, requiring three sequential
    external service calls from the Modal container:

    Step 1: Embed the user's question via OpenAI Embeddings
      - Modal container -> OpenAI API (network hop #1)

    Step 2: Retrieve relevant context from Supabase pgvector
      - Modal container -> Supabase Postgres (network hop #2)
      - Modal has no local vector index; must query over the wire.

    Step 3: Generate answer via OpenAI Chat with retrieved context
      - Modal container -> OpenAI API (network hop #3)

    Total: 3 network round-trips, 2 external services, 0 local state.
    A platform with built-in RAG (Pixeltable) does steps 1-2 as a
    single in-process operation.
    """
    conversation_id = request.conversation_id or str(uuid.uuid4())

    # --- Step 1: Embed the query via OpenAI (external service #1, call #1) ---
    openai_client = get_openai_client()
    embed_response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=request.message)
    query_embedding = embed_response.data[0].embedding

    # --- Step 2: Retrieve context from Supabase (external service #2) ---
    # Modal has no storage — context retrieval is a network call to Postgres.
    db = get_supabase_client()
    search_result = db.rpc(
        'search_documents',
        {'query_embedding': query_embedding, 'match_count': CONTEXT_LIMIT},
    ).execute()

    context_chunks: list[str] = []
    sources: list[str] = []
    for row in search_result.data:
        context_chunks.append(row['content'])
        if row['source'] not in sources:
            sources.append(row['source'])

    context_text = '\n\n---\n\n'.join(context_chunks) if context_chunks else 'No relevant documents found.'

    # --- Step 3: Generate answer via OpenAI Chat (external service #1, call #2) ---
    system_prompt = (
        'You are a helpful knowledge-base assistant. Answer the user\'s question '
        'based on the provided context. If the context doesn\'t contain enough '
        'information, say so. Cite your sources.\n\n'
        f'Context:\n{context_text}'
    )

    chat_response = openai_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': request.message},
        ],
        max_tokens=1024,
    )

    answer = chat_response.choices[0].message.content or 'I could not generate an answer.'

    return AgentResponse(
        answer=answer,
        sources=sources,
        conversation_id=conversation_id,
    )
