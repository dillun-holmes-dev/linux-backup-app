# Linux portability

VaultLeaf releases include their own Python, PyGObject, GTK4, restic, rclone,
typelibs, image loaders, GLib schemas, and dynamically loaded GTK modules.
They never execute a system Python interpreter.

## Release formats

- `VaultLeafBackup-<arch>.AppImage` is the normal single-file desktop app.
- `VaultLeafBackup-<arch>-portable.tar.gz` is the fallback for a machine that
  cannot mount AppImages. Extract it and run `VaultLeafBackup-<arch>/AppRun`.

## Compatibility boundary

Linux is not one binary platform. Releases are CPU-specific (`x86_64` or
`aarch64`) and require a graphical desktop plus a glibc version at least as new
as the build host. Build release artifacts on the oldest supported distro.
Ubuntu 22.04 is the x86-64 baseline.

FUSE is not needed by the portable archive. It remains an operating-system
requirement only when the user chooses VaultLeaf's mounted cloud-folder mode.
Direct rclone repositories and local-folder backups do not use a FUSE mount.

## Building

Install the build dependencies on the build host, then run:

```sh
./packaging/build-release.sh
```

Tagged releases are built natively on GitHub's `ubuntu-22.04` x86-64 and
`ubuntu-22.04-arm` ARM64 runners. This publishes AppImage and portable archive
assets for both architectures without CPU emulation.
On a native x86-64 or ARM64 Docker-capable development machine, run
`./packaging/build-compatible.sh`. The script selects the matching Ubuntu 22.04
container and refuses accidental CPU emulation.
