"""Embedding and vision functions running on Modal compute.

This module handles two external API calls that Modal must orchestrate:
  1. OpenAI Embeddings API  — text -> vector(1536)
  2. OpenAI Vision API      — image -> text description -> vector(1536)

Neither of these is built-in; Modal provides the container, you provide
the API wiring.  Compare with Pixeltable where embedding is a one-liner
computed column.
"""

from __future__ import annotations

import modal

from app import app, get_openai_client, image, secrets

EMBEDDING_MODEL = 'text-embedding-3-small'
VISION_MODEL = 'gpt-4o-mini'


@app.cls(image=image, secrets=[secrets])
class Embeddings:
    """Modal class wrapping OpenAI embedding and vision calls.

    Every method here is a network round-trip from a Modal container to
    the OpenAI API — latency you don't pay on platforms with built-in
    embedding support.
    """

    @modal.method()
    def embed_text(self, text: str) -> list[float]:
        """Embed text via OpenAI Embeddings API.

        Modal compute -> OpenAI API (external service #1).
        """
        client = get_openai_client()
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
        return response.data[0].embedding

    @modal.method()
    def describe_image(self, image_url: str) -> str:
        """Generate a text description of an image via OpenAI Vision.

        Modal compute -> OpenAI Vision API (external service #1).
        """
        client = get_openai_client()
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': 'Describe this image in detail for search indexing.'},
                        {'type': 'image_url', 'image_url': {'url': image_url}},
                    ],
                }
            ],
            max_tokens=300,
        )
        return response.choices[0].message.content or ''

    @modal.method()
    def embed(self, *, content: str | None = None, image_url: str | None = None) -> tuple[str, list[float]]:
        """Embed either text content or an image URL.

        Returns (text_to_store, embedding_vector).

        For images this is a two-step pipeline:
          Modal -> OpenAI Vision -> get description -> OpenAI Embeddings -> get vector
        Two external API calls just to ingest one image.
        """
        if image_url:
            description = self.describe_image.local(image_url)
            embedding = self.embed_text.local(description)
            return description, embedding
        elif content:
            embedding = self.embed_text.local(content)
            return content, embedding
        else:
            raise ValueError('Either content or image_url must be provided')
