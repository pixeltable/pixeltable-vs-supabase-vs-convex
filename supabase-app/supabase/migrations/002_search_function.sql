-- RPC function for semantic search via pgvector cosine distance
-- Must be created as a separate migration because it depends on the documents table
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
