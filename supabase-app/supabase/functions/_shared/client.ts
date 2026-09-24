// Shared between Functions, per Supabase's documented layout: "store any shared code in
// a folder prefixed with an underscore (_)".
// https://supabase.com/docs/guides/functions/development-tips
//
// Imports use the `npm:` specifier with a pinned version, per Supabase's Edge Function
// guidance: "Do NOT use bare specifiers... make sure it's prefixed with either `npm:` or
// `jsr:`", "always define a version", and minimize `esm.sh`.
// https://supabase.com/docs/guides/getting-started/ai-prompts/edge-functions

const COMPUTE_SERVICE_URL = Deno.env.get("COMPUTE_SERVICE_URL") || "http://localhost:9000";
// Set on a deployed project with `supabase secrets set`; unset locally, where the service
// accepts any caller.
const COMPUTE_SERVICE_TOKEN = Deno.env.get("COMPUTE_SERVICE_TOKEN");

/** Call the external compute service, which runs the ffmpeg and model work for this app. */
export const compute = async (path: string, body: unknown) => {
  const resp = await fetch(`${COMPUTE_SERVICE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(COMPUTE_SERVICE_TOKEN ? { Authorization: `Bearer ${COMPUTE_SERVICE_TOKEN}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status} ${await resp.text()}`);
  return await resp.json();
};

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** A malformed request body. Thrown here, turned into a 400 by the router.
 *
 * Without it, a missing or wrongly typed field is an unhandled throw, which the Edge
 * Runtime surfaces as a 500: a server error reported for a client mistake, which clients
 * retry and alerting pages on. Deno has no request-validation layer, so the check is
 * ours to write. */
export class BadRequest extends Error {}

export const readJson = async (req: Request): Promise<Record<string, unknown>> => {
  const body = await req.json().catch(() => null);
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw new BadRequest("body must be a JSON object");
  }
  return body as Record<string, unknown>;
};

export const requireString = (value: unknown, field: string): string => {
  if (typeof value !== "string") throw new BadRequest(`${field} must be a string`);
  return value;
};

export const readLimit = (value: unknown, fallback = 10): number => {
  if (value === undefined || value === null) return fallback;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new BadRequest("limit must be a non-negative integer");
  }
  return value;
};
