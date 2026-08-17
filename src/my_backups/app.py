"""VaultLeaf Backup — GTK4 application shell.

Main window with a native sidebar (StackSidebar) and five pages:
Setup, Overview, Backups & logs, Restore, and Settings. A 1 s timer refreshes the
visible page from the backend so progress is always live.
"""
import ctypes
import sys
import threading
import time
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk

from . import backend as B
from . import updates
from .pages.backups import BackupsPage
from .pages.overview import OverviewPage
from .pages.restore import RestorePage
from .pages.setup import SetupPage
from .pages.settings import SettingsPage
from .tray import TrayIcon
from .metadata import APP_ICON, APP_ID, APP_NAME, EXECUTABLE_NAME


def _set_linux_identity():
    """Give launchers, docks, and process viewers one consistent identity."""
    GLib.set_prgname(EXECUTABLE_NAME)
    GLib.set_application_name(APP_NAME)
    Gtk.Window.set_default_icon_name(APP_ICON)
    try:
        # Linux limits the task name to 15 visible bytes.
        ctypes.CDLL(None).prctl(15, b"VaultLeaf", 0, 0, 0)
    except (AttributeError, OSError):
        pass


def _leaf_image():
    """Build the leaf logo without depending on host image-loader plugins."""
    pixels = (Path(__file__).parent / "data" / "icon-64.rgba").read_bytes()
    if len(pixels) != 64 * 64 * 4:
        raise RuntimeError("The bundled leaf icon pixels are invalid")
    texture = Gdk.MemoryTexture.new(
        64, 64, Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(pixels), 64 * 4)
    return Gtk.Image.new_from_paintable(texture)


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
        brand = _leaf_image()
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
        menu.append("Shut down backup services", "app.shutdown-services")
        menu.append("Resume backup services", "app.resume-services")
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
        # flags defaults to 0 (G_APPLICATION_FLAGS_NONE) — valid on every
        # GLib version; DEFAULT_FLAGS was removed from newer typelibs.
        super().__init__(application_id=APP_ID)
        self.cfg = B.load_config()
        self.cache = B.Cache(self.cfg)
        self.window = None
        self.tray = None
        self.tray_window = None
        self._background_start = False
        self._last_integrity = None
        self._held = False
        self._tick_count = 0
        self._resume_scan_running = False
        self._resume_attempts = {}
        self._resume_after = {}
        self.add_main_option("background", 0, GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, "Start hidden in the tray", None)

    def do_handle_local_options(self, options):
        self._background_start = options.contains("background")
        return -1

    def do_startup(self):
        Gtk.Application.do_startup(self)
        try:
            B.ensure_desktop_identity()
        except OSError:
            # A restricted home must not prevent the application opening.
            pass
        self.hold()
        self._held = True
        self.cache.start()
        self._add_action("refresh", lambda: self.window and self.window.refresh_all())
        self._add_action("run-daily", lambda: self.run_backup("daily"))
        self._add_action("run-weekly", lambda: self.run_backup("weekly"))
        self._add_action("run-monthly", lambda: self.run_backup("monthly"))
        self._add_action("run-integrity", self._run_integrity)
        self._add_action("open-drive", lambda: B.open_folder(self.cfg["drive_dir"]))
        self._add_action("change-storage", lambda: self._open_setup(1))
        self._add_action("change-schedule", lambda: self._open_setup(3))
        self._add_action("open-settings", lambda: self._open_page("settings"))
        self._add_action("show", self.show_main_window)
        self._add_action("tray-controller", self.show_tray_controller)
        self._add_action("quit-from-tray", self._quit_from_tray)
        self._add_action("shutdown-services", self._shutdown_services)
        self._add_action("resume-services", self._resume_services)

    def do_activate(self):
        if self.window is None:
            self.window = BackupWindow(self)
            self.add_window(self.window)
            self.tray = TrayIcon(self)
            GLib.timeout_add_seconds(30, self.tray.retry_registration)
            threading.Thread(target=self._start_portable_services, daemon=True).start()
            threading.Thread(target=self._check_available_update, daemon=True).start()
            threading.Thread(target=self._self_heal, daemon=True).start()
            if not self._background_start:
                self.window.present()
            GLib.timeout_add(1000, self._tick)
        else:
            if not self._background_start:
                self.window.present()
        self._background_start = False

    def _start_portable_services(self):
        try:
            migrated = B.migrate_existing_setup(self.cfg)
            if migrated:
                GLib.idle_add(self._existing_setup_notice)
        except OSError:
            pass
        B.ensure_portable_mount(self.cfg)
        B.run_portable_schedule(self.cfg)
        self._resume_interrupted_backups()

    def _self_heal(self):
        try:
            repaired = B.self_heal(self.cfg)
        except Exception:
            return
        if repaired and self.window is not None:
            GLib.idle_add(self.window.toast,
                          "VaultLeaf repaired automatically: " + "; ".join(repaired))

    def _existing_setup_notice(self):
        text = ("Your existing backup plan was found and is ready. "
                "You do not need to set it up again.")
        if self.window is not None and self.window.get_visible():
            self.window.toast(text)
        notice = Gio.Notification.new("Existing VaultLeaf setup loaded")
        notice.set_body(text)
        notice.add_button("Open VaultLeaf", "app.show")
        self.send_notification("existing-setup-loaded", notice)
        return False

    def _check_available_update(self):
        try:
            release = updates.check_latest_release()
            if updates.is_newer(release.version):
                GLib.idle_add(self._notify_available_update, release.version)
        except Exception:
            pass

    def _notify_available_update(self, version):
        notice = Gio.Notification.new(f"VaultLeaf {version} is available")
        notice.set_body("Open Settings to download and verify the update.")
        notice.add_button("Open Settings", "app.open-settings")
        self.send_notification("update-available", notice)
        return False

    def _tick(self):
        self._tick_count += 1
        if self.window is not None and self.window.get_visible():
            self.window.refresh_all()
        if self._tick_count % 30 == 0:
            B.run_portable_schedule(self.cfg)
        if self._tick_count % 60 == 0:
            threading.Thread(target=B.ensure_portable_mount,
                             args=(self.cfg,), daemon=True).start()
            self._schedule_resume_scan()
        self._check_integrity()
        return True

    def _schedule_resume_scan(self):
        if self._resume_scan_running or not self.cfg.get("setup_complete"):
            return
        self._resume_scan_running = True

        def scan():
            try:
                self._resume_interrupted_backups()
            finally:
                self._resume_scan_running = False
        threading.Thread(target=scan, daemon=True).start()

    def _resume_interrupted_backups(self):
        """Resume one interrupted job at a time, retrying until it completes."""
        if not self.cfg.get("setup_complete"):
            return
        services = self.cfg.get("services", {})
        running = {key: B.service_running(svc, self.cfg)
                   for key, svc in services.items()}
        if any(running.values()):
            return
        now = time.monotonic()
        for key in ("daily", "weekly", "monthly"):
            if key not in services:
                continue
            if not B.backup_incomplete(self.cfg, key, running=False):
                was_resuming = self._resume_attempts.pop(key, None) is not None
                self._resume_after.pop(key, None)
                if was_resuming:
                    GLib.idle_add(self._automatic_resume_complete, key)
                continue
            if now < self._resume_after.get(key, 0):
                continue
            attempt = self._resume_attempts.get(key, 0) + 1
            # Retry quickly once, then back off to avoid hammering unavailable
            # storage while still continuing automatically until completion.
            delay = min(1800, (60, 300, 900, 1800)[min(attempt - 1, 3)])
            self._resume_attempts[key] = attempt
            self._resume_after[key] = now + delay

            def started(ok, message, backup_key=key):
                GLib.idle_add(self._automatic_resume_notice,
                              backup_key, ok, message)
            B.start_backup(self.cfg, key, on_done=started)
            return

    def _automatic_resume_notice(self, key, ok, message):
        if ok:
            text = (f"Continuing the interrupted {key} backup automatically. "
                    "VaultLeaf will keep retrying until it finishes.")
            notice = Gio.Notification.new("Interrupted backup is continuing")
            notice.set_body(text)
            notice.add_button("Open VaultLeaf", "app.show")
            self.send_notification(f"resume-{key}", notice)
            if self.window is not None and self.window.get_visible():
                self.window.toast(text)
        elif self.window is not None and self.window.get_visible():
            self.window.toast(
                f"Could not continue {key} yet. VaultLeaf will retry. {message}",
                "error")
        return False

    def _automatic_resume_complete(self, key):
        text = f"The interrupted {key} backup finished successfully."
        notice = Gio.Notification.new("Backup recovery complete")
        notice.set_body(text)
        notice.add_button("Open VaultLeaf", "app.show")
        self.send_notification(f"resume-{key}", notice)
        if self.window is not None and self.window.get_visible():
            self.window.toast(text)
        return False

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

    def _open_page(self, name):
        self.show_main_window()
        if self.window is not None:
            self.window.stack.set_visible_child_name(name)
        return False

    def show_tray_controller(self):
        if self.tray_window is not None:
            self.tray_window.present()
            return False
        win = Gtk.ApplicationWindow(application=self, title="VaultLeaf — Background")
        win.set_default_size(340, 300)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.append(Gtk.Label(label="VaultLeaf Backup is running in the background.", wrap=True))
        open_btn = Gtk.Button(label="Open VaultLeaf Backup")
        open_btn.connect("clicked", lambda *_: self.show_main_window())
        shutdown_btn = Gtk.Button(label="Shut down backup services completely")
        shutdown_btn.add_css_class("destructive-action")
        shutdown_btn.connect("clicked", lambda *_: self._shutdown_services())
        resume_btn = Gtk.Button(label="Resume backup services")
        resume_btn.connect("clicked", lambda *_: self._resume_services())
        quit_btn = Gtk.Button(label="Quit background app")
        quit_btn.add_css_class("destructive-action")
        quit_btn.connect("clicked", lambda *_: self._quit_from_tray())
        box.append(open_btn)
        box.append(shutdown_btn)
        box.append(resume_btn)
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

    def _shutdown_services(self):
        def work():
            try:
                B.shutdown_services(self.cfg)
                ok, message = True, "All backup services stopped. Schedules are paused."
            except Exception as exc:  # noqa: BLE001
                ok, message = False, f"Could not stop services: {exc}"
            GLib.idle_add(self._services_changed, ok, message)
        threading.Thread(target=work, daemon=True).start()

    def _resume_services(self):
        def work():
            try:
                resumed = B.resume_services(self.cfg)
                ok, message = ((True, "Backup services resumed.")
                               if resumed else (False, "Services were not stopped."))
            except Exception as exc:  # noqa: BLE001
                ok, message = False, f"Could not resume services: {exc}"
            GLib.idle_add(self._services_changed, ok, message)
        threading.Thread(target=work, daemon=True).start()

    def _services_changed(self, ok, message):
        if self.tray_window is not None:
            self.tray_window.destroy()
        if self.window is not None:
            self.window.refresh_all()
            GLib.idle_add(self.window.toast, message, "info" if ok else "error")

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

    def run_backup(self, key):
        # start_backup checks active services in its worker thread; inspecting
        # the saved state here therefore cannot stall the GTK event loop.
        continuing = B.backup_incomplete(self.cfg, key, running=False)
        def on_done(ok, msg):
            if self.window is not None:
                if ok and continuing:
                    msg = (f"Continuing the {key} backup. Already uploaded data "
                           "will be reused safely.")
                GLib.idle_add(self.window.toast, msg, "error" if not ok else "info")
        B.start_backup(self.cfg, key, on_done=on_done)

    def verify_replica(self, key):
        def on_done(ok, message):
            if self.window is not None:
                GLib.idle_add(self.window.toast, message,
                              "error" if not ok else "info")
        B.verify_replica(self.cfg, key, on_done=on_done)

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
    _set_linux_identity()
    app = BackupApplication()
    return app.run(sys.argv)
