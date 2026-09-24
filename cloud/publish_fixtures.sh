#!/bin/sh
# The fixture videos, at a public URL every hosted implementation can fetch.
#
#     HF_DATASET=owner/name sh cloud/publish_fixtures.sh
#
# A hosted Pixeltable, Edge Function or Convex action cannot read this laptop's disk, so
# `harness/seed.py --video-base-url` sends each video as a URL under the base this
# prints. One base covers every tier, because the tier directories are part of the path.
set -eu
: "${HF_DATASET:?set HF_DATASET=owner/name}"
cd "$(dirname "$0")/.."

hf repo create "$HF_DATASET" --repo-type dataset --exist-ok
hf upload "$HF_DATASET" fixtures/videos . --repo-type dataset --include '*.mp4' '*/*.mp4' \
    --commit-message 'Publish fixture videos'
echo "https://huggingface.co/datasets/$HF_DATASET/resolve/main"
