"""Friendly, overwrite-safe restore assistant."""
from datetime import datetime
from pathlib import Path
import threading

from gi.repository import GLib, Gtk

from .. import backend as B

_REPOS = (("daily", "Recent backups"),
          ("weekly", "Weekly history"),
          ("monthly", "Monthly archive"))


class RestorePage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.app = app
        self.cfg = app.cfg
        self.cache = app.cache
        self._job = None
        self._snapshots = []
        self._last_percent = None
        self._final_target = None
        self.set_margin_top(14)
        self.set_margin_bottom(14)
        self.set_margin_start(18)
        self.set_margin_end(18)
        self._build()

    @staticmethod
    def _frame(title):
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        frame.set_child(box)
        return frame, box

    def _build(self):
        title = Gtk.Label(label="Restore your files", xalign=0)
        title.add_css_class("title-1")
        self.append(title)
        intro = Gtk.Label(
            label="Recover a lost or older file safely. VaultLeaf restores into a new folder "
                  "by default, so it will not replace your current files.",
            xalign=0, wrap=True)
        intro.set_margin_bottom(12)
        self.append(intro)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_end(8)
        scroller.set_child(content)

        backup_frame, backup = self._frame("1. Choose a backup")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(Gtk.Label(label="History", xalign=0))
        self.repo_dd = Gtk.DropDown(model=Gtk.StringList(
            strings=[label for _, label in _REPOS]))
        self.repo_dd.connect("notify::selected", lambda *_: self._refresh_snapshots(True))
        row.append(self.repo_dd)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self._refresh_snapshots(True))
        row.append(refresh)
        backup.append(row)
        self.snap_dd = Gtk.DropDown()
        self.snap_dd.set_hexpand(True)
        self.snap_dd.connect("notify::selected", self._snapshot_changed)
        backup.append(self.snap_dd)
        self.snapshot_info = Gtk.Label(label="", xalign=0, wrap=True)
        self.snapshot_info.add_css_class("dim-label")
        backup.append(self.snapshot_info)
        content.append(backup_frame)

        files_frame, files = self._frame("2. Choose what to recover")
        self.everything = Gtk.CheckButton(label="Restore everything from this backup")
        self.everything.set_active(True)
        self.selected_only = Gtk.CheckButton(label="Restore only one original file or folder")
        self.selected_only.set_group(self.everything)
        self.everything.connect("toggled", self._restore_mode_changed)
        files.append(self.everything)
        files.append(self.selected_only)
        self.include_entry = Gtk.Entry()
        self.include_entry.set_placeholder_text(
            f"Original path, for example {Path.home() / 'Documents' / 'report.pdf'}")
        self.include_entry.set_sensitive(False)
        files.append(self.include_entry)
        hint = Gtk.Label(
            label="Tip: enter the path the item had when it was backed up. Restoring everything "
                  "is the easiest choice if you are unsure.", xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        files.append(hint)
        content.append(files_frame)

        target_frame, target = self._frame("3. Choose where recovered files go")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.target_entry = Gtk.Entry()
        self.target_entry.set_text(str(Path.home() / "Restored Files"))
        self.target_entry.set_hexpand(True)
        row.append(self.target_entry)
        browse = Gtk.Button(label="Browse…")
        browse.connect("clicked", self._browse_target)
        row.append(browse)
        target.append(row)
        self.safe_folder = Gtk.CheckButton(
            label="Create a new dated folder (recommended — prevents overwriting)")
        self.safe_folder.set_active(True)
        target.append(self.safe_folder)
        content.append(target_frame)

        self.progress_frame, progress_box = self._frame("Restore progress")
        self.progress_frame.set_visible(False)
        self.progress = Gtk.ProgressBar(show_text=True)
        progress_box.append(self.progress)
        self.status_lbl = Gtk.Label(label="", xalign=0, wrap=True)
        progress_box.append(self.status_lbl)
        self.output_expander = Gtk.Expander(label="Technical details")
        self.outbuf = Gtk.TextBuffer()
        self.outview = Gtk.TextView(buffer=self.outbuf)
        self.outview.set_editable(False)
        self.outview.set_monospace(True)
        output_scroll = Gtk.ScrolledWindow()
        output_scroll.set_min_content_height(130)
        output_scroll.set_child(self.outview)
        self.output_expander.set_child(output_scroll)
        progress_box.append(self.output_expander)
        content.append(self.progress_frame)
        self.append(scroller)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(10)
        self.restore_btn = Gtk.Button(label="Review restore")
        self.restore_btn.add_css_class("suggested-action")
        self.restore_btn.connect("clicked", self._review_restore)
        self.cancel_btn = Gtk.Button(label="Cancel restore")
        self.cancel_btn.add_css_class("destructive-action")
        self.cancel_btn.set_visible(False)
        self.cancel_btn.connect("clicked", self._cancel_restore)
        self.open_btn = Gtk.Button(label="Open recovered files")
        self.open_btn.set_visible(False)
        self.open_btn.connect("clicked", lambda *_: B.open_folder(self._final_target))
        footer.append(self.restore_btn)
        footer.append(self.cancel_btn)
        footer.append(self.open_btn)
        self.append(footer)
        self._refresh_snapshots()

    def _repo_key(self):
        idx = self.repo_dd.get_selected()
        return _REPOS[idx][0] if 0 <= idx < len(_REPOS) else "daily"

    def _refresh_snapshots(self, force=False):
        key = self._repo_key()
        snaps = [] if force else (self.cache.snapshots.get(key) or [])
        if snaps:
            self._show_snapshots(snaps)
            return
        self.snapshot_info.set_label("Loading available backups…")
        self.restore_btn.set_sensitive(False)
        threading.Thread(target=self._load_snapshots, args=(key,), daemon=True).start()

    def _load_snapshots(self, key):
        try:
            snaps = B.get_snapshots(self.cfg, self.cfg["repos"][key])
        except Exception:
            snaps = []
        GLib.idle_add(self._snapshots_loaded, key, snaps)

    def _snapshots_loaded(self, key, snaps):
        self.cache.snapshots[key] = snaps
        if key == self._repo_key():
            self._show_snapshots(snaps)
        return False

    def _show_snapshots(self, snaps):
        self._snapshots = snaps
        labels = []
        for snap in snaps:
            try:
                when = datetime.strptime(snap["time"], "%Y-%m-%d %H:%M:%S")
                friendly = when.strftime("%A, %d %B %Y at %H:%M")
            except ValueError:
                friendly = snap["time"]
            labels.append(friendly)
        self.snap_dd.set_model(Gtk.StringList(strings=labels))
        self.snap_dd.set_selected(0 if snaps else Gtk.INVALID_LIST_POSITION)
        self.restore_btn.set_sensitive(bool(snaps))
        self.snapshot_info.set_label(
            "No backups found in this history yet." if not snaps else "")
        self._snapshot_changed()

    def _snapshot_changed(self, *_args):
        idx = self.snap_dd.get_selected()
        if 0 <= idx < len(self._snapshots):
            snap = self._snapshots[idx]
            self.snapshot_info.set_label(
                f"Original location: {snap.get('paths') or 'your backup folder'}  •  "
                f"Snapshot ID: {snap['id'][:8]}")

    def _restore_mode_changed(self, *_args):
        self.include_entry.set_sensitive(self.selected_only.get_active())

    def _browse_target(self, _button):
        dialog = Gtk.FileChooserNative(
            title="Choose where to place recovered files", transient_for=self.app.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            accept_label="Choose this folder", cancel_label="Cancel")
        dialog.connect("response", self._target_response)
        dialog.show()

    def _target_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            path = selected.get_path() if selected else None
            if path:
                self.target_entry.set_text(path)
        dialog.destroy()

    def _review_restore(self, _button):
        if self._job is not None:
            return
        idx = self.snap_dd.get_selected()
        if idx < 0 or idx >= len(self._snapshots):
            return self.app.window.toast("Choose a backup first.", "error")
        base = self.target_entry.get_text().strip()
        include = self.include_entry.get_text().strip() if self.selected_only.get_active() else ""
        if not base:
            return self.app.window.toast("Choose a restore destination.", "error")
        if self.selected_only.get_active() and not include:
            return self.app.window.toast("Enter the original file or folder path.", "error")
        snap = self._snapshots[idx]
        try:
            target = B.prepare_restore_target(
                base, snap["time"], self.safe_folder.get_active())
        except (OSError, ValueError) as exc:
            return self.app.window.toast(f"Cannot use that destination: {exc}", "error")
        self._pending = (snap, target, include or None)
        safe = self.safe_folder.get_active()
        dialog = Gtk.MessageDialog(
            transient_for=self.app.window, modal=True,
            message_type=(Gtk.MessageType.QUESTION if safe else Gtk.MessageType.WARNING),
            buttons=Gtk.ButtonsType.NONE,
            text="Ready to recover your files?")
        what = include if include else "Everything in the selected backup"
        safety = ("Your current files are not changed." if safe else
                  "Warning: files with matching names in this folder may be replaced.")
        dialog.format_secondary_text(
            f"Recover: {what}\nPlace files in: {target}\n\n{safety}")
        dialog.add_button("Go back", Gtk.ResponseType.CANCEL)
        start = dialog.add_button("Start restore", Gtk.ResponseType.ACCEPT)
        start.add_css_class("suggested-action")
        dialog.connect("response", self._confirm_restore)
        dialog.present()

    def _confirm_restore(self, dialog, response):
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        snap, target, include = self._pending
        self.outbuf.set_text("")
        self.progress.set_fraction(0.0)
        self.progress.set_text("Starting…")
        self._last_percent = 0.0
        self._final_target = target
        self.restore_btn.set_visible(False)
        self.open_btn.set_visible(False)
        self.cancel_btn.set_visible(True)
        self.progress_frame.set_visible(True)
        self.status_lbl.set_label("Recovering files. You may keep using VaultLeaf.")
        self._job = B.RestoreJob(
            self.cfg, self.cfg["repos"][self._repo_key()], snap["id"], target, include)
        self._job.start()

    def _cancel_restore(self, _button):
        if self._job is not None:
            self._job.cancel()
            self.cancel_btn.set_sensitive(False)
            self.status_lbl.set_label("Stopping the restore safely…")

    def refresh(self):
        job = self._job
        if job is None:
            return
        if job.percent is not None and job.percent != self._last_percent:
            self.progress.set_fraction(job.percent)
            self.progress.set_text(f"{int(job.percent * 100)}% complete")
            self._last_percent = job.percent
        lines = job.snapshot_lines()
        if lines:
            self.outbuf.insert(self.outbuf.get_end_iter(), "\n".join(lines) + "\n")
        if not job.done:
            return
        self._job = None
        self.cancel_btn.set_visible(False)
        self.cancel_btn.set_sensitive(True)
        self.restore_btn.set_visible(True)
        if job.ok:
            self.progress.set_fraction(1.0)
            self.progress.set_text("Restore complete")
            self.status_lbl.set_label("✓ Your recovered files are ready.")
            self.open_btn.set_visible(True)
            self.app.window.toast("Restore complete — your recovered files are ready.")
        elif job.cancelled:
            self.progress.set_text("Restore cancelled")
            self.status_lbl.set_label("Restore cancelled. Partial recovered files may remain.")
        else:
            self.progress.set_text("Restore failed")
            self.status_lbl.set_label(f"Restore failed: {job.error}")
            self.output_expander.set_expanded(True)
            self.app.window.toast(f"Restore failed: {job.error}", "error")
