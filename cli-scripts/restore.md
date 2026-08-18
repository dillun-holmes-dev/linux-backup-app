# How to restore

Two very different situations — pick the right one.

---

## Situation 1 — THIS PC STILL WORKS  →  quick recovery (daily / weekly)

You deleted a file, or want yesterday's version. Do it **on this exact machine** —
no other PC needed, tools are already installed.

    # see what's available
    restic -r rclone:gdrive:daily  snapshots        # or ...:weekly

    # restore one file/folder from the newest backup
    restic -r rclone:gdrive:daily  restore latest \
        --include /path/to/file --target ~/restored

The **My Backups** app shows the same snapshots. This is your everyday recovery path.

---

## Situation 2 — THIS PC IS GONE  →  full restore (monthly image)

If the PC is **stolen or dead**, use the **monthly bootable image** and restore it
on **any other computer** (another Linux, or Windows). It brings back the whole OS,
files and apps, bootable on a new NVMe.

### On another Linux PC (or a Live USB created on any machine)

1. Install tools:
       sudo apt install -y rclone restic gnupg zstd openssl
2. Connect to Google Drive (authorize in the browser):
       rclone config reconnect gdrive:
3. Get this kit and unlock the keys:
       rclone copy gdrive:restore-tools ~/backup-scripts
       cd ~/backup-scripts
       gpg -d KEYS-LOCKED.gpg > keys.tar.gz && tar -xzf keys.tar.gz
4. Restore to the new NVMe (⚠️ OVERWRITES the target disk):
       sudo ./restore-monthly.sh /dev/nvmeXnY

The disk comes back **bootable** — partitions + bootloader included.

### On Windows

Follow **RESTORE-ON-WINDOWS.txt** (in this folder) — uses WSL2 + balenaEtcher.

---

## The keys

Both keys are locked in **KEYS-LOCKED.gpg** on Drive (AES-256). You only need the
unlock password (yours alone — it is NOT on the Drive):

    gpg -d KEYS-LOCKED.gpg > keys.tar.gz && tar -xzf keys.tar.gz

That creates `restic-passphrase.txt` + `backup-key.bin`, which the restore scripts use.

---

## Practice once!

Restore to a **spare USB/SSD** at least once. A backup you've never restored is not a backup.

## Health checks

    sudo journalctl -u backup-daily -u backup-integrity --since today
