"""Checked updates from the project's GitHub Releases feed."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile
from urllib.request import Request, urlopen

from .metadata import VERSION

REPOSITORY = "dillun-holmes-dev/linux-backup-app"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
USER_AGENT = f"VaultLeaf-Backup/{VERSION}"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    page_url: str
    appimage_name: str
    appimage_url: str
    checksum_url: str


def normalized_arch(machine=None):
    value = (machine or platform.machine()).lower()
    if value in ("x86_64", "amd64"):
        return "x86_64"
    if value in ("aarch64", "arm64"):
        return "aarch64"
    raise RuntimeError(f"Updates are not published for architecture: {value}")


def _version_tuple(value):
    numbers = re.findall(r"\d+", value.lstrip("vV"))
    return tuple(int(number) for number in numbers[:3]) + (0,) * max(0, 3 - len(numbers))


def is_newer(candidate, current=VERSION):
    return _version_tuple(candidate) > _version_tuple(current)


def _request_json(url):
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def check_latest_release():
    payload = _request_json(LATEST_RELEASE_API)
    version = str(payload.get("tag_name", "")).lstrip("vV")
    arch = normalized_arch()
    appimage_name = f"VaultLeafBackup-{arch}.AppImage"
    checksum_name = f"SHA256SUMS-{arch}"
    assets = {item.get("name"): item.get("browser_download_url")
              for item in payload.get("assets", [])}
    if ((appimage_name not in assets or checksum_name not in assets) and
            is_newer(version)):
        raise RuntimeError(f"Release {version or 'unknown'} has no {arch} application")
    return ReleaseInfo(version=version,
                       page_url=payload.get("html_url", ""),
                       appimage_name=appimage_name,
                       appimage_url=assets.get(appimage_name, ""),
                       checksum_url=assets.get(checksum_name, ""))


def _download(url, target):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response, open(target, "wb") as output:
        shutil.copyfileobj(response, output)


def _expected_checksum(text, filename):
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    raise RuntimeError("The release checksum file is invalid")


def install_release(release):
    """Download, verify, and atomically replace the running AppImage."""
    current = os.environ.get("APPIMAGE")
    if not current:
        raise RuntimeError("Updates are available only in the AppImage release")
    target = Path(current).resolve()
    if not os.access(target.parent, os.W_OK):
        raise RuntimeError(f"Cannot update {target}; move it to a writable folder")

    with tempfile.TemporaryDirectory(prefix="vaultleaf-update-",
                                     dir=target.parent) as directory:
        temporary = Path(directory) / release.appimage_name
        checksum_file = Path(directory) / "SHA256SUMS"
        _download(release.appimage_url, temporary)
        _download(release.checksum_url, checksum_file)
        expected = _expected_checksum(checksum_file.read_text(), release.appimage_name)
        hasher = hashlib.sha256()
        with open(temporary, "rb") as downloaded:
            for chunk in iter(lambda: downloaded.read(1024 * 1024), b""):
                hasher.update(chunk)
        actual = hasher.hexdigest()
        if actual != expected:
            raise RuntimeError("Update download failed its SHA-256 verification")
        os.chmod(temporary, 0o755)
        backup = target.with_name(target.name + ".previous")
        if backup.exists():
            backup.unlink()
        os.replace(target, backup)
        try:
            os.replace(temporary, target)
        except Exception:
            os.replace(backup, target)
            raise
    return target
