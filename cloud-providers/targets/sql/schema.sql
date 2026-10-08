-- The one row every database stores: Neon, Turso, Supabase, Cloudflare D1, Railway, Render and Prisma Postgres.
-- Supabase also needs RLS enabled; the harness writes with the service role key.
CREATE TABLE IF NOT EXISTS docs (id text PRIMARY KEY, title text NOT NULL, body text);
