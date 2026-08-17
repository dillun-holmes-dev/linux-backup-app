"""Overview page: live backup progress, Drive space, schedule."""
import time

from gi.repository import Gtk

from .. import backend as B

CARDS = (("daily", "Daily backup"),
         ("weekly", "Weekly backup"),
         ("monthly", "Monthly backup"))


class OverviewPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.cfg = app.cfg
        self.cache = app.cache
        self._prev = {}
        self._rate = {}
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        self.banner = Gtk.Label(label="…", xalign=0)
        self.banner.add_css_class("title-2")
        self.append(self.banner)

        self.cards = {}
        for key, title in CARDS:
            card = Gtk.Frame(label=title)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(10)
            box.set_margin_end(10)

            bar = Gtk.ProgressBar()
            box.append(bar)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label="waiting…", xalign=0)
            lbl.hexpand = True
            speed = Gtk.Label(label="", xalign=1)
            row.append(lbl)
            row.append(speed)
            box.append(row)

            det = Gtk.Label(label="", xalign=0)
            det.add_css_class("dim-label")
            box.append(det)

            action = Gtk.Button(label="Back up now")
            action.set_halign(Gtk.Align.START)
            action.add_css_class("suggested-action")
            action.connect("clicked", lambda _button, backup_key=key:
                           self.app.run_backup(backup_key))
            box.append(action)

            verify = Gtk.Button(label="Verify replica")
            verify.set_halign(Gtk.Align.START)
            verify.connect("clicked", lambda _button, backup_key=key:
                           self.app.verify_replica(backup_key))
            box.append(verify)

            card.set_child(box)
            self.append(card)
            self.cards[key] = {"bar": bar, "lbl": lbl, "det": det,
                               "speed": speed, "action": action,
                               "verify": verify}

        self.info_lbl = Gtk.Label(label="loading…", xalign=0)
        self.info_lbl.add_css_class("dim-label")
        self.append(self.info_lbl)

        self.sched_lbl = Gtk.Label(label="loading…", xalign=0)
        self.sched_lbl.add_css_class("dim-label")
        self.append(self.sched_lbl)

        self.integrity_lbl = Gtk.Label(label="Integrity: not checked yet", xalign=0)
        self.append(self.integrity_lbl)

    # ------------------------------------------------------------- updates
    def refresh(self):
        now = time.time()
        runs = []
        recoveries = []
        for key, svc in self.cfg["services"].items():
            jpath = self.cfg[key + "_json"]
            running = B.service_running(svc, self.cfg)
            st = B.last_status(jpath)
            incomplete = B.backup_incomplete(self.cfg, key, running=running)
            self._update_card(key, st, running, now)
            card = self.cards[key]
            card["action"].set_sensitive(
                bool(self.cfg.get("setup_complete")) and not running)
            image_monthly = (key == "monthly" and
                             self.cfg.get("monthly_mode") == "system_image")
            card["action"].set_label(
                "Continue interrupted backup" if incomplete else
                ("Image system now" if image_monthly else "Back up now"))
            card["verify"].set_sensitive(not image_monthly)
            if (not self.cfg.get("schedule_enabled", {}).get(key, True)
                    and not running and not incomplete):
                card["lbl"].set_label("automatic schedule disabled")
                card["speed"].set_label("")
                card["det"].set_label("Manual backups are still available")
            if running:
                runs.append(key)
            elif incomplete:
                recoveries.append(key)
        if runs:
            rate = sum(self._rate.get(k, 0) for k in runs)
            self.banner.set_label(
                f"● RUNNING: {', '.join(runs).upper()}   ·   {rate / 1e6:.0f} MB/s")
            self.banner.add_css_class("error")
            self.banner.remove_css_class("success")
        elif recoveries:
            self.banner.set_label(
                f"● RECOVERY PENDING — continuing {', '.join(recoveries).upper()} automatically")
            self.banner.add_css_class("error")
            self.banner.remove_css_class("success")
        else:
            self.banner.set_label("● IDLE — next backup is scheduled")
            self.banner.add_css_class("success")
            self.banner.remove_css_class("error")

        about = self.cache.about
        if self.cfg.get("storage_mode") == "folder":
            info = f"Storage folder:  {self.cfg['drive_dir']}"
        elif self.cfg.get("storage_mode") == "smb":
            info = (f"SMB share:  smb://{self.cfg.get('smb_host', '')}/"
                    f"{self.cfg.get('smb_share', '')}\n"
                    f"Available locally at:  {self.cfg['drive_dir']}")
        elif about:
            info = ("Drive:  "
                    f"Total {about.get('total', '…')}   ·   "
                    f"Used {about.get('used', '…')}   ·   "
                    f"Free {about.get('free', '…')}")
        else:
            info = "Google Drive: loading…"
        parts = [f"{key}: {len(self.cache.snapshots.get(key) or [])} snapshot(s)"
                 for key in ("daily", "weekly", "monthly")]
        info += "\n" + "   |   ".join(parts)
        self.info_lbl.set_label(info)

        timers = self.cache.timers
        if timers:
            self.sched_lbl.set_label(
                "Schedule:\n" + "\n".join(f"  {name:<11} →  {nxt}"
                                          for name, nxt in timers))

        integrity = B.integrity_status(self.cfg)
        if (not self.cfg.get("schedule_enabled", {}).get("integrity", True) and
                (not integrity or integrity.get("ok"))):
            self.integrity_lbl.set_label("Integrity: automatic checks disabled")
            self.integrity_lbl.remove_css_class("success")
            self.integrity_lbl.remove_css_class("error")
        elif integrity:
            if not integrity.get("checked", True):
                self.integrity_lbl.set_label("Integrity: waiting for the first backup")
                self.integrity_lbl.remove_css_class("success")
                self.integrity_lbl.remove_css_class("error")
            elif integrity.get("ok"):
                self.integrity_lbl.set_label(
                    f"✓ Integrity check passed — {integrity.get('checked_at')}")
                self.integrity_lbl.add_css_class("success")
                self.integrity_lbl.remove_css_class("error")
            else:
                self.integrity_lbl.set_label(
                    f"✗ Integrity check FAILED — {integrity.get('failed', 'repository')}")
                self.integrity_lbl.add_css_class("error")
                self.integrity_lbl.remove_css_class("success")

    def _update_card(self, key, st, running, now):
        card = self.cards[key]
        prev_t, prev_b = self._prev.get(key, (now, st.get("bytes_done", 0) if st else 0))
        cur_b = st.get("bytes_done", 0) if st else 0
        dt = max(0.001, now - prev_t)
        rate = (cur_b - prev_b) / dt if cur_b >= prev_b else 0.0
        self._prev[key] = (now, cur_b)
        self._rate[key] = rate

        if st is None:
            card["bar"].set_fraction(0.0)
            card["lbl"].set_label("starting…" if running else "waiting for next run")
            card["speed"].set_label("")
            card["det"].set_label("")
        elif st.get("summary"):
            card["bar"].set_fraction(1.0)
            card["lbl"].set_label("✓ complete")
            card["speed"].set_label("")
            card["det"].set_label(
                f"{B.fmt_bytes(st.get('total_bytes_processed', 0))} processed")
        else:
            pct = min(100.0, st.get("percent_done", 0) * 100)
            card["bar"].set_fraction(pct / 100.0)
            card["lbl"].set_label(f"{pct:.2f}%")
            remaining = max(0, st.get("total_bytes", 0) - cur_b)
            if cur_b <= 0:
                card["speed"].set_label("starting…" if running else "")
            elif rate > 0:
                card["speed"].set_label(
                    f"{rate / 1e6:.1f} MB/s  ·  ETA {B.fmt_eta(remaining / rate)}")
            else:
                card["speed"].set_label("—")
            card["det"].set_label(
                f"{st.get('files_done', 0):,}/{st.get('total_files', 0):,} files  ·  "
                f"{B.fmt_bytes(cur_b)} / {B.fmt_bytes(st.get('total_bytes', 0))}")
