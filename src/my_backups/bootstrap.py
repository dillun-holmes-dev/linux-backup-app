"""Promote a downloaded AppImage to VaultLeaf's single stable location."""
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from .metadata import APP_ID, VERSION


INSTALL_DIR = Path.home() / ".local" / "lib" / "vaultleaf-backup"
INSTALLED_APPIMAGE = INSTALL_DIR / "VaultLeafBackup.AppImage"


def _version_tuple(value):
    """Return a comparable numeric version without requiring packaging."""
    return tuple(int(part) for part in re.findall(r"\d+", value)[:4])


def appimage_version(path):
    """Read a VaultLeaf AppImage version, returning an empty tuple on failure."""
    try:
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, timeout=20,
            env=_clean_appimage_environment())
        match = re.search(r"(\d+(?:\.\d+)+)", result.stdout + result.stderr)
        return _version_tuple(match.group(1)) if match else ()
    except (OSError, subprocess.SubprocessError):
        return ()


def _clean_appimage_environment():
    """Do not pass the currently mounted AppImage runtime into another one."""
    env = os.environ.copy()
    system_ld = env.pop("VAULTLEAF_SYSTEM_LD_LIBRARY_PATH", "")
    system_xdg = env.pop("VAULTLEAF_SYSTEM_XDG_DATA_DIRS", "")
    for name in ("APPIMAGE", "APPDIR", "ARGV0", "OWD", "LD_LIBRARY_PATH", "PYTHONHOME",
                 "PYTHONPATH", "GI_TYPELIB_PATH", "GIO_EXTRA_MODULES",
                 "GTK_PATH", "GDK_PIXBUF_MODULEDIR", "GDK_PIXBUF_MODULE_FILE"):
        env.pop(name, None)
    if system_ld:
        env["LD_LIBRARY_PATH"] = system_ld
    if system_xdg:
        env["XDG_DATA_DIRS"] = system_xdg
    return env


def promote_appimage(source, installed=INSTALLED_APPIMAGE):
    """Atomically install *source* and return the executable that should run."""
    source = Path(source).expanduser().resolve()
    installed = Path(installed).expanduser()
    try:
        if source == installed.resolve():
            return installed, False
    except OSError:
        pass

    installed.parent.mkdir(parents=True, exist_ok=True)
    current_version = appimage_version(installed) if installed.is_file() else ()
    incoming_version = _version_tuple(VERSION)
    if current_version and current_version >= incoming_version:
        return installed, False

    temporary = installed.with_name(f".{installed.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(temporary, installed)
    finally:
        temporary.unlink(missing_ok=True)
    return installed, True


def remove_downloaded_copies(keep=INSTALLED_APPIMAGE):
    """Remove only downloaded VaultLeaf AppImages after stable installation."""
    downloads = Path.home() / "Downloads"
    removed = []
    if not downloads.is_dir():
        return removed
    keep = Path(keep).resolve()
    for candidate in downloads.glob("VaultLeafBackup*.AppImage"):
        try:
            if candidate.resolve() != keep and candidate.is_file():
                candidate.unlink()
                removed.append(candidate)
        except OSError:
            continue
    return removed


def _quit_existing_instance():
    """Ask an older running build to release the shared application ID."""
    try:
        from gi.repository import Gio
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        path = "/" + APP_ID.replace(".", "/")
        actions = Gio.DBusActionGroup.get(connection, APP_ID, path)
        actions.activate_action("quit-from-tray", None)
        # Give GTK a brief moment to release the bus name. A later activation
        # remains safe even when no old instance existed.
        time.sleep(0.35)
    except Exception:
        pass


def handoff_to_installed_appimage():
    """Install a downloaded AppImage, then replace this process with it."""
    source = os.environ.get("APPIMAGE")
    if not source:
        return False
    source_path = Path(source).expanduser().resolve()
    target, changed = promote_appimage(source_path)
    try:
        already_installed = source_path == target.resolve()
    except OSError:
        already_installed = False
    if already_installed:
        return False
    if changed:
        _quit_existing_instance()
    remove_downloaded_copies(target)
    env = _clean_appimage_environment()
    os.execve(str(target), [str(target), *sys.argv[1:]], env)
    return True
