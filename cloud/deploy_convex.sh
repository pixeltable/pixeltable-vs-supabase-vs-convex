#!/bin/sh
# convex-app to its production Convex deployment.
#
#     COMPUTE_SERVICE_URL=http://... COMPUTE_SERVICE_TOKEN=... sh cloud/deploy_convex.sh
#
# Needs `npx convex login`. The project and its production deployment were created once,
# with the CLI:
#
#     npx convex project create platform-comparison
#     npx convex deployment create TEAM:platform-comparison:production --type prod --default --region us
#
# CONVEX_DEPLOYMENT in the environment selects that deployment for `deploy`, and
# `--deployment` does for `env`. Neither touches convex-app/.env.local, which keeps the
# local benchmark and CI on the anonymous local deployment; `npx convex dev` against the
# cloud project would rewrite it. HTTP routes serve from https://$CONVEX_PROD.convex.site.
set -eu
CONVEX_PROD=${CONVEX_PROD:-sleek-snake-473}
: "${COMPUTE_SERVICE_URL:?set COMPUTE_SERVICE_URL to the deployed compute-service}"
: "${COMPUTE_SERVICE_TOKEN:?set COMPUTE_SERVICE_TOKEN}"
cd "$(dirname "$0")/../convex-app"

# Before the code, so no deployed action ever runs without them.
npx convex env set --deployment "$CONVEX_PROD" COMPUTE_SERVICE_URL "$COMPUTE_SERVICE_URL"
# Over stdin, as Convex's CLI recommends for secrets.
printf '%s' "$COMPUTE_SERVICE_TOKEN" | npx convex env set --deployment "$CONVEX_PROD" COMPUTE_SERVICE_TOKEN
CONVEX_DEPLOYMENT="prod:$CONVEX_PROD" npx convex deploy
echo "https://$CONVEX_PROD.convex.site"
