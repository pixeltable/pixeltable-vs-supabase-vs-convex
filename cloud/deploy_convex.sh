#!/bin/sh
# convex-app to its production Convex deployment.
#
#     COMPUTE_SERVICE_URL=https://... COMPUTE_SERVICE_TOKEN=... sh cloud/deploy_convex.sh
#
# Needs `npx convex login` and the project configured once by `npx convex dev`. HTTP
# routes serve from the deployment's .convex.site URL, which `deploy` prints.
set -eu
: "${COMPUTE_SERVICE_URL:?set COMPUTE_SERVICE_URL to the deployed compute-service}"
: "${COMPUTE_SERVICE_TOKEN:?set COMPUTE_SERVICE_TOKEN}"
cd "$(dirname "$0")/../convex-app"

npx convex deploy
npx convex env set --prod COMPUTE_SERVICE_URL "$COMPUTE_SERVICE_URL"
# Over stdin, as Convex's CLI recommends for secrets.
printf '%s' "$COMPUTE_SERVICE_TOKEN" | npx convex env set --prod COMPUTE_SERVICE_TOKEN
