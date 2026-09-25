#!/bin/sh
# Stop compute-service's Fargate task, keeping its image and every resource, so nothing bills
# but the stored image. cloud/resume_compute.sh brings it back.
set -eu
REGION=${AWS_REGION:-us-east-1}
NAME=platform-comparison-compute
aws --region "$REGION" ecs update-service --cluster "$NAME" --service "$NAME" --desired-count 0 >/dev/null
aws --region "$REGION" ecs wait services-stable --cluster "$NAME" --services "$NAME"
echo "paused $NAME: 0 tasks"
