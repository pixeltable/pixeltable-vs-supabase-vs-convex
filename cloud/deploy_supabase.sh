#!/bin/sh
# supabase-app to a hosted Supabase project.
#
#     SUPABASE_PROJECT_REF=... COMPUTE_SERVICE_URL=https://... COMPUTE_SERVICE_TOKEN=... \
#         sh cloud/deploy_supabase.sh
#
# Needs `supabase login` and a project created in the dashboard (region us-east-1, beside
# the compute Space). `link` and `db push` ask for the database password.
set -eu
: "${SUPABASE_PROJECT_REF:?set SUPABASE_PROJECT_REF}"
: "${COMPUTE_SERVICE_URL:?set COMPUTE_SERVICE_URL to the deployed compute-service}"
: "${COMPUTE_SERVICE_TOKEN:?set COMPUTE_SERVICE_TOKEN}"
cd "$(dirname "$0")/../supabase-app"

npx supabase link --project-ref "$SUPABASE_PROJECT_REF"
npx supabase db push
# The function authenticates with withSupabase({ auth: 'secret' }); a secret API key is
# not a JWT, so the gateway's JWT check is off, as it is under `functions serve` locally.
npx supabase functions deploy api --no-verify-jwt --project-ref "$SUPABASE_PROJECT_REF"

# Through a file rather than argv, so the token never shows in the process list.
env_file=$(mktemp)
trap 'rm -f "$env_file"' EXIT
chmod 600 "$env_file"
printf 'COMPUTE_SERVICE_URL=%s\nCOMPUTE_SERVICE_TOKEN=%s\n' "$COMPUTE_SERVICE_URL" "$COMPUTE_SERVICE_TOKEN" >"$env_file"
npx supabase secrets set --env-file "$env_file" --project-ref "$SUPABASE_PROJECT_REF"
echo "https://$SUPABASE_PROJECT_REF.supabase.co"
