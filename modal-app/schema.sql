-- =============================================================================
-- Modal has NO data layer — this SQL must be run on Supabase, Neon, or any
-- Postgres instance with pgvector installed.  Modal is compute-only; every
-- query and insert in the Modal app hits this external database over the
-- network.  This is the fundamental architectural difference vs. platforms
-- that bundle storage (Pixeltable, Convex, Supabase).
-- =============================================================================

-- Enable pgvector extension for embedding storage and similarity search
create extension if not exists vector with schema extensions;

-- Documents table: stores text content, image descriptions, and their embeddings
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  content text not null,
  source text not null,
  modality text not null check (modality in ('text', 'image')),
  image_url text,
  metadata jsonb default '{}'::jsonb,
  embedding extensions.vector(1536) not null,
  created_at timestamptz default now()
);

-- HNSW index for fast approximate nearest-neighbor search
create index documents_embedding_idx
  on public.documents
  using hnsw (embedding extensions.vector_cosine_ops)
  with (m = 16, ef_construction = 64);

-- Index for filtering by modality
create index documents_modality_idx on public.documents (modality);

-- Index for ordering by creation time
create index documents_created_at_idx on public.documents (created_at desc);

-- RPC function for semantic search via pgvector cosine distance.
-- Modal calls this via the Supabase client SDK's .rpc() method, because
-- Modal itself has no query engine — it must delegate to Postgres.
create or replace function public.search_documents(
  query_embedding extensions.vector(1536),
  match_count int default 5
)
returns table (
  id uuid,
  content text,
  source text,
  modality text,
  image_url text,
  metadata jsonb,
  similarity float
)
language plpgsql
as $$
begin
  return query
    select
      d.id,
      d.content,
      d.source,
      d.modality,
      d.image_url,
      d.metadata,
      1 - (d.embedding <=> query_embedding) as similarity
    from public.documents d
    order by d.embedding <=> query_embedding
    limit match_count;
end;
$$;
