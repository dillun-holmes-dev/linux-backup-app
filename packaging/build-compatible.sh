#!/usr/bin/env bash
# Build an Ubuntu 22.04 baseline release on the matching native CPU.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARCH="${ARCH:-$(uname -m)}"
HOST_ARCH="$(uname -m)"

case "$ARCH" in
    x86_64) PLATFORM="linux/amd64" ;;
    aarch64) PLATFORM="linux/arm64" ;;
    *) echo "Unsupported architecture: $ARCH" >&2; exit 2 ;;
esac
if [ "$ARCH" != "$HOST_ARCH" ]; then
    echo "This compatibility builder uses native CPUs." >&2
    echo "Run it on $ARCH Linux or use the GitHub release workflow." >&2
    exit 2
fi

IMAGE="vaultleaf-builder:ubuntu22-$ARCH"
docker build --platform "$PLATFORM" -t "$IMAGE" \
    -f "$HERE/Dockerfile.ubuntu22" "$ROOT"
docker run --rm --platform "$PLATFORM" --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e ARCH="$ARCH" \
    -v "$ROOT:/workspace" "$IMAGE"
