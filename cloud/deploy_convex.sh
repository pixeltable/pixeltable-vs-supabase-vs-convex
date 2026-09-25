#!/bin/sh
# convex-app to a production Convex deployment.
#
#     CONVEX_DEPLOY_KEY=prod:... COMPUTE_SERVICE_URL=http://... COMPUTE_SERVICE_TOKEN=... \
#         sh cloud/deploy_convex.sh
#
# The deploy key comes from the project's settings in the Convex dashboard, and selects
# the deployment every command below acts on. It is used instead of `npx convex dev`,
# which would rewrite convex-app/.env.local and point the local benchmark and CI at the
# cloud. HTTP routes serve from the deployment's .convex.site URL, which `deploy` prints.
set -eu
: "${CONVEX_DEPLOY_KEY:?set CONVEX_DEPLOY_KEY to the project production deploy key}"
: "${COMPUTE_SERVICE_URL:?set COMPUTE_SERVICE_URL to the deployed compute-service}"
: "${COMPUTE_SERVICE_TOKEN:?set COMPUTE_SERVICE_TOKEN}"
cd "$(dirname "$0")/../convex-app"

npx convex deploy
npx convex env set COMPUTE_SERVICE_URL "$COMPUTE_SERVICE_URL"
# Over stdin, as Convex's CLI recommends for secrets.
printf '%s' "$COMPUTE_SERVICE_TOKEN" | npx convex env set COMPUTE_SERVICE_TOKEN
