#!/bin/bash
# Restore the latest monthly full disk image to a target disk.
# IMPORTANT: Run from a Live USB. The target disk will be OVERWRITTEN.
# Usage: sudo ./restore-monthly.sh /dev/nvmeXnY
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# Use the original machine's rclone config if present, else the live user's default
if [ -f "/home/dillun/.config/rclone/rclone.conf" ]; then
  export RCLONE_CONFIG="/home/dillun/.config/rclone/rclone.conf"
fi
TARGET="${1:?Usage: $0 /dev/nvmeXnY  (target disk to restore TO)}"
KEYFILE="$DIR/backup-key.bin"
REMOTE="gdrive:monthly"
STAGE="/var/tmp/restore-monthly"

echo "WARNING: This will erase $TARGET completely!"
read -r -p "Type YES to continue: " ans
[ "$ans" = "YES" ] || { echo "Aborted."; exit 1; }

mkdir -p "$STAGE"
LATEST="$(rclone lsf "$REMOTE" --dirs-only | sort | tail -n 1)"
echo "Restoring from: $LATEST"

# Download the most recent month's parts
rclone copy "$REMOTE/$LATEST" "$STAGE" --progress

# Reassemble -> decrypt -> decompress -> write to disk
cat "$STAGE"/system-*.part.* \
  | openssl enc -d -aes-256-cbc -pbkdf2 -salt -pass file:"$KEYFILE" \
  | zstd -d -T0 -q \
  | dd of="$TARGET" bs=4M status=progress conv=fsync

sync
echo "Done. The disk is now bootable — install it and power on."
