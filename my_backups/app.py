"""VaultLeaf Backup — GTK4 application shell.

Main window with a native sidebar (StackSidebar) and five pages:
Setup, Overview, Backups & logs, Restore, and Settings. A 1 s timer refreshes the
visible page from the backend so progress is always live.
"""
import sys
import threading
from pathlib import Path

from gi.repository import Gio, GLib, Gtk

from . import backend as B
from .pages.backups import BackupsPage
from .pages.overview import OverviewPage
from .pages.restore import RestorePage
from .pages.setup import SetupPage
from .pages.settings import SettingsPage
from .tray import TrayIcon

APP_ID = "io.mybackups.App"


class BackupWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="VaultLeaf Backup")
        self.app = app
        self.cfg = app.cfg
        self.cache = app.cache
        self.set_default_size(940, 680)
        self._build()
        self.connect("close-request", self._close_requested)

    def _close_requested(self, _window):
        self.hide()
        self.app.background_notice()
        return True

    # ------------------------------------------------------------------ UI
    def _build(self):
        hb = Gtk.HeaderBar()
        brand = Gtk.Image.new_from_file(str(Path(__file__).parent / "data" / "icon.svg"))
        brand.set_pixel_size(28)
        hb.pack_start(brand)
        hb.set_title_widget(Gtk.Label(label="VaultLeaf Backup"))

        menu = Gio.Menu()
        menu.append("Run daily now", "app.run-daily")
        menu.append("Run weekly now", "app.run-weekly")
        menu.append("Run monthly now", "app.run-monthly")
        menu.append("Run integrity check", "app.run-integrity")
        menu.append("Change storage", "app.change-storage")
        menu.append("Change schedule", "app.change-schedule")
        menu.append("Open storage folder", "app.open-drive")
        menu.append("Refresh", "app.refresh")
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        hb.pack_end(mb)
        self.set_titlebar(hb)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)

        pages = [
            (SetupPage(self.app), "setup", "Backup plan", "emblem-system-symbolic"),
            (OverviewPage(self.app), "overview", "Overview", "go-home-symbolic"),
            (BackupsPage(self.app), "backups", "Backups & logs", "folder-symbolic"),
            (RestorePage(self.app), "restore", "Restore", "edit-undo-symbolic"),
            (SettingsPage(self.app), "settings", "Settings", "preferences-system-symbolic"),
        ]
        self._pages = {}
        for widget, name, title, icon in pages:
            self.stack.add_titled(widget, name, title)
            sp = self.stack.get_page(widget)
            sp.set_icon_name(icon)
            self._pages[name] = widget

        self.stack.set_visible_child_name(
            "overview" if self.cfg.get("setup_complete") else "setup")

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.set_size_request(210, -1)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(sidebar)
        paned.set_end_child(self.stack)
        paned.set_position(230)
        paned.set_wide_handle(True)

        # toast-style info bar overlaid on top
        self.infobar = Gtk.InfoBar()
        self.infobar.set_show_close_button(True)
        self.infobar.set_revealed(False)
        self.infobar.connect("response", lambda *_: self.infobar.set_revealed(False))
        self.infobar_label = Gtk.Label(label="")
        self.infobar_label.set_margin_start(10)
        self.infobar_label.set_margin_end(10)
        self.infobar.add_child(self.infobar_label)
        self.infobar.set_valign(Gtk.Align.START)
        self.infobar.set_halign(Gtk.Align.FILL)

        overlay = Gtk.Overlay()
        overlay.set_child(paned)
        overlay.add_overlay(self.infobar)
        self.set_child(overlay)

    # ------------------------------------------------------------- updates
    def refresh_all(self):
        for widget in self._pages.values():
            widget.refresh()

    def toast(self, msg, kind="info"):
        self.infobar_label.set_label(msg)
        self.infobar.set_message_type(
            Gtk.MessageType.ERROR if kind == "error" else Gtk.MessageType.INFO)
        self.infobar.set_revealed(True)
        GLib.timeout_add(6000, self._hide_infobar)

    def open_setup_step(self, step):
        setup = self._pages.get("setup")
        if setup is not None:
            setup.open_step(step)
        self.stack.set_visible_child_name("setup")

    def _hide_infobar(self):
        self.infobar.set_revealed(False)
        return False


class BackupApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.cfg = B.load_config()
        self.cache = B.Cache(self.cfg)
        self.window = None
        self.tray = None
        self.tray_window = None
        self._background_start = False
        self._last_integrity = None
        self._held = False
        self._tick_count = 0
        self.add_main_option("background", 0, GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, "Start hidden in the tray", None)

    def do_handle_local_options(self, options):
        self._background_start = options.contains("background")
        return -1

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        self._held = True
        self.cache.start()
        self._add_action("refresh", lambda: self.window and self.window.refresh_all())
        self._add_action("run-daily", lambda: self._run_backup("daily"))
        self._add_action("run-weekly", lambda: self._run_backup("weekly"))
        self._add_action("run-monthly", lambda: self._run_backup("monthly"))
        self._add_action("run-integrity", self._run_integrity)
        self._add_action("open-drive", lambda: B.open_folder(self.cfg["drive_dir"]))
        self._add_action("change-storage", lambda: self._open_setup(1))
        self._add_action("change-schedule", lambda: self._open_setup(3))
        self._add_action("show", self.show_main_window)
        self._add_action("tray-controller", self.show_tray_controller)
        self._add_action("quit-from-tray", self._quit_from_tray)

    def do_activate(self):
        if self.window is None:
            self.window = BackupWindow(self)
            self.add_window(self.window)
            self.tray = TrayIcon(self)
            GLib.timeout_add_seconds(30, self.tray.retry_registration)
            threading.Thread(target=self._start_portable_services, daemon=True).start()
            if not self._background_start:
                self.window.present()
            GLib.timeout_add(1000, self._tick)
        else:
            if not self._background_start:
                self.window.present()
        self._background_start = False

    def _start_portable_services(self):
        B.ensure_portable_mount(self.cfg)
        B.run_portable_schedule(self.cfg)

    def _tick(self):
        self._tick_count += 1
        if self.window is not None and self.window.get_visible():
            self.window.refresh_all()
        if self._tick_count % 30 == 0:
            B.run_portable_schedule(self.cfg)
        if self._tick_count % 60 == 0:
            threading.Thread(target=B.ensure_portable_mount,
                             args=(self.cfg,), daemon=True).start()
        self._check_integrity()
        return True

    def show_main_window(self):
        if self.window is None:
            self.activate()
        else:
            self.window.present()
        return False

    def _open_setup(self, step):
        self.show_main_window()
        if self.window is not None:
            self.window.open_setup_step(step)
        return False

    def show_tray_controller(self):
        if self.tray_window is not None:
            self.tray_window.present()
            return False
        win = Gtk.ApplicationWindow(application=self, title="VaultLeaf — Background")
        win.set_default_size(320, 140)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.append(Gtk.Label(label="VaultLeaf Backup is running in the background.", wrap=True))
        open_btn = Gtk.Button(label="Open VaultLeaf Backup")
        open_btn.connect("clicked", lambda *_: self.show_main_window())
        quit_btn = Gtk.Button(label="Quit background app")
        quit_btn.add_css_class("destructive-action")
        quit_btn.connect("clicked", lambda *_: self._quit_from_tray())
        box.append(open_btn)
        box.append(quit_btn)
        win.set_child(box)
        win.connect("destroy", self._tray_window_destroyed)
        self.tray_window = win
        win.present()
        return False

    def _tray_window_destroyed(self, *_args):
        self.tray_window = None

    def background_notice(self):
        if self.tray is not None and self.tray.registered_with_watcher:
            return
        notice = Gio.Notification.new("VaultLeaf Backup is still running")
        notice.set_body("Your desktop is hiding tray icons. Open the background controls here.")
        notice.add_button("Open controls", "app.tray-controller")
        self.send_notification("background-status", notice)

    def _quit_from_tray(self):
        if self.tray_window is not None:
            self.tray_window.destroy()
        if self._held:
            self.release()
            self._held = False
        self.quit()
        return False

    def _run_integrity(self):
        def done(ok, message):
            if self.window is not None:
                GLib.idle_add(self.window.toast, message, "info" if ok else "error")
        B.start_integrity_check(self.cfg, done)

    def _check_integrity(self):
        status = B.integrity_status(self.cfg)
        if not status:
            return
        stamp = status.get("checked_at")
        if status.get("ok"):
            if self.tray:
                self.tray.set_attention(False)
            self._last_integrity = stamp
            return
        if stamp == self._last_integrity:
            return
        self._last_integrity = stamp
        if self.tray:
            self.tray.set_attention(True)
        failed = status.get("failed") or "repository"
        notice = Gio.Notification.new("Backup integrity check failed")
        notice.set_body(f"Problem detected in: {failed}. Open VaultLeaf and check the integrity log.")
        notice.add_button("Open VaultLeaf", "app.show")
        self.send_notification("integrity-failed", notice)
        self.show_main_window()
        dialog = Gtk.MessageDialog(
            transient_for=self.window, modal=True, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Backup integrity check failed")
        dialog.format_secondary_text(
            f"A problem was detected in: {failed}. Your backups may need attention. "
            "Open Backups & logs before relying on this repository.")
        dialog.connect("response", lambda dlg, *_: dlg.destroy())
        dialog.present()

    def _run_backup(self, key):
        def on_done(ok, msg):
            if self.window is not None:
                GLib.idle_add(self.window.toast, msg, "error" if not ok else "info")
        B.start_backup(self.cfg, key, on_done=on_done)

    def _add_action(self, name, cb):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_: cb())
        self.add_action(action)

    def do_shutdown(self):
        self.cache.stop()
        if self.tray is not None:
            self.tray.close()
        Gtk.Application.do_shutdown(self)


def main():
    app = BackupApplication()
    return app.run(sys.argv)
