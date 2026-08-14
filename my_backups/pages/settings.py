"""Settings page: excludes editor, schedule, destinations."""
from pathlib import Path

from gi.repository import Gtk

from .. import backend as B


class SettingsPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.cfg = app.cfg
        self.cache = app.cache
        self.exclude_source_override = None
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.content)
        self.append(scroller)
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Settings", xalign=0)
        title.add_css_class("title-2")
        title.set_hexpand(True)
        back = Gtk.Button(label="Review full backup plan")
        back.connect("clicked", lambda *_: self.app.window.open_setup_step(4))
        heading.append(title)
        heading.append(back)
        self.content.append(heading)

        quick = Gtk.Frame(label="Change your backup plan")
        quick_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        quick_box.set_margin_top(10)
        quick_box.set_margin_bottom(10)
        quick_box.set_margin_start(10)
        quick_box.set_margin_end(10)
        quick_box.append(Gtk.Label(
            label="Change one section without starting over. Existing backups are preserved.",
            xalign=0, wrap=True))
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, step in (("Storage & network", 1), ("Files & speed", 2),
                            ("Automatic schedule", 3)):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _button, value=step:
                           self.app.window.open_setup_step(value))
            buttons.append(button)
        quick_box.append(buttons)
        quick.set_child(quick_box)
        self.content.append(quick)

        # ---- excludes editor ----
        frame = Gtk.Frame(label="Excludes — files & folders skipped in backups")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        self.excl_buf = Gtk.TextBuffer()
        self.excl_buf.set_text(B.get_excludes(self.cfg))
        self.excl_buf.set_modified(False)
        self._loaded_excludes_path = self.cfg.get("excludes_file")
        help_label = Gtk.Label(
            label="Choose files or folders below, or enter one restic exclude pattern per line.",
            xalign=0, wrap=True)
        help_label.add_css_class("dim-label")
        box.append(help_label)
        view = Gtk.TextView(buffer=self.excl_buf)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.set_min_content_height(150)
        sw.set_child(view)
        box.append(sw)

        browse_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_file = Gtk.Button(label="Add files…")
        add_file.connect("clicked", lambda *_: self._browse_excludes(False))
        add_folder = Gtk.Button(label="Add folders…")
        add_folder.connect("clicked", lambda *_: self._browse_excludes(True))
        remove = Gtk.Button(label="Remove selected text")
        remove.connect("clicked", self._remove_selected)
        browse_row.append(add_file)
        browse_row.append(add_folder)
        browse_row.append(remove)
        box.append(browse_row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_btn = Gtk.Button(label="Save excludes")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        self.save_status = Gtk.Label(label="", xalign=0)
        self.save_status.add_css_class("dim-label")
        row.append(save_btn)
        row.append(self.save_status)
        box.append(row)

        frame.set_child(box)
        self.content.append(frame)

        # ---- schedule ----
        sf = Gtk.Frame(label="Next automatic jobs")
        sb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sb.set_margin_top(8)
        sb.set_margin_bottom(8)
        sb.set_margin_start(10)
        sb.set_margin_end(10)
        self.sched_lbl = Gtk.Label(label="loading…", xalign=0)
        sb.append(self.sched_lbl)
        sf.set_child(sb)
        self.content.append(sf)

        # ---- destinations ----
        df = Gtk.Frame(label="Destinations")
        db = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        db.set_margin_top(8)
        db.set_margin_bottom(8)
        db.set_margin_start(10)
        db.set_margin_end(10)
        self.dest_lbl = Gtk.Label(label="", xalign=0)
        db.append(self.dest_lbl)
        df.set_child(db)
        self.content.append(df)

        # ---- actions ----
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        b1 = Gtk.Button(label="Open backup scripts folder")
        b1.connect("clicked", lambda *_: B.open_folder(self.cfg["backup_scripts_dir"]))
        b2 = Gtk.Button(label="Open config folder")
        b2.connect("clicked", self._open_config_folder)
        actions.append(b1)
        actions.append(b2)
        self.content.append(actions)

        note = Gtk.Label(
            label="Config: ~/.config/my-backups/config.json  (advanced use)",
            xalign=0)
        note.add_css_class("dim-label")
        self.content.append(note)

    def _open_config_folder(self, *_args):
        config_dir = Path.home() / ".config" / "my-backups"
        config_dir.mkdir(parents=True, exist_ok=True)
        B.open_folder(str(config_dir))

    # ------------------------------------------------------------- actions
    def _on_save(self, _btn):
        buf = self.excl_buf
        start, end = buf.get_bounds()
        text = buf.get_text(start, end, False)
        try:
            B.save_excludes(self._exclude_cfg(), text)
            self.excl_buf.set_modified(False)
            self.save_status.set_label("✓ saved")
        except Exception as e:  # noqa: BLE001
            self.save_status.set_label(f"✗ {e}")

    def _browse_excludes(self, folders):
        dialog = Gtk.FileChooserNative(
            title="Choose folders to exclude" if folders else "Choose files to exclude",
            transient_for=self.app.window,
            action=(Gtk.FileChooserAction.SELECT_FOLDER if folders
                    else Gtk.FileChooserAction.OPEN),
            accept_label="Add to exclusions", cancel_label="Cancel")
        dialog.set_select_multiple(True)
        dialog.connect("response", self._exclude_response)
        dialog.show()

    def _exclude_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_files()
            paths = []
            for index in range(selected.get_n_items()):
                item = selected.get_item(index)
                path = item.get_path() if item else None
                if path:
                    paths.append(str(Path(path).resolve()))
            self._add_exclude_paths(paths)
        dialog.destroy()

    def _add_exclude_paths(self, paths):
        start, end = self.excl_buf.get_bounds()
        current = self.excl_buf.get_text(start, end, False)
        lines = current.splitlines()
        existing = {line.strip() for line in lines if line.strip()}
        added = 0
        rejected = 0
        source = Path(self.exclude_source_override or
                      self.cfg.get("backup_source", Path.home())).resolve()
        for path in paths:
            candidate = Path(path).resolve()
            if candidate == source or candidate in source.parents:
                rejected += 1
                continue
            if path not in existing:
                lines.append(path)
                existing.add(path)
                added += 1
        if not added:
            self.save_status.set_label(
                "Cannot exclude the whole backup source" if rejected else "Already excluded")
            return
        text = "\n".join(lines).strip() + "\n"
        self.excl_buf.set_text(text)
        try:
            B.save_excludes(self._exclude_cfg(), text)
            self.excl_buf.set_modified(False)
            suffix = f"; skipped {rejected} unsafe selection(s)" if rejected else ""
            self.save_status.set_label(f"✓ added {added} and saved{suffix}")
        except Exception as exc:  # noqa: BLE001
            self.save_status.set_label(f"✗ {exc}")

    def _remove_selected(self, _button):
        bounds = self.excl_buf.get_selection_bounds()
        if not bounds:
            self.save_status.set_label("Select text to remove first")
            return
        start, end = bounds[-2], bounds[-1]
        self.excl_buf.delete(start, end)
        self._on_save(None)

    def _exclude_cfg(self):
        if not self.exclude_source_override:
            return self.cfg
        cfg = dict(self.cfg)
        cfg["backup_source"] = self.exclude_source_override
        return cfg

    # ------------------------------------------------------------- updates
    def refresh(self):
        excludes_path = self.cfg.get("excludes_file")
        if excludes_path != self._loaded_excludes_path and not self.excl_buf.get_modified():
            self.excl_buf.set_text(B.get_excludes(self.cfg))
            self.excl_buf.set_modified(False)
            self._loaded_excludes_path = excludes_path
        timers = self.cache.timers
        if timers:
            self.sched_lbl.set_label(
                "\n".join(f"{name:<11} →  {nxt}" for name, nxt in timers))
        elif self.cfg.get("setup_complete"):
            self.sched_lbl.set_label("No automatic schedules are enabled.")
        repos = "\n".join(f"  {k}: {v}" for k, v in self.cfg["repos"].items())
        storage = self.cfg["drive_dir"]
        if self.cfg.get("storage_mode") == "smb":
            storage += (f"  (SMB smb://{self.cfg.get('smb_host', '')}/"
                        f"{self.cfg.get('smb_share', '')})")
        self.dest_lbl.set_label(
            f"Restic repositories:\n{repos}\n"
            f"Storage folder: {storage}")
