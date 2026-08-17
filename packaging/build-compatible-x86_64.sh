#!/usr/bin/env bash
# Build against Ubuntu 22.04's glibc for compatibility with current desktops.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ARCH=x86_64 exec "$HERE/build-compatible.sh"
