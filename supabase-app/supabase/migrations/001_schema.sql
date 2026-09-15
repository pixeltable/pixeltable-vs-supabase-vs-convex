-- Video Intelligence Pipeline schema
-- 5 tables, 3 foreign keys, 2 vector columns, 2 HNSW indexes, 1 status column.
-- Compare: pixeltable/app.py declares 1 table and 2 views, and no status column,
-- because a cell either holds a value or holds its own error.

CREATE EXTENSION IF NOT EXISTS vector;

-- Main video table
CREATE TABLE IF NOT EXISTS videos (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    video_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'ready', 'error')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Extracted frames (one per video per FPS tick)
CREATE TABLE IF NOT EXISTS frames (
    id BIGSERIAL PRIMARY KEY,
    video_id BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_idx INT NOT NULL,
    frame_url TEXT NOT NULL,
    embedding vector(512),  -- openai/clip-vit-base-patch32
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS frames_video_id_idx ON frames(video_id);
CREATE INDEX IF NOT EXISTS frames_embedding_idx ON frames
    USING hnsw (embedding vector_cosine_ops);

-- Audio chunks (10-second segments)
CREATE TABLE IF NOT EXISTS audio_chunks (
    id BIGSERIAL PRIMARY KEY,
    video_id BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    start_sec FLOAT NOT NULL,
    end_sec FLOAT NOT NULL,
    transcript TEXT,
    embedding vector(384),  -- sentence-transformers/all-MiniLM-L6-v2
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audio_chunks_video_id_idx ON audio_chunks(video_id);
CREATE INDEX IF NOT EXISTS audio_chunks_embedding_idx ON audio_chunks
    USING hnsw (embedding vector_cosine_ops);

-- Detected scenes
CREATE TABLE IF NOT EXISTS scenes (
    id BIGSERIAL PRIMARY KEY,
    video_id BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    start_sec FLOAT NOT NULL,
    end_sec FLOAT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS scenes_video_id_idx ON scenes(video_id);


-- The agent's evidence. In pixeltable/app.py this is the Conversations table, where
-- retrieval is a column; here it is a table the agent writes to by hand.
CREATE TABLE IF NOT EXISTS conversations (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    visual JSONB NOT NULL DEFAULT '[]'::jsonb,
    spoken JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
