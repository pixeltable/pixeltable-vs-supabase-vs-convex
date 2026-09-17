-- Evolution task: make the video title semantically searchable on a populated database.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS title_embedding vector(384);
CREATE INDEX IF NOT EXISTS videos_title_embedding_idx ON videos
    USING hnsw (title_embedding vector_cosine_ops);
