-- Control: the same ALTER TABLE path with a column that needs no backfill.
-- What remains in the semantic run after subtracting this is the HNSW index build.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS title_tag text;
