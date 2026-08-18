#!/bin/bash
# Upload the restore tools + instructions to Google Drive (secrets excluded)
# so you can recover from any machine. Runs automatically with the daily backup.
set -uo pipefail

export RCLONE_CONFIG="/home/dillun/.config/rclone/rclone.conf"
SRC="/home/dillun/backup-scripts"
REMOTE="gdrive:restore-tools"
LOG="/home/dillun/backup-scripts/restore-tools-sync.log"

echo "$(date): syncing restore-tools -> $REMOTE" >> "$LOG"
rclone copy "$SRC" "$REMOTE" \
  --exclude 'restic-passphrase.txt' \
  --exclude 'backup-key.bin' \
  --exclude '*.json' \
  --exclude '*.pyc' \
  --exclude '__pycache__' \
  --exclude '.git' \
  >> "$LOG" 2>&1 || echo "$(date): restore-tools sync FAILED" >> "$LOG"
