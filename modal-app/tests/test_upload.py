"""Integration tests for POST /upload on the Modal deployment.

Each test validates that the three-service chain works:
  Modal container -> OpenAI API -> Supabase pgvector
"""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(scope='session')
def http_client() -> httpx.Client:
    return httpx.Client(timeout=60.0)


class TestUpload:
    """Test document upload via Modal web endpoint."""

    def test_upload_text_document(self, http_client: httpx.Client, upload_url: str) -> None:
        """Upload a text document and verify the response matches the API contract."""
        response = http_client.post(
            upload_url,
            json={
                'content': 'Modal is a serverless compute platform for data and ML teams.',
                'source': 'test-modal-overview.txt',
                'metadata': {'category': 'documentation'},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert 'id' in data
        assert data['source'] == 'test-modal-overview.txt'
        assert data['modality'] == 'text'

    def test_upload_image_document(self, http_client: httpx.Client, upload_url: str) -> None:
        """Upload an image URL — this triggers the two-step Vision + Embedding pipeline."""
        response = http_client.post(
            upload_url,
            json={
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/1200px-Cat03.jpg',
                'source': 'test-cat-image.jpg',
                'metadata': {'category': 'test-image'},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert 'id' in data
        assert data['source'] == 'test-cat-image.jpg'
        assert data['modality'] == 'image'

    def test_upload_rejects_empty_request(self, http_client: httpx.Client, upload_url: str) -> None:
        """Reject uploads with neither content nor image_url."""
        response = http_client.post(
            upload_url,
            json={'source': 'empty.txt'},
        )
        assert response.status_code in (400, 422)

    def test_upload_returns_valid_uuid(self, http_client: httpx.Client, upload_url: str) -> None:
        """Verify the returned ID is a valid UUID from Supabase."""
        response = http_client.post(
            upload_url,
            json={
                'content': 'Testing UUID generation in the Modal -> Supabase pipeline.',
                'source': 'test-uuid-check.txt',
            },
        )
        assert response.status_code == 200
        data = response.json()
        import uuid

        uuid.UUID(data['id'])  # raises ValueError if not a valid UUID
