# Contributing to Linux Backup App

Thanks for wanting to help! This project is community-driven, but it is a
**single-maintainer project**: all changes land on `main` only through
pull requests that the maintainer reviews and merges.

## How contributions work

| Action | Allowed? |
| ------ | -------- |
| Open an issue / report a bug | ✅ Yes |
| Suggest a feature (issue) | ✅ Yes |
| Fork the repo & open a pull request | ✅ Yes |
| Commit directly to `main` | ❌ No — blocked by branch protection |
| Merge your own pull request | ❌ No — PRs need a review approval |

## Rules

1. **Never push directly to `main`.** The branch is protected:
   - Pull requests are required before any change merges.
   - Every pull request needs **at least one approving review**.
   - PR authors cannot approve their own pull request, so you can't self-merge.
   - Force pushes, deletions, and non-linear history are blocked.
2. **Open an issue first** for anything non-trivial (bug, feature, design
   change) so work isn't wasted. Small fixes and typos are fine without one.
3. **Fork → branch → PR.** Work on a descriptive branch (e.g.
   `fix/restore-race`, `feat/smb-encryption`), then open a pull request against
   `main` from your fork.
4. **Keep changes focused.** One logical change per pull request, with a clear
   description of what and why.
5. **Resolve review feedback.** The maintainer (or another reviewer) will
   approve once the change is ready. The maintainer merges the pull request.

## Development setup

This is a GTK4 Python app (`my_backups/`). Running from source:

```sh
python3 -m my_backups
```

It shells out to **restic** and **rclone**, which must be installed and
reachable. See the README for the AppImage build (packaging/).

## Code style

- Python 3.10+, PEP 8, type hints on new public functions.
- Keep GTK UI code in `my_backups/pages/`; keep shelling/backup logic in
  `my_backups/backend.py`.
- Prefer small, readable functions over clever one-liners.

## Reporting issues

When opening an issue, include:

- App version (from `--version` / package) and your distro.
- Steps to reproduce.
- Expected vs. actual behavior.
- Any relevant log output (sanitize secrets/credentials first).
