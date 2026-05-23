"""Integration tests for POST /search and GET /documents on the Modal deployment.

Each test validates the two-service search chain:
  Modal container -> OpenAI Embeddings -> Supabase pgvector RPC
"""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(scope='session')
def http_client() -> httpx.Client:
    return httpx.Client(timeout=60.0)


@pytest.fixture(scope='session', autouse=True)
def seed_data(http_client: httpx.Client, upload_url: str) -> None:
    """Seed the knowledge base with test documents before running search tests."""
    docs = [
        {
            'content': 'Modal provides serverless GPU and CPU compute for ML workloads.',
            'source': 'search-test-modal.txt',
        },
        {
            'content': 'Pixeltable is a declarative data infrastructure for multimodal AI.',
            'source': 'search-test-pixeltable.txt',
        },
        {
            'content': 'Supabase is an open-source Firebase alternative with a Postgres database.',
            'source': 'search-test-supabase.txt',
        },
    ]
    for doc in docs:
        response = http_client.post(upload_url, json=doc)
        assert response.status_code == 200, f'Failed to seed document: {doc["source"]}'


class TestSearch:
    """Test semantic search via Modal web endpoint."""

    def test_search_returns_results(self, http_client: httpx.Client, search_url: str) -> None:
        """Search for a term and verify results are returned."""
        response = http_client.post(
            search_url,
            json={'query': 'serverless compute platform', 'limit': 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert 'results' in data
        assert 'query' in data
        assert len(data['results']) > 0

    def test_search_result_structure(self, http_client: httpx.Client, search_url: str) -> None:
        """Verify each search result matches the API contract."""
        response = http_client.post(
            search_url,
            json={'query': 'database', 'limit': 3},
        )
        assert response.status_code == 200
        data = response.json()
        for result in data['results']:
            assert 'content' in result
            assert 'source' in result
            assert 'similarity' in result
            assert 'modality' in result
            assert 0 <= result['similarity'] <= 1
            assert result['modality'] in ('text', 'image')

    def test_search_respects_limit(self, http_client: httpx.Client, search_url: str) -> None:
        """Verify the limit parameter caps the number of results."""
        response = http_client.post(
            search_url,
            json={'query': 'data', 'limit': 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data['results']) <= 2

    def test_search_relevance_ordering(self, http_client: httpx.Client, search_url: str) -> None:
        """Results should be ordered by descending similarity."""
        response = http_client.post(
            search_url,
            json={'query': 'Modal serverless GPU compute', 'limit': 10},
        )
        assert response.status_code == 200
        data = response.json()
        similarities = [r['similarity'] for r in data['results']]
        assert similarities == sorted(similarities, reverse=True)


class TestDocuments:
    """Test document listing via Modal web endpoint."""

    def test_list_documents(self, http_client: httpx.Client, documents_url: str) -> None:
        """GET /documents should return all documents from Supabase."""
        response = http_client.get(documents_url)
        assert response.status_code == 200
        data = response.json()
        assert 'documents' in data
        assert 'total' in data
        assert data['total'] >= 3  # at least the seeded documents

    def test_document_structure(self, http_client: httpx.Client, documents_url: str) -> None:
        """Verify each document matches the API contract."""
        response = http_client.get(documents_url)
        assert response.status_code == 200
        data = response.json()
        for doc in data['documents']:
            assert 'id' in doc
            assert 'source' in doc
            assert 'modality' in doc
            assert doc['modality'] in ('text', 'image')
