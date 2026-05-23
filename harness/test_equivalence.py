"""Cross-platform equivalence tests.

Validates that all four implementations return comparable results for the same
queries. Requires at least one implementation to be running and seeded with the
shared fixture data.

Usage:
    pytest harness/test_equivalence.py --base-url http://localhost:8000
    pytest harness/test_equivalence.py --base-url http://localhost:8000 --base-url http://localhost:8001
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures'
QUERIES = json.loads((FIXTURES / 'queries' / 'test_queries.json').read_text())


def pytest_addoption(parser):
    parser.addoption(
        '--base-url',
        action='append',
        default=[],
        help='Base URL(s) of running implementations to test against',
    )


@pytest.fixture(params=lambda request: request.config.getoption('--base-url') or ['http://localhost:8000'])
def base_url(request):
    return request.param


@pytest.fixture
def client(base_url):
    return httpx.Client(base_url=base_url, timeout=30.0)


class TestUploadContract:
    """All implementations must accept the same upload payloads."""

    def test_upload_text_document(self, client: httpx.Client):
        response = client.post('/upload', json={
            'content': 'Test document for equivalence checking.',
            'source': 'equivalence-test.txt',
            'metadata': {'test': True},
        })
        assert response.status_code == 200
        data = response.json()
        assert 'id' in data
        assert data['source'] == 'equivalence-test.txt'
        assert data['modality'] == 'text'

    def test_upload_image(self, client: httpx.Client):
        image_url = 'https://raw.githubusercontent.com/pixeltable/pixeltable/release/docs/resources/images/000000000001.jpg'
        response = client.post('/upload', json={
            'image_url': image_url,
            'source': 'equivalence-test-image.jpg',
        })
        assert response.status_code == 200
        data = response.json()
        assert data['modality'] == 'image'


class TestSearchContract:
    """All implementations must return the same response shape for search."""

    def test_search_returns_results(self, client: httpx.Client):
        response = client.post('/search', json={'query': 'embedding and indexing', 'limit': 5})
        assert response.status_code == 200
        data = response.json()
        assert 'results' in data
        assert 'query' in data
        assert isinstance(data['results'], list)

    def test_search_result_shape(self, client: httpx.Client):
        response = client.post('/search', json={'query': 'GPU computing cost', 'limit': 3})
        data = response.json()
        for result in data['results']:
            assert 'content' in result
            assert 'source' in result
            assert 'similarity' in result
            assert 'modality' in result
            assert result['modality'] in ('text', 'image')
            assert 0 <= result['similarity'] <= 1

    @pytest.mark.parametrize('q', QUERIES, ids=[q['id'] for q in QUERIES])
    def test_fixture_queries_return_relevant_results(self, client: httpx.Client, q: dict):
        response = client.post('/search', json={'query': q['query'], 'limit': 5})
        assert response.status_code == 200
        data = response.json()
        assert len(data['results']) > 0, f'Query {q["id"]!r} returned no results'


class TestAgentContract:
    """All implementations must accept agent queries and return grounded answers."""

    def test_agent_returns_answer(self, client: httpx.Client):
        response = client.post('/agent/query', json={
            'message': 'How does automatic embedding work?',
        })
        assert response.status_code == 200
        data = response.json()
        assert 'answer' in data
        assert len(data['answer']) > 0
        assert 'sources' in data

    def test_agent_with_conversation_id(self, client: httpx.Client):
        response = client.post('/agent/query', json={
            'message': 'What is RAG?',
            'conversation_id': 'test-conv-001',
        })
        data = response.json()
        assert data.get('conversation_id') is not None


class TestDocumentsContract:
    """All implementations must list uploaded documents."""

    def test_list_documents(self, client: httpx.Client):
        response = client.get('/documents')
        assert response.status_code == 200
        data = response.json()
        assert 'documents' in data
        assert 'total' in data
        assert isinstance(data['documents'], list)
