# Security Policy

## Disclaimer / No Liability

VaultLeaf Backup is provided **"as is"**, without warranty of any kind,
express or implied — including, but not limited to, the implied warranties of
merchantability, fitness for a particular purpose, and non-infringement.

No warranty is provided and **no liability is accepted** for any damages,
data loss, security breaches, or other issues arising from the use of this
software. **You are responsible** for the safety and integrity of your own
data and systems.

Before relying on this software for important data:

- Test it in a safe environment first.
- Keep independent, verified backups of anything you cannot afford to lose.
- Review the code yourself and use it at your own risk.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 1.1.x   | Yes       |
| < 1.1   | No        |

## Authentic releases

VaultLeaf release checksum manifests are signed with a dedicated Ed25519
Minisign publisher key. The updater contains that public key and refuses an
update unless the signature is valid before checking the downloaded file's
SHA-256 digest.

GitHub Actions also creates keyless artifact attestations for every AppImage
and portable archive. This records the repository and workflow that produced
the files.

To verify a downloaded release manually:

```sh
minisign -Vm SHA256SUMS-x86_64 \
  -x SHA256SUMS-x86_64.minisig \
  -p src/my_backups/data/vaultleaf-minisign.pub
sha256sum -c SHA256SUMS-x86_64
gh attestation verify VaultLeafBackup-x86_64.AppImage \
  --repo dillun-holmes-dev/linux-backup-app
```

Use `aarch64` instead on ARM64. Minisign and GitHub CLI are needed only for
manual verification; the VaultLeaf AppImage bundles its own verifier.

## Reporting a vulnerability

If you believe you have found a security issue, do not disclose it publicly.
Open the repository's **Security** tab and use **Report a vulnerability**.
The report is visible only to you and the repository maintainers. Include the
affected version, reproduction steps, and potential impact, but never include
passwords, repository keys, backup contents, or other secrets.

This is a community project without a formal security team, so response and
fix timelines cannot be guaranteed.

## Publisher key handling

The private release key is not committed. It is stored as a protected GitHub
Actions secret. The public key in `src/my_backups/data/vaultleaf-minisign.pub`
is intentionally committed and bundled into the app.
