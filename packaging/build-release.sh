#!/usr/bin/env bash
# Produce both AppImage and extract-and-run releases with checksums.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARCH="${ARCH:-$(uname -m)}"
RELEASE_DIR="$ROOT/dist"
PORTABLE_DIR="$HERE/build/VaultLeafBackup-$ARCH"

"$HERE/build-appimage.sh"

rm -rf "$PORTABLE_DIR"
mkdir -p "$RELEASE_DIR"
cp -a "$HERE/build/AppDir" "$PORTABLE_DIR"
tar -C "$HERE/build" -czf \
    "$RELEASE_DIR/VaultLeafBackup-$ARCH-portable.tar.gz" \
    "$(basename "$PORTABLE_DIR")"
cp "$ROOT/VaultLeafBackup-$ARCH.AppImage" "$RELEASE_DIR/"

(
    cd "$RELEASE_DIR"
    sha256sum "VaultLeafBackup-$ARCH.AppImage" \
        "VaultLeafBackup-$ARCH-portable.tar.gz" >"SHA256SUMS-$ARCH"
)

echo "Release files are in: $RELEASE_DIR"
