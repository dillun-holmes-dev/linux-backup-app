"""Backups page: daily/weekly/monthly snapshots and live logs."""
from gi.repository import Gtk

from .. import backend as B


class BackupsPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.app = app
        self.cfg = app.cfg
        self.cache = app.cache
        self._snapcount = {}
        self._last_log = ""
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        nb = Gtk.Notebook()
        nb.set_hexpand(True)
        nb.set_vexpand(True)
        self.append(nb)

        self.lists = {}
        for key, label in (("daily", "Daily snapshots"), ("weekly", "Weekly snapshots"),
                           ("monthly", "Monthly snapshots")):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(8)
            box.set_margin_end(8)

            header = Gtk.Label(label="", xalign=0)
            header.add_css_class("dim-label")
            box.append(header)

            sw = Gtk.ScrolledWindow()
            sw.set_vexpand(True)
            lb = Gtk.ListBox()
            lb.set_selection_mode(Gtk.SelectionMode.NONE)
            sw.set_child(lb)
            box.append(sw)

            nb.append_page(box, Gtk.Label(label=label))
            self.lists[key] = (header, lb)

        logbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        logbox.set_margin_top(8)
        logbox.set_margin_bottom(8)
        logbox.set_margin_start(8)
        logbox.set_margin_end(8)
        self.logview = Gtk.TextView()
        self.logview.set_editable(False)
        self.logview.set_monospace(True)
        self.logview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw2 = Gtk.ScrolledWindow()
        sw2.set_vexpand(True)
        sw2.set_child(self.logview)
        logbox.append(sw2)
        nb.append_page(logbox, Gtk.Label(label="Logs"))

    # ------------------------------------------------------------- updates
    def refresh(self):
        for key, (header, lb) in self.lists.items():
            snaps = self.cache.snapshots.get(key) or []
            header.set_label(f"{key.title()} — {len(snaps)} snapshot(s)")
            if self._snapcount.get(key) != len(snaps):
                while (row := lb.get_first_child()) is not None:
                    lb.remove(row)
                for s in snaps:
                    row = Gtk.Label(
                        label=f"  {s['time']}   {s['id']}   {s['paths']}", xalign=0)
                    lb.append(row)
                self._snapcount[key] = len(snaps)

        dtail = "\n".join(B.tail(self.cfg["daily_log"], 8192))
        wtail = "\n".join(B.tail(self.cfg["weekly_log"], 8192))
        mtail = "\n".join(B.tail(self.cfg.get("monthly_log", ""), 8192))
        itail = "\n".join(B.tail(self.cfg.get("integrity_log", ""), 8192))
        combined = (f"===== DAILY =====\n{dtail}\n\n===== WEEKLY =====\n{wtail}"
                    f"\n\n===== MONTHLY =====\n{mtail}"
                    f"\n\n===== INTEGRITY =====\n{itail}")
        if combined != self._last_log:
            self.logview.get_buffer().set_text(combined)
            self._last_log = combined
