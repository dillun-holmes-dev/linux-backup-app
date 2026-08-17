# Contributing to Linux Backup App

Thanks for wanting to help! This project is community-driven, but it is a
**single-maintainer project**: all changes land on `main` only through
pull requests that the maintainer reviews and merges.

## Ways to contribute

Everyone is welcome — from first-time contributors to seasoned maintainers.
**No contribution is too small.**

- 🐛 **Report a bug** — open an issue using the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml)
- 💭 **Suggest a feature or idea** — open an issue with the [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml)
- 📖 **Improve the docs** — README, this file, comments.
- 🔧 **Fix something or add a feature** — fork, branch, and open a pull request.
- 💬 **Help triage** — reproduce bugs, answer questions, or clarify issues.

A typo fix, a clearer error message, or a well-written bug report all count.

## Your first pull request

1. **Fork** the repo (button at the top-right of the GitHub page).
2. **Clone** your fork and create a branch:
   ```sh
   git clone https://github.com/<your-username>/linux-backup-app.git
   cd linux-backup-app
   git checkout -b fix/my-improvement
   ```
3. Make your change and **commit** it with a clear message.
4. **Push** the branch to your fork and **open a pull request** against `main`.
5. The maintainer reviews and merges it. That's it! 🎉

New to this? A well-explained pull request beats a perfect one — questions in
the PR description are always welcome.

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

This is a GTK4 Python app (`src/my_backups/`). Running from source:

```sh
PYTHONPATH=src python3 -m my_backups
```

It shells out to **restic** and **rclone**, which must be installed and
reachable. See the README for the AppImage build (packaging/).

## Code style

- Python 3.10+, PEP 8, type hints on new public functions.
- Keep GTK UI code in `src/my_backups/pages/`; keep shelling/backup logic in
  `src/my_backups/backend.py`.
- Prefer small, readable functions over clever one-liners.

## Reporting issues

When opening an issue, include:

- App version (from `--version` / package) and your distro.
- Steps to reproduce.
- Expected vs. actual behavior.
- Any relevant log output (sanitize secrets/credentials first).

## License & legal

This project is licensed under the [Apache License 2.0](LICENSE). By
submitting a pull request or issue, you agree that your contributions are
provided under the same license.
