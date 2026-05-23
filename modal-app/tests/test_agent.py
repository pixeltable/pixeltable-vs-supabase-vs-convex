"""Integration tests for POST /agent/query on the Modal deployment.

Each test validates the three-service agent chain:
  Modal container -> OpenAI Embeddings -> Supabase RPC -> OpenAI Chat
"""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(scope='session')
def http_client() -> httpx.Client:
    return httpx.Client(timeout=120.0)


@pytest.fixture(scope='session', autouse=True)
def seed_data(http_client: httpx.Client, upload_url: str) -> None:
    """Seed the knowledge base with test documents before running agent tests."""
    docs = [
        {
            'content': (
                'Modal is a cloud platform that lets you run code in the cloud without managing infrastructure. '
                'It supports GPUs, scheduled jobs, and web endpoints.'
            ),
            'source': 'agent-test-modal.txt',
        },
        {
            'content': (
                'Pixeltable unifies data storage, versioning, and model orchestration in a single declarative '
                'framework. It eliminates the need for separate vector databases and ETL pipelines.'
            ),
            'source': 'agent-test-pixeltable.txt',
        },
    ]
    for doc in docs:
        response = http_client.post(upload_url, json=doc)
        assert response.status_code == 200, f'Failed to seed document: {doc["source"]}'


class TestAgent:
    """Test RAG agent via Modal web endpoint."""

    def test_agent_returns_answer(self, http_client: httpx.Client, agent_url: str) -> None:
        """Agent should return a non-empty answer with sources."""
        response = http_client.post(
            agent_url,
            json={'message': 'What is Modal and what can it do?'},
        )
        assert response.status_code == 200
        data = response.json()
        assert 'answer' in data
        assert len(data['answer']) > 0
        assert 'sources' in data
        assert 'conversation_id' in data

    def test_agent_response_structure(self, http_client: httpx.Client, agent_url: str) -> None:
        """Verify the response matches the API contract."""
        response = http_client.post(
            agent_url,
            json={'message': 'Compare Modal and Pixeltable.'},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data['answer'], str)
        assert isinstance(data['sources'], list)
        assert data['conversation_id'] is not None

    def test_agent_uses_context(self, http_client: httpx.Client, agent_url: str) -> None:
        """Agent should reference seeded documents in its answer."""
        response = http_client.post(
            agent_url,
            json={'message': 'What does Pixeltable unify?'},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data['sources']) > 0

    def test_agent_preserves_conversation_id(self, http_client: httpx.Client, agent_url: str) -> None:
        """When a conversation_id is provided, it should be returned."""
        conv_id = 'test-conversation-12345'
        response = http_client.post(
            agent_url,
            json={'message': 'Hello', 'conversation_id': conv_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data['conversation_id'] == conv_id

    def test_agent_generates_conversation_id(self, http_client: httpx.Client, agent_url: str) -> None:
        """When no conversation_id is provided, one should be generated."""
        response = http_client.post(
            agent_url,
            json={'message': 'Hello'},
        )
        assert response.status_code == 200
        data = response.json()
        assert data['conversation_id'] is not None
        import uuid

        uuid.UUID(data['conversation_id'])  # validates it's a proper UUID
