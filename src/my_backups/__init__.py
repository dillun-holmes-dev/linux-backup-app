"""VaultLeaf Backup — easy restic/rclone backup manager (GTK4).

A native GNOME-style GUI that can configure persistent storage and schedules,
run backups, browse snapshots/logs, restore files, and edit exclusions.
"""
import gi

from .metadata import VERSION

gi.require_version("Gtk", "4.0")

__version__ = VERSION
