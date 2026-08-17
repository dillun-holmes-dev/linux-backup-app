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
        # Instantiate the real application so GTK/GIO API incompatibilities
        # fail the release build instead of failing on a user's desktop.
        from .app import BackupApplication
        application = BackupApplication()
        application.cache.stop()
        print("VaultLeaf bundled runtime: OK")
        sys.exit(0)
    if "--ui-test" in sys.argv:
        from .app import BackupApplication, BackupWindow, _set_linux_identity
        from .tray import load_icon_pixmaps
        _set_linux_identity()
        application = BackupApplication()
        if not application.register():
            raise RuntimeError("Could not register the GTK application")
        window = BackupWindow(application)
        if not load_icon_pixmaps():
            raise RuntimeError("Could not render the tray icon")
        window.destroy()
        application.cache.stop()
        print("VaultLeaf GTK interface: OK")
        sys.exit(0)
    from .app import main
    sys.exit(main())
