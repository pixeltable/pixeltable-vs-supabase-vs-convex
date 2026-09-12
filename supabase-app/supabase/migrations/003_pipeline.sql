-- The pipeline itself: a storage bucket for frames, and the triggers that drive
-- embedding. Without this file the rows exist with NULL embeddings and every
-- search returns nothing, because inserting a row does not compute anything.
--
-- Compare: pixeltable/app.py has no equivalent. `__indexes__` on the model is the
-- whole declaration, and the work runs when the row arrives.

CREATE EXTENSION IF NOT EXISTS pg_net;

-- Public bucket for extracted frames. The ingest function uploads into it.
INSERT INTO storage.buckets (id, name, public)
VALUES ('frames', 'frames', true)
ON CONFLICT (id) DO NOTHING;

-- Where the Edge Functions live. Set once per environment.
CREATE TABLE IF NOT EXISTS pipeline_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO pipeline_config (key, value)
VALUES ('functions_url', 'http://host.docker.internal:54321/functions/v1'),
       ('service_role_key', '')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION notify_edge_function(fn_name TEXT, payload JSONB)
RETURNS void AS $$
DECLARE
    base_url TEXT;
    auth_key TEXT;
BEGIN
    SELECT value INTO base_url FROM pipeline_config WHERE key = 'functions_url';
    SELECT value INTO auth_key FROM pipeline_config WHERE key = 'service_role_key';
    PERFORM net.http_post(
        url := base_url || '/' || fn_name,
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'Authorization', 'Bearer ' || auth_key
        ),
        body := payload
    );
END;
$$ LANGUAGE plpgsql;

-- One webhook per frame row. A 15-second video at 1 FPS fires 15 of these.
CREATE OR REPLACE FUNCTION on_frame_inserted()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM notify_edge_function('process-frames', jsonb_build_object('record', to_jsonb(NEW)));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS frames_embed_trigger ON frames;
CREATE TRIGGER frames_embed_trigger
    AFTER INSERT ON frames
    FOR EACH ROW EXECUTE FUNCTION on_frame_inserted();

-- One webhook per audio chunk row.
CREATE OR REPLACE FUNCTION on_chunk_inserted()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM notify_edge_function('process-audio', jsonb_build_object('record', to_jsonb(NEW)));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS chunks_transcribe_trigger ON audio_chunks;
CREATE TRIGGER chunks_transcribe_trigger
    AFTER INSERT ON audio_chunks
    FOR EACH ROW EXECUTE FUNCTION on_chunk_inserted();

-- `status` on videos is set by the ingest function before any embedding has run,
-- so it cannot be trusted. This derives the real answer by counting NULLs.
CREATE OR REPLACE FUNCTION video_status(v_id BIGINT)
RETURNS TEXT AS $$
    SELECT CASE
        WHEN (SELECT status FROM videos WHERE id = v_id) = 'error' THEN 'error'
        WHEN EXISTS (SELECT 1 FROM frames WHERE video_id = v_id AND embedding IS NULL) THEN 'processing'
        WHEN EXISTS (SELECT 1 FROM audio_chunks WHERE video_id = v_id AND embedding IS NULL) THEN 'processing'
        ELSE 'ready'
    END;
$$ LANGUAGE sql STABLE;
