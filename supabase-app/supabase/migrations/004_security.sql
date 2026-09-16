-- Everything Supabase's own advisors flag as an error, fixed.
-- Verify with: supabase db advisors --local --type all --level warn
--
-- This app talks to Postgres only through an Edge Function holding the service role,
-- so no client ever needs direct table access. Enabling RLS with no policies is exactly
-- right for that: PostgREST's anon and authenticated roles are denied everything, and
-- the service role bypasses RLS as usual. A multi-tenant application would instead write
-- per-table policies against auth.uid(); see ../../docs/TRADEOFFS.md.

ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE frames ENABLE ROW LEVEL SECURITY;
ALTER TABLE audio_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE scenes ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

-- A view runs with its creator's permissions unless told otherwise, which would let it
-- read past the RLS of whoever queries it.
ALTER VIEW video_summary SET (security_invoker = true);

-- Without a fixed search_path, a caller can shadow the objects these functions resolve.
ALTER FUNCTION search_frames(vector, int) SET search_path = '';
ALTER FUNCTION search_transcripts(vector, int) SET search_path = '';
