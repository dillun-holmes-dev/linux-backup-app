#!/bin/bash
# Run a FULL backup RIGHT NOW in the foreground with a live progress bar.
#   ./run-backup-now.sh            -> daily repo (default)
#   ./run-backup-now.sh weekly     -> weekly repo
set -euo pipefail

export RCLONE_CONFIG="/home/dillun/.config/rclone/rclone.conf"
PWFILE="/home/dillun/backup-scripts/restic-passphrase.txt"
TARGET="${1:-daily}"

case "$TARGET" in
  daily)  REPO="rclone:gdrive:daily";  KEEP="--keep-daily 5" ;;
  weekly) REPO="rclone:gdrive:weekly"; KEEP="--keep-last 2" ;;
  *) echo "Usage: $0 [daily|weekly]"; exit 1 ;;
esac

echo "== Full $TARGET backup to Google Drive (progress bar below) =="
sudo env RCLONE_CONFIG="$RCLONE_CONFIG" restic --password-file "$PWFILE" -r "$REPO" backup / \
  --exclude-file=/home/dillun/backup-scripts/excludes.txt \
  --exclude-caches \
  --pack-size 128

echo ""
echo "== Pruning old snapshots =="
sudo env RCLONE_CONFIG="$RCLONE_CONFIG" restic --password-file "$PWFILE" -r "$REPO" forget \
  $KEEP --pack-size 128 --prune

echo ""
echo "== Snapshots =="
sudo env RCLONE_CONFIG="$RCLONE_CONFIG" restic --password-file "$PWFILE" -r "$REPO" snapshots
