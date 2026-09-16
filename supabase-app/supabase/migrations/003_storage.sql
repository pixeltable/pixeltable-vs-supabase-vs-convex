-- A public bucket for the extracted frames. The API Function uploads into it.
--
-- The API Function embeds the whole batch in one call, so no trigger is needed here.
-- Per-row automatic processing, for rows inserted by anything other than that Function,
-- would need a pg_net trigger and one webhook per row. That is what Pixeltable's computed
-- columns give you for free. See docs/JOURNEY.md, step 4.

INSERT INTO storage.buckets (id, name, public)
VALUES ('frames', 'frames', true)
ON CONFLICT (id) DO NOTHING;
