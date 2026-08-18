#!/bin/bash
# Daily encrypted incremental system backup to Google Drive via restic.
# Keeps the 7 most recent daily snapshots.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export RCLONE_CONFIG="$HOME/.config/rclone/rclone.conf"
REPO="rclone:gdrive:daily"
PWFILE="$SCRIPT_DIR/restic-passphrase.txt"
LOG="/var/log/backup-daily.log"
JSON="/var/tmp/backup-daily.json"

notify() {
  command -v notify-send >/dev/null 2>&1 || return 0
  if [ "$(id -u)" = "0" ]; then
    UUSER="dillun"; UIDU="$(id -u "$UUSER")"
    sudo -u "$UUSER" env DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UIDU/bus" notify-send -a "Backup" "$@" >/dev/null 2>&1 || true
  else
    notify-send -a "Backup" "$@" >/dev/null 2>&1 || true
  fi
}
trap 'echo "FAILED at line $LINENO" >> "$LOG"; notify -u critical "Daily backup FAILED" "See $LOG"' ERR

echo "=== Backup started $(date) ===" >> "$LOG"
notify -u normal "Backup started" "Daily backup to Google Drive"

: > "$JSON"

# Ensure repo is initialized
if ! restic --password-file "$PWFILE" -r "$REPO" snapshots >/dev/null 2>&1; then
  notify -u normal "Backup Init" "Initializing new restic repository"
  restic --password-file "$PWFILE" -r "$REPO" init >> "$LOG" 2>&1
fi

restic --password-file "$PWFILE" -r "$REPO" backup / \
  -o rclone.connections=20 \
  --one-file-system \
  --exclude-file="$SCRIPT_DIR/excludes.txt" \
  --exclude-caches \
  --pack-size 128 \
  --json >> "$JSON" 2>> "$LOG"

restic --password-file "$PWFILE" -r "$REPO" forget \
  --keep-daily 5 \
  --pack-size 128 \
  --prune --json >> "$JSON" 2>> "$LOG"

# Dated manifest so you can see what was backed up and when
MANIFEST="history-$(date +%Y-%m-%d_%H-%M).txt"
restic --password-file "$PWFILE" -r "$REPO" snapshots --compact > "/var/tmp/$MANIFEST" 2>>"$LOG"
rclone copyto "/var/tmp/$MANIFEST" "gdrive:daily/$MANIFEST" >> "$LOG" 2>&1
rm -f "/var/tmp/$MANIFEST"
# keep only the 30 most recent manifests in the daily folder
rclone lsf "gdrive:daily" --files-only --include "history-*" 2>/dev/null | sort | head -n -30 | while read -r f; do
  rclone delete "gdrive:daily/$f" >> "$LOG" 2>&1 || true
done || true

# Keep the restore kit + instructions current on Drive (no secrets included)
"$SCRIPT_DIR/update-restore-tools.sh" || true

notify -u normal "Backup complete" "Daily backup to Google Drive finished"
echo "=== Backup finished $(date) ===" >> "$LOG"
