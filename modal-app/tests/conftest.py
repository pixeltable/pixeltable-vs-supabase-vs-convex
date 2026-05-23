"""Pytest fixtures for Modal integration tests.

These tests hit the deployed Modal web endpoints.  You must deploy the
app first with `modal deploy app.py`, then set MODAL_BASE_URL to the
deployment URL (visible in the Modal dashboard).

Unlike Pixeltable (local server) or Supabase (managed), Modal endpoints
live at auto-generated URLs like:
  https://<workspace>--platform-comparison-knowledge-base-<fn>.modal.run
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope='session')
def base_url() -> str:
    """Base URL of the deployed Modal app.

    Modal assigns a unique URL to each @modal.fastapi_endpoint function,
    so the base_url here is the common prefix.  Set MODAL_BASE_URL in
    your environment before running tests.
    """
    url = os.environ.get('MODAL_BASE_URL', '')
    if not url:
        pytest.skip('MODAL_BASE_URL not set — deploy with `modal deploy app.py` first')
    return url.rstrip('/')


@pytest.fixture(scope='session')
def upload_url(base_url: str) -> str:
    return f'{base_url}/upload'


@pytest.fixture(scope='session')
def search_url(base_url: str) -> str:
    return f'{base_url}/search'


@pytest.fixture(scope='session')
def agent_url(base_url: str) -> str:
    return f'{base_url}/agent_query'


@pytest.fixture(scope='session')
def documents_url(base_url: str) -> str:
    return f'{base_url}/documents'
