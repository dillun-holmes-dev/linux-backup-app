#!/bin/bash
# Weekly integrity checks:
#  1) restic repository structure check (fast)
#  2) sample 10% of the backup data each week (full coverage over ~10 weeks)
set -euo pipefail

export RCLONE_CONFIG="/home/dillun/.config/rclone/rclone.conf"
REPO="rclone:gdrive:restic-repo"
PWFILE="/home/dillun/backup-scripts/restic-passphrase.txt"
LOG="/var/log/backup-integrity.log"

echo "=== Integrity check started $(date) ===" >> "$LOG"

restic --password-file "$PWFILE" -r "$REPO" check >> "$LOG" 2>&1
restic --password-file "$PWFILE" -r "$REPO" check --read-data --read-data-subset=10% >> "$LOG" 2>&1

echo "=== Integrity check finished $(date) ===" >> "$LOG"
