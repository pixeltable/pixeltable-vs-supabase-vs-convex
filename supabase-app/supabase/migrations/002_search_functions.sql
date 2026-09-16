-- Search functions with JOINs back to videos table.
-- `search_path = ''` (set in 004_security.sql) means every table, and the `<=>`
-- operator itself, has to be schema-qualified. That is the price of closing the
-- search_path hole Supabase's advisors flag.
--
-- Each function has to know which model filled the column it searches: 512 dimensions
-- of CLIP here, 384 of sentence-transformers there. Nothing enforces that the query
-- vector came from the same model as the index. Compare: Frames.frame.similarity(string=q).

CREATE OR REPLACE FUNCTION search_frames(
    query_embedding vector(512),
    match_count INT DEFAULT 10
)
RETURNS TABLE(
    frame_url TEXT,
    frame_idx INT,
    video_title TEXT,
    similarity FLOAT
) AS $$
    SELECT
        f.frame_url,
        f.frame_idx,
        v.title AS video_title,
        GREATEST(0.0, LEAST(1.0, 1 - (f.embedding OPERATOR(public.<=>) query_embedding))) AS similarity
    FROM public.frames f
    JOIN public.videos v ON f.video_id = v.id
    WHERE f.embedding IS NOT NULL
    ORDER BY f.embedding OPERATOR(public.<=>) query_embedding
    LIMIT match_count;
$$ LANGUAGE sql STABLE;


CREATE OR REPLACE FUNCTION search_transcripts(
    query_embedding vector(384),
    match_count INT DEFAULT 10
)
RETURNS TABLE(
    transcript TEXT,
    start_sec FLOAT,
    video_title TEXT,
    similarity FLOAT
) AS $$
    SELECT
        ac.transcript,
        ac.start_sec,
        v.title AS video_title,
        GREATEST(0.0, LEAST(1.0, 1 - (ac.embedding OPERATOR(public.<=>) query_embedding))) AS similarity
    FROM public.audio_chunks ac
    JOIN public.videos v ON ac.video_id = v.id
    WHERE ac.embedding IS NOT NULL AND ac.transcript IS NOT NULL
    ORDER BY ac.embedding OPERATOR(public.<=>) query_embedding
    LIMIT match_count;
$$ LANGUAGE sql STABLE;


-- One row per video with its counts, so GET /videos is a single request instead of
-- three per video. Compare pixeltable/app.py, where `scene_count` is a column on the
-- base table and the view lineage supplies the title.
CREATE OR REPLACE VIEW video_summary AS
    SELECT
        v.title AS video_title,
        v.status,
        COALESCE(MAX(ac.end_sec), 0) AS duration_sec,
        count(DISTINCT s.id) AS scene_count
    FROM public.videos v
    LEFT JOIN public.scenes s ON s.video_id = v.id
    LEFT JOIN public.audio_chunks ac ON ac.video_id = v.id
    GROUP BY v.id, v.title, v.status;
