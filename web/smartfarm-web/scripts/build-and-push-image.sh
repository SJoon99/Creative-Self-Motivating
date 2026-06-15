#!/usr/bin/env bash
set -euo pipefail

# Build on the NUC, push to internal Harbor first, then fall back to DockerHub.
# Credentials are intentionally not handled here. Run `docker login` beforehand.

APP_NAME="${APP_NAME:-smartfarm-web}"
IMAGE_TAG="${IMAGE_TAG:-0.1.0}"
LOCAL_IMAGE="${APP_NAME}:${IMAGE_TAG}"
DRY_RUN="${DRY_RUN:-0}"

HARBOR_REGISTRY="${HARBOR_REGISTRY:-}"
HARBOR_PROJECT="${HARBOR_PROJECT:-}"
DOCKERHUB_REPOSITORY="${DOCKERHUB_REPOSITORY:-}"

run() {
  printf '+ %s\n' "$*"
  if [ "$DRY_RUN" != "1" ]; then
    "$@"
  fi
}

push_image() {
  local target="$1"
  run docker tag "$LOCAL_IMAGE" "$target"
  run docker push "$target"
}

cd "$(dirname "$0")/.."

run npm run build
run docker build -t "$LOCAL_IMAGE" .

if [ -n "$HARBOR_REGISTRY" ] && [ -n "$HARBOR_PROJECT" ]; then
  HARBOR_IMAGE="${HARBOR_REGISTRY%/}/${HARBOR_PROJECT}/${APP_NAME}:${IMAGE_TAG}"
  printf 'Trying Harbor first: %s\n' "$HARBOR_IMAGE"
  if push_image "$HARBOR_IMAGE"; then
    if [ "$DRY_RUN" = "1" ]; then
      printf 'Dry run complete. Harbor would be used: %s\n' "$HARBOR_IMAGE"
    else
      printf 'Pushed image: %s\n' "$HARBOR_IMAGE"
    fi
    exit 0
  fi
  printf 'Harbor push failed. Falling back to DockerHub if configured.\n' >&2
else
  printf 'Harbor config missing. Set HARBOR_REGISTRY and HARBOR_PROJECT to try Harbor first.\n' >&2
fi

if [ -n "$DOCKERHUB_REPOSITORY" ]; then
  DOCKERHUB_IMAGE="${DOCKERHUB_REPOSITORY}:${IMAGE_TAG}"
  printf 'Trying DockerHub fallback: %s\n' "$DOCKERHUB_IMAGE"
  push_image "$DOCKERHUB_IMAGE"
  if [ "$DRY_RUN" = "1" ]; then
    printf 'Dry run complete. DockerHub fallback would be used: %s\n' "$DOCKERHUB_IMAGE"
  else
    printf 'Pushed image: %s\n' "$DOCKERHUB_IMAGE"
  fi
  exit 0
fi

cat >&2 <<'EOF'
No registry push target configured.

Set one or both:
  HARBOR_REGISTRY=harbor.internal.example
  HARBOR_PROJECT=smartfarm
  DOCKERHUB_REPOSITORY=dockerhub-user/smartfarm-web

Example:
  HARBOR_REGISTRY=harbor.local HARBOR_PROJECT=smartfarm \
  DOCKERHUB_REPOSITORY=joon/smartfarm-web IMAGE_TAG=0.1.0 \
  ./scripts/build-and-push-image.sh
EOF
exit 2
