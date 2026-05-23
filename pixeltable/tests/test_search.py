"""Integration tests for the /search endpoint."""

import pytest
import httpx


pytestmark = pytest.mark.integration


def test_search_returns_results(base_url: str, sample_document: dict) -> None:
    httpx.post(f'{base_url}/upload', json=sample_document)
    r = httpx.post(f'{base_url}/search', json={'query': 'multimodal AI', 'limit': 5})
    assert r.status_code == 200
    body = r.json()
    assert body['query'] == 'multimodal AI'
    assert len(body['results']) >= 1


def test_search_result_shape(base_url: str, sample_document: dict) -> None:
    httpx.post(f'{base_url}/upload', json=sample_document)
    r = httpx.post(f'{base_url}/search', json={'query': 'data storage', 'limit': 3})
    body = r.json()
    for result in body['results']:
        assert 'content' in result
        assert 'source' in result
        assert 'similarity' in result
        assert 0 <= result['similarity'] <= 1
        assert result['modality'] in ('text', 'image')


def test_search_respects_limit(base_url: str) -> None:
    r = httpx.post(f'{base_url}/search', json={'query': 'anything', 'limit': 2})
    assert r.status_code == 200
    assert len(r.json()['results']) <= 2
