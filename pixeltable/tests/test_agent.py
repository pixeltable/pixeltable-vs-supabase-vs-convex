"""Integration tests for the /agent/query endpoint."""

import pytest
import httpx


pytestmark = pytest.mark.integration


def test_agent_responds_with_answer(base_url: str, sample_document: dict) -> None:
    httpx.post(f'{base_url}/upload', json=sample_document)
    r = httpx.post(
        f'{base_url}/agent/query',
        json={'message': 'What does Pixeltable do?'},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body['answer']) > 0
    assert 'conversation_id' in body


def test_agent_returns_sources(base_url: str, sample_document: dict) -> None:
    httpx.post(f'{base_url}/upload', json=sample_document)
    r = httpx.post(
        f'{base_url}/agent/query',
        json={'message': 'Tell me about data orchestration'},
    )
    body = r.json()
    assert isinstance(body['sources'], list)
    assert len(body['sources']) >= 1


def test_agent_preserves_conversation_id(base_url: str, sample_document: dict) -> None:
    httpx.post(f'{base_url}/upload', json=sample_document)
    r1 = httpx.post(
        f'{base_url}/agent/query',
        json={'message': 'Hello', 'conversation_id': 'test-conv-1'},
    )
    assert r1.json()['conversation_id'] == 'test-conv-1'
