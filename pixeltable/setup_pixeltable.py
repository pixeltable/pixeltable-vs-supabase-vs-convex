"""Schema definition for the knowledge-base tables.

Running this module (or calling ``init()``) is idempotent — every operation
uses ``if_exists='ignore'`` so it safely no-ops on subsequent runs.
"""

from typing import Optional

import pixeltable as pxt
from pixeltable.functions.openai import chat_completions, embeddings

import config  # noqa: F401 — ensures env vars are loaded

EMBEDDING_FN = embeddings.using(model=config.EMBEDDING_MODEL)


@pxt.udf
def pick_embed_text(modality: str, text: Optional[str], description: Optional[str]) -> str:
    """Return text content for text docs, or the AI-generated description for images."""
    if modality == 'text':
        return text or ''
    return description or ''


def init() -> None:
    pxt.create_dir('kb', if_exists='ignore')

    # -- documents table --
    docs = pxt.create_table(
        'kb.documents',
        {
            'text': pxt.String,
            'source': pxt.String,
            'modality': pxt.String,
            'metadata': pxt.Json,
            'image': pxt.Image,
        },
        if_exists='ignore',
    )

    # For images: auto-generate a text description via GPT-4o-mini
    docs.add_computed_column(
        description=chat_completions(
            messages=[
                {'role': 'system', 'content': 'Describe this image in detail.'},
                {
                    'role': 'user',
                    'content': [{'type': 'image_url', 'image_url': {'url': docs.image}}],
                },
            ],
            model=config.CHAT_MODEL,
        ).choices[0].message.content,
        if_exists='ignore',
    )

    # Embed text for text docs, or the generated description for images
    docs.add_computed_column(
        embed_text=pick_embed_text(docs.modality, docs.text, docs.description),
        if_exists='ignore',
    )

    docs.add_embedding_index(
        'embed_text',
        idx_name='embed_idx',
        embedding=EMBEDDING_FN,
        if_exists='ignore',
    )

    # -- conversations table --
    pxt.create_table(
        'kb.conversations',
        {
            'message': pxt.String,
            'role': pxt.String,
            'conversation_id': pxt.String,
        },
        if_exists='ignore',
    )


if __name__ == '__main__':
    init()
