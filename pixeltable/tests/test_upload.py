"""Integration tests for the /upload endpoint."""

import pytest
import httpx


pytestmark = pytest.mark.integration


def test_upload_text_document(base_url: str, sample_document: dict) -> None:
    r = httpx.post(f'{base_url}/upload', json=sample_document)
    assert r.status_code == 200
    body = r.json()
    assert body['source'] == sample_document['source']
    assert body['modality'] == 'text'
    assert 'id' in body


def test_upload_image_document(base_url: str, sample_image_url: str) -> None:
    payload = {
        'image_url': sample_image_url,
        'source': 'test-logo.png',
        'metadata': {'type': 'logo'},
    }
    r = httpx.post(f'{base_url}/upload', json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body['modality'] == 'image'


def test_upload_returns_in_documents_list(base_url: str, sample_document: dict) -> None:
    httpx.post(f'{base_url}/upload', json=sample_document)
    r = httpx.get(f'{base_url}/documents')
    assert r.status_code == 200
    body = r.json()
    assert body['total'] >= 1
    sources = [d['source'] for d in body['documents']]
    assert sample_document['source'] in sources
