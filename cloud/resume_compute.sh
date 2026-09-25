#!/bin/sh
# Bring compute-service back and point both consumers at it.
#
#     sh cloud/resume_compute.sh
#
# Reads COMPUTE_SERVICE_TOKEN from cloud/.env.cloud. A restarted task gets a new public IP,
# so the new URL is written back to cloud/.env.cloud and set on the Convex deployment and
# the Supabase project; neither step needs the database password. The image is reused
# when the compute-service source has not changed.
set -eu
cd "$(dirname "$0")/.."
set -a
. cloud/.env.cloud
set +a
SUPABASE_PROJECT_REF=${SUPABASE_PROJECT_REF:-tujgsfbhxobyxhgoacsa}
CONVEX_PROD=${CONVEX_PROD:-sleek-snake-473}

URL=$(sh cloud/deploy_compute.sh | tail -1)
case "$URL" in http://*) ;; *) echo "deploy did not print a URL: $URL" >&2; exit 1 ;; esac
grep -v '^COMPUTE_SERVICE_URL=' cloud/.env.cloud >cloud/.env.cloud.new || true
printf 'COMPUTE_SERVICE_URL=%s\n' "$URL" >>cloud/.env.cloud.new
mv cloud/.env.cloud.new cloud/.env.cloud
chmod 600 cloud/.env.cloud

(cd convex-app && npx convex env set --deployment "$CONVEX_PROD" COMPUTE_SERVICE_URL "$URL")
(cd supabase-app && npx supabase secrets set "COMPUTE_SERVICE_URL=$URL" --project-ref "$SUPABASE_PROJECT_REF")
echo "$URL"
