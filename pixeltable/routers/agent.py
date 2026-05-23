"""Agent chat endpoint with RAG context retrieval."""

from __future__ import annotations

import uuid

import openai
import pixeltable as pxt
from fastapi import APIRouter

import config
from api_contract import AgentRequest, AgentResponse

router = APIRouter()

_client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

SYSTEM_PROMPT = (
    'You are a helpful knowledge-base assistant. '
    'Answer the user\'s question using ONLY the provided context. '
    'Cite the source document for each fact. '
    'If the context is insufficient, say so.'
)


@router.post('/agent/query', response_model=AgentResponse)
def agent_query(req: AgentRequest) -> AgentResponse:
    conversation_id = req.conversation_id or str(uuid.uuid4())

    # Retrieve relevant context via similarity search
    docs = pxt.get_table('kb.documents')
    sim = docs.embed_text.similarity(string=req.message)
    hits = (
        docs.order_by(sim, asc=False)
        .limit(5)
        .select(docs.text, docs.source, docs.modality, docs.description, score=sim)
        .collect()
        .to_dicts()
    )

    context_parts: list[str] = []
    sources: list[str] = []
    for h in hits:
        content = h['text'] if h['modality'] == 'text' else (h['description'] or '')
        context_parts.append(f'[{h["source"]}]: {content}')
        if h['source'] not in sources:
            sources.append(h['source'])

    context_block = '\n\n'.join(context_parts)

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'Context:\n{context_block}\n\nQuestion: {req.message}'},
    ]

    response = _client.chat.completions.create(model=config.CHAT_MODEL, messages=messages)
    answer = response.choices[0].message.content or ''

    # Persist the exchange
    convos = pxt.get_table('kb.conversations')
    convos.insert([
        {'message': req.message, 'role': 'user', 'conversation_id': conversation_id},
        {'message': answer, 'role': 'assistant', 'conversation_id': conversation_id},
    ])

    return AgentResponse(answer=answer, sources=sources, conversation_id=conversation_id)
