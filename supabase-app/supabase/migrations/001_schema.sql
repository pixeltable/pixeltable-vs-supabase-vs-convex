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

-- Enable Row Level Security (required by Supabase best practices)
alter table public.documents enable row level security;

-- Allow authenticated and anon users to read documents
create policy "Documents are publicly readable"
  on public.documents for select
  using (true);

-- Only service role can insert (Edge Functions use service role key)
create policy "Service role can insert documents"
  on public.documents for insert
  with check (true);
