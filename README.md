# VaultLeaf Backup — easy Linux backup manager

A native GTK4 backup app built on **restic** and **rclone**. It includes an
easy setup flow; pre-written scripts and hand-edited systemd units are no
longer required.

![icon](my_backups/data/icon.svg)

## Features

- **Overview** — live progress bars for daily, weekly, and monthly backups, upload speed,
  ETA, storage information, and the next scheduled runs.
- **Backups & logs** — snapshot lists for daily, weekly, and monthly repositories plus
  live logs.
- **Restore** — a guided, overwrite-safe recovery flow with friendly dates,
  partial recovery, confirmation, cancellation, progress, and one-click access.
- **Backup plan** — connect Google Drive with OAuth, connect a persistent SMB
  network share, or choose a local/synced folder; then fully customize jobs.
- **Settings** — direct shortcuts for storage, source, speed, and schedules;
  browse for exclusions; and view upcoming jobs and destinations.

## Easy first-run setup

Open **Backup plan**. A five-step assistant guides users through
**Welcome → Storage → Backup → Schedule → Review**. It validates each step,
explains recommended choices, and changes nothing until **Finish setup**.

Choose one:

- **Cloud account (rclone OAuth)** — click **Add Google Drive account…**.
  rclone opens OAuth sign-in in your browser. Return to the app and select the
  new account. Accounts already present in rclone are also listed.
- **Local or synced folder** — choose a writable local disk, external disk,
  NAS folder, or a folder already managed by another sync app.
- **Windows or NAS share (SMB)** — enter the server, share, and login, test the
  connection, and choose where it should appear locally. VaultLeaf creates a
  user service that reconnects after login (including after a reboot) and
  retries network failures.
  The password is obscured in rclone's private configuration and is not copied
  into VaultLeaf's JSON settings.

The app creates a private restic password, backup repositories, and user-level
systemd schedules. Cloud mode also creates `~/MyBackups/CloudDrive` and enables
a persistent rclone mount. It reconnects after reboot when the user signs in.
Timers use `Persistent=true`, so a backup missed while the computer was off
runs after it starts again.

Daily, weekly, monthly, and integrity jobs can each be enabled or disabled.
Choose exact 24-hour times, weekdays, a monthly date from 1–28, or the last day
of every month. Disabled backups remain available from **Run now**.

Local destinations receive a small marker file. If an external disk or network
folder is missing, the scheduled backup stops instead of silently writing to
the wrong disk.

### Easy or faster Google connection

- **Easy shared rclone client** needs only browser sign-in. It can be slower
  when many people are sharing the default Google API quota.
- **Private Google API client JSON** uses your own quota. Create a Desktop OAuth
  client in Google Cloud, add your account as a test user, download the JSON,
  and select it in setup. The secret is passed directly into rclone and is not
  copied into the app's configuration.

Choose a reliable, balanced, or fast connection profile. This controls rclone
concurrency, Drive upload chunk size, retries, cloud refresh frequency, and the
percentage of repository data sampled by integrity checks.

### Background operation and integrity alerts

Setup installs an XDG autostart entry and a permanent user-local application
copy. Closing the main window hides it; backups and integrity checks continue.
On desktops supporting StatusNotifierItem, left-clicking the tray icon opens
the app and right-clicking opens controls containing **Quit background app**.
If a desktop hides tray icons, a notification provides the same controller.

A persistent weekly integrity timer checks repository structure and samples
stored data. A failure produces both a desktop notification and a blocking
error popup, and the tray icon requests attention. Integrity output appears in
**Backups & logs**.

### Easy exclusions

In **Settings**, choose **Add files…** or **Add folders…** and select one or
more items. Paths are deduplicated and saved automatically. Advanced users can
still enter restic patterns directly. The app rejects selections that would
exclude the entire backup source.

## Requirements

- Ubuntu/GNOME with `python3`, PyGObject and GTK4:
  ```sh
  sudo apt install python3-gi gir1.2-gtk-4.0
  ```
- `restic`, `rclone`, and FUSE (`fuse3`) for the optional cloud folder.
- Existing root/system-wide backup setups remain supported.

The setup page can install these components with one administrator prompt on
APT, DNF, Zypper, Pacman, and APK-based distributions. Normal operation is
entirely user-owned and does not ask for administrator access again.

## Run (without packaging)

```sh
cd "backup llinux app"
chmod +x run-my-backups.sh   # once
./run-my-backups.sh
# or
python3 -m my_backups
```

For a new machine, the bootstrap installer requests sudo once, installs the
right dependencies, installs the app under `~/.local`, and launches it:

```sh
chmod +x install.sh
./install.sh
```

## Build the AppImage

```sh
cd "backup llinux app"
bash packaging/build-appimage.sh     # needs curl; downloads appimagetool once
```

Result: **`VaultLeafBackup-x86_64.AppImage`** in the project root.

### Install & launch the AppImage

```sh
chmod +x VaultLeafBackup-x86_64.AppImage
./VaultLeafBackup-x86_64.AppImage    # just run it, or
```

To get an app-menu entry + icon on Ubuntu 22.04+:
**right-click the AppImage → “Allow Launching”**, then double-click it.
Or install it system-wide:

```sh
sudo cp VaultLeafBackup-x86_64.AppImage /opt/
sudo chmod +x /opt/VaultLeafBackup-x86_64.AppImage
ln -s /opt/VaultLeafBackup-x86_64.AppImage ~/.local/bin/my-backups
```

## Notes

- New setups run as the current user and do not need an administrator password.
  Existing root backup configurations still use `pkexec`.
- **Restore runs as your user** and writes to the folder you choose
  (default `~/Restored`). Daily, weekly, and monthly snapshots are available.
- The AppImage uses your system's GTK runtime, so it works on this GNOME
  machine without bundling gigabytes of libraries.
- Setup data is kept in `~/.local/share/my-backups/`; advanced configuration
  is in `~/.config/my-backups/config.json`.
- Secrets are **not** bundled in the AppImage.
