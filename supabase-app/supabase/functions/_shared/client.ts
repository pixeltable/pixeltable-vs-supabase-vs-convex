// Shared between Functions, per Supabase's documented layout: "store any shared code in
// a folder prefixed with an underscore (_)".
// https://supabase.com/docs/guides/functions/development-tips
//
// Imports use the `npm:` specifier with a pinned version, per Supabase's Edge Function
// guidance: "Do NOT use bare specifiers... make sure it's prefixed with either `npm:` or
// `jsr:`", "always define a version", and minimize `esm.sh`.
// https://supabase.com/docs/guides/getting-started/ai-prompts/edge-functions

const COMPUTE_SERVICE_URL = Deno.env.get("COMPUTE_SERVICE_URL") || "http://localhost:9000";

/** Call the external compute service. Deno cannot run ffmpeg, Whisper or CLIP itself. */
export const compute = async (path: string, body: unknown) => {
  const resp = await fetch(`${COMPUTE_SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status} ${await resp.text()}`);
  return await resp.json();
};

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
