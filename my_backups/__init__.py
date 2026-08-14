"""VaultLeaf Backup — easy restic/rclone backup manager (GTK4).

A native GNOME-style GUI that can configure persistent storage and schedules,
run backups, browse snapshots/logs, restore files, and edit exclusions.
"""
import gi

gi.require_version("Gtk", "4.0")

__version__ = "2.1.0"
