-- A video whose media steps failed must not appear in GET /videos. The contract's list
-- row carries no status, so listing a failed video tells a caller it processed. The row
-- stays in `videos` with status 'error'; the view is what the API answers from.
CREATE OR REPLACE VIEW video_summary AS
    SELECT
        v.title AS video_title,
        v.status,
        COALESCE(MAX(ac.end_sec), 0) AS duration_sec,
        count(DISTINCT s.id) AS scene_count
    FROM public.videos v
    LEFT JOIN public.scenes s ON s.video_id = v.id
    LEFT JOIN public.audio_chunks ac ON ac.video_id = v.id
    WHERE v.status = 'ready'
    GROUP BY v.id, v.title, v.status;

-- CREATE OR REPLACE VIEW keeps the options of the existing view on most versions, but
-- restating it is cheap and the advisors check exits non-zero if it is ever lost.
ALTER VIEW video_summary SET (security_invoker = true);
