"""Shared fixtures for integration tests.

These tests require a running server: ``uvicorn main:app --port 8000``
"""

import pytest


@pytest.fixture
def base_url() -> str:
    return 'http://localhost:8000'


@pytest.fixture
def sample_document() -> dict:
    return {
        'content': (
            'Pixeltable unifies data storage, transformation, indexing, '
            'and orchestration for multimodal AI applications.'
        ),
        'source': 'test-doc.txt',
        'metadata': {'category': 'test'},
    }


@pytest.fixture
def sample_image_url() -> str:
    return (
        'https://raw.githubusercontent.com/pixeltable/pixeltable/main/'
        'docs/resources/images/pixeltable-logo-large.png'
    )
