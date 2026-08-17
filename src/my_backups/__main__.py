"""Entry point: python3 -m my_backups"""
import sys

from . import __version__

if __name__ == "__main__":
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"VaultLeaf Backup {__version__}")
        sys.exit(0)
    if "--uninstall" in sys.argv:
        from .backend import uninstall_application
        print(uninstall_application())
        sys.exit(0)
    if "--self-test" in sys.argv:
        from pathlib import Path
        import os
        from gi.repository import Gtk
        bundled = Path(os.environ.get("VAULTLEAF_BUNDLED_BIN", ""))
        if Gtk.get_major_version() != 4:
            raise RuntimeError("Bundled GTK4 is unavailable")
        for command in ("restic", "rclone", "minisign"):
            if not (bundled / command).is_file():
                raise RuntimeError(f"Bundled {command} is unavailable")
        print("VaultLeaf bundled runtime: OK")
        sys.exit(0)
    from .app import main
    sys.exit(main())
