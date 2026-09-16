# Why `deno lint` excludes `no-import-prefix`

Deno's default style is to declare dependencies in an import map and import bare
specifiers. Supabase's Edge Function guidance says the opposite, verbatim:

> "Do NOT use bare specifiers when importing dependencies... make sure it's prefixed with
> either `npm:` or `jsr:`."

Two standards, and for a Supabase Edge Function the platform's own rule wins. That one
rule is excluded in `deno.json` and every other default stays on, including
`no-unversioned-import`, which enforces the other half of the same guidance: "always
define a version".

https://supabase.com/docs/guides/getting-started/ai-prompts/edge-functions
