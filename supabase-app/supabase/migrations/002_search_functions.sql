-- Search functions with JOINs back to videos table.
-- Each function has to know which model filled the column it searches: 512 dimensions
-- of CLIP here, 384 of sentence-transformers there. Nothing enforces that the query
-- vector came from the same model as the index. Compare: Frames.frame.similarity(string=q).

CREATE OR REPLACE FUNCTION search_frames(
    query_embedding vector(512),
    match_count INT DEFAULT 10
)
RETURNS TABLE(
    frame_id BIGINT,
    frame_url TEXT,
    frame_idx INT,
    video_title TEXT,
    similarity FLOAT
) AS $$
    SELECT
        f.id AS frame_id,
        f.frame_url,
        f.frame_idx,
        v.title AS video_title,
        1 - (f.embedding <=> query_embedding) AS similarity
    FROM frames f
    JOIN videos v ON f.video_id = v.id
    WHERE f.embedding IS NOT NULL
    ORDER BY f.embedding <=> query_embedding
    LIMIT match_count;
$$ LANGUAGE sql STABLE;


CREATE OR REPLACE FUNCTION search_transcripts(
    query_embedding vector(384),
    match_count INT DEFAULT 10
)
RETURNS TABLE(
    chunk_id BIGINT,
    transcript TEXT,
    start_sec FLOAT,
    video_title TEXT,
    similarity FLOAT
) AS $$
    SELECT
        ac.id AS chunk_id,
        ac.transcript,
        ac.start_sec,
        v.title AS video_title,
        1 - (ac.embedding <=> query_embedding) AS similarity
    FROM audio_chunks ac
    JOIN videos v ON ac.video_id = v.id
    WHERE ac.embedding IS NOT NULL AND ac.transcript IS NOT NULL
    ORDER BY ac.embedding <=> query_embedding
    LIMIT match_count;
$$ LANGUAGE sql STABLE;
