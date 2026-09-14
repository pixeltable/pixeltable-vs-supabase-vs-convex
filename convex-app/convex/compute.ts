// Shared helper. Convex's own best-practices guide: "Most logic should be written as
// plain TypeScript functions, with the query, mutation, and action wrapper functions
// being a thin wrapper around one or more helper function."
// https://docs.convex.dev/understanding/best-practices/

/** Call the external compute service. The Convex runtime cannot run ffmpeg, Whisper or CLIP. */
export const compute = async (path: string, body: unknown) => {
  // Read inside the call, not at module scope: Convex bundles modules at push time and
  // a module-scope read can bake in the fallback before `npx convex env set` runs.
  const base = process.env.COMPUTE_SERVICE_URL || "http://localhost:9000";
  const resp = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
  return await resp.json();
};
