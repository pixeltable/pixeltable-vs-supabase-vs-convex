"""Modal App definition and shared infrastructure.

Modal is compute-only — it provides serverless containers but NO database,
NO vector store, and NO file storage.  Every data operation in this app
requires an external service call:

  Modal container  -->  OpenAI API   (embeddings, vision, chat)
  Modal container  -->  Supabase     (pgvector storage and queries)

This module defines the Modal App, the container image, secrets references,
and a shared Supabase client helper used by all endpoints.
"""

from __future__ import annotations

import os

import modal

# ---------------------------------------------------------------------------
# Modal App
# ---------------------------------------------------------------------------

app = modal.App('platform-comparison-knowledge-base')

# ---------------------------------------------------------------------------
# Container image
# ---------------------------------------------------------------------------
# Modal builds a container image from this spec.  Unlike platforms with a
# built-in runtime (Pixeltable, Convex), you must explicitly declare every
# dependency and manage the image yourself.

image = modal.Image.debian_slim(python_version='3.11').pip_install(
    'openai>=1.30',
    'supabase>=2.0',
    'fastapi[standard]',
)

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
# Modal stores secrets in its own secrets manager — you must create a secret
# group named "knowledge-base-secrets" in the Modal dashboard containing:
#   OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
#
# This is the third piece of infrastructure you manage (Modal + Supabase + Modal Secrets).

secrets = modal.Secret.from_name('knowledge-base-secrets')


# ---------------------------------------------------------------------------
# Shared Supabase client helper
# ---------------------------------------------------------------------------
# Because Modal has no data layer, every function that reads or writes data
# must construct a Supabase client and make a network call to the external DB.

def get_supabase_client():
    """Create a Supabase client from environment variables injected by Modal secrets."""
    from supabase import create_client

    url = os.environ['SUPABASE_URL']
    key = os.environ['SUPABASE_SERVICE_ROLE_KEY']
    return create_client(url, key)


def get_openai_client():
    """Create an OpenAI client from environment variables injected by Modal secrets."""
    from openai import OpenAI

    return OpenAI(api_key=os.environ['OPENAI_API_KEY'])
