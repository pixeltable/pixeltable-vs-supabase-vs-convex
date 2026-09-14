-- A public bucket for the extracted frames. The API Function uploads into it.
--
-- The previous version of this file also declared pg_net triggers that fired one
-- webhook per frame row. That is gone: the API Function embeds the whole batch in one
-- call, which is both idiomatic and far faster. What the triggers bought was automatic
-- processing of rows inserted by anyone, from anywhere, which is what Pixeltable's
-- computed columns give you for free. See docs/JOURNEY.md, step 4.

INSERT INTO storage.buckets (id, name, public)
VALUES ('frames', 'frames', true)
ON CONFLICT (id) DO NOTHING;
