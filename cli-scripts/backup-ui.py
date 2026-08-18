#!/usr/bin/env python3
"""
My Backups — Google Drive backup monitor & control.
Shows live speed, ETA, progress, snapshots, Drive space and the schedule.
Refresh every 2s; heavy data (Drive space / snapshots / timers) fetched in the
background so the UI never freezes.
"""
import json
import os
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

HOME_DIR = os.path.expanduser("~")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DAILY_JSON = "/var/tmp/backup-daily.json"
WEEKLY_JSON = "/var/tmp/backup-weekly.json"
DAILY_LOG = "/var/log/backup-daily.log"
WEEKLY_LOG = "/var/log/backup-weekly.log"
MONTHLY_DIR = os.path.join(HOME_DIR, "GoogleDrive", "monthly")
DRIVE_DIR = os.path.join(HOME_DIR, "GoogleDrive")
PWFILE = os.path.join(SCRIPT_DIR, "restic-passphrase.txt")
RCLONE_CONFIG = os.path.join(HOME_DIR, ".config", "rclone", "rclone.conf")

REPOS = {"daily": "rclone:gdrive:daily", "weekly": "rclone:gdrive:weekly"}
SERVICES = {
    "daily": ("backup-daily.service", DAILY_JSON, DAILY_LOG),
    "weekly": ("backup-weekly.service", WEEKLY_JSON, WEEKLY_LOG),
}
TIMERS = {
    "Daily": "backup-daily.timer",
    "Weekly": "backup-weekly.timer",
    "Monthly": "backup-monthly.timer",
    "Integrity": "backup-integrity.timer",
}


def run(cmd, timeout=30):
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = RCLONE_CONFIG
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return (r.stdout + r.stderr).strip()
    except Exception:
        return ""


def tail(path, nbytes=100 * 1024):
    try:
        with open(path, "rb") as f:
            size = os.path.getsize(path)
            f.seek(max(0, size - nbytes))
            return f.read().decode(errors="replace").splitlines()
    except OSError:
        return []


def last_status(path):
    for line in reversed(tail(path)):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        mt = d.get("message_type")
        if mt == "summary":
            return {"summary": True, **d}
        if mt == "status" and "percent_done" in d:
            return d
    return None


def service_running(svc):
    try:
        out = subprocess.run(["systemctl", "is-active", svc],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return out in ("activating", "active")
    except Exception:
        return False


def fmt_bytes(n):
    n = max(0, n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


def fmt_eta(secs):
    if secs is None or secs < 0 or secs != secs:
        return "…"
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


class BackupApp:
    def __init__(self, root):
        self.root = root
        self._stop = False
        self._prev = {}
        self._rate = {}
        self._cache = {"about": None, "snap": None, "timers": None,
                       "t_about": 0, "t_snap": 0, "t_timers": 0}
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh()
        self.root.after(2000, self._auto)
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------- UI ----------
    def _build(self):
        r = self.root
        r.title("My Backups — Google Drive")
        r.geometry("740x700")
        r.minsize(620, 600)

        style = ttk.Style(r)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("", 17, "bold"))
        style.configure("Card.TLabelframe", bordercolor="#cfcfcf")
        style.configure("Card.TLabelframe.Label", font=("", 10, "bold"))
        style.configure("Big.TLabel", font=("", 12, "bold"))

        head = ttk.Frame(r)
        head.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(head, text="My Backups", style="Title.TLabel").pack(side="left")
        self.banner = tk.Label(head, text="…", font=("", 11, "bold"),
                               padx=12, pady=5, bg="#e0e0e0", fg="#333")
        self.banner.pack(side="right")

        self.cards = {}
        for key, title in (("daily", "Daily backup"),
                           ("weekly", "Weekly backup"),
                           ("monthly", "Monthly disk image")):
            card = ttk.LabelFrame(r, text=title, style="Card.TLabelframe")
            card.pack(fill="x", padx=12, pady=4)
            bar = ttk.Progressbar(card, maximum=100)
            bar.pack(fill="x", padx=10, pady=(8, 2))
            row = ttk.Frame(card)
            row.pack(fill="x", padx=10, pady=(0, 2))
            lbl = ttk.Label(row, text="waiting…", style="Big.TLabel")
            lbl.pack(side="left")
            speed = ttk.Label(row, text="", foreground="#007a66", font=("", 10, "bold"))
            speed.pack(side="right")
            det = ttk.Label(card, text="", foreground="#666")
            det.pack(anchor="w", padx=10, pady=(0, 8))
            self.cards[key] = {"bar": bar, "lbl": lbl, "det": det, "speed": speed}

        btns = ttk.Frame(r)
        btns.pack(fill="x", padx=12, pady=6)
        ttk.Button(btns, text="▶  Run daily now", command=lambda: self.launch("daily")).pack(side="left", padx=3)
        ttk.Button(btns, text="▶  Run weekly now", command=lambda: self.launch("weekly")).pack(side="left", padx=3)
        ttk.Button(btns, text="📁  Open Drive folder", command=self.open_drive).pack(side="left", padx=3)
        ttk.Button(btns, text="↻  Refresh", command=self.refresh).pack(side="left", padx=3)

        info = ttk.LabelFrame(r, text="Google Drive", style="Card.TLabelframe")
        info.pack(fill="x", padx=12, pady=4)
        self.info_lbl = ttk.Label(info, text="loading…", justify="left")
        self.info_lbl.pack(anchor="w", padx=10, pady=8)

        sched = ttk.LabelFrame(r, text="Schedule", style="Card.TLabelframe")
        sched.pack(fill="x", padx=12, pady=4)
        self.sched_lbl = ttk.Label(sched, text="loading…", justify="left")
        self.sched_lbl.pack(anchor="w", padx=10, pady=8)

        logf = ttk.LabelFrame(r, text="Recent log", style="Card.TLabelframe")
        logf.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self.log = scrolledtext.ScrolledText(logf, height=6, state="disabled", font=("monospace", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

    # ---------- live update ----------
    def refresh(self):
        now = time.time()
        runs = []
        for key, (svc, jpath, lpath) in SERVICES.items():
            running = service_running(svc)
            st = last_status(jpath)
            self._update_card(key, st, running, now)
            if running:
                runs.append(key)
            if lpath:
                human = [l for l in tail(lpath, 4096) if not l.strip().startswith("{")]
                self._set_log("\n".join(human[-6:]))
        self._update_monthly()

        if runs:
            rate = sum(self._rate.get(k, 0) for k in runs)
            self.banner.config(text=f"● RUNNING: {', '.join(runs).upper()}  ·  {rate / 1e6:.0f} MB/s",
                               bg="#c0392b", fg="white")
        else:
            self.banner.config(text="● IDLE — next backup tonight", bg="#27ae60", fg="white")

        self._render_cache()

    def _update_card(self, key, st, running, now):
        card = self.cards[key]
        prev_t, prev_b = self._prev.get(key, (now, st.get("bytes_done", 0) if st else 0))
        cur_b = st.get("bytes_done", 0) if st else 0
        dt = max(0.001, now - prev_t)
        rate = (cur_b - prev_b) / dt if cur_b >= prev_b else 0.0
        self._prev[key] = (now, cur_b)
        self._rate[key] = rate

        if st is None:
            card["bar"]["value"] = 0
            card["lbl"].config(text="running…" if running else "waiting for next run")
            card["speed"].config(text="")
            card["det"].config(text="")
        elif st.get("summary"):
            card["bar"]["value"] = 100
            card["lbl"].config(text="✓ complete")
            card["speed"].config(text="")
            card["det"].config(text=f"{fmt_bytes(st.get('total_bytes_processed', 0))} processed")
        else:
            pct = min(100.0, st.get("percent_done", 0) * 100)
            card["bar"]["value"] = pct
            card["lbl"].config(text=f"{pct:.2f}%")
            remaining = max(0, st.get("total_bytes", 0) - cur_b)
            if rate > 0:
                card["speed"].config(text=f"{rate / 1e6:.1f} MB/s  ·  ETA {fmt_eta(remaining / rate)}")
            else:
                card["speed"].config(text="starting…")
            card["det"].config(text=(
                f"{st.get('files_done', 0):,}/{st.get('total_files', 0):,} files  ·  "
                f"{fmt_bytes(cur_b)} / {fmt_bytes(st.get('total_bytes', 0))}"))

    def _update_monthly(self):
        card = self.cards["monthly"]
        try:
            entries = sorted(os.listdir(MONTHLY_DIR))
        except OSError:
            entries = []
        if entries:
            card["bar"]["value"] = 100
            card["lbl"].config(text=f"✓ last image: {entries[-1]}")
            card["speed"].config(text=f"{len(entries)} stored")
            card["det"].config(text="bootable clone of the OS drive")
        else:
            card["bar"]["value"] = 0
            card["lbl"].config(text="due on last day of month")
            card["speed"].config(text="")
            card["det"].config(text="first image: Aug 31")

    def _render_cache(self):
        about = self._cache.get("about")
        if about:
            info = (f"Total: {about.get('total', '…')}    Used: {about.get('used', '…')}"
                    f"    Free: {about.get('free', '…')}")
        else:
            info = "Total: …    Used: …    Free: …"
        snap = self._cache.get("snap")
        if snap:
            info += "\n" + "   |   ".join(f"{k.capitalize()}: {v}" for k, v in snap.items())
        self.info_lbl.config(text=info)

        timers = self._cache.get("timers")
        if timers:
            self.sched_lbl.config(text="\n".join(f"{name:<11} →  {nxt}" for name, nxt in timers))

    def _set_log(self, text):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", text)
        self.log.config(state="disabled")

    def _auto(self):
        if self._stop:
            return
        self.refresh()
        self.root.after(2000, self._auto)

    # ---------- background data ----------
    def _worker(self):
        while not self._stop:
            now = time.time()
            if now - self._cache["t_about"] > 60:
                self._cache["about"] = self._get_about()
                self._cache["t_about"] = now
            if now - self._cache["t_snap"] > 60:
                self._cache["snap"] = self._get_snapshots()
                self._cache["t_snap"] = now
            if now - self._cache["t_timers"] > 30:
                self._cache["timers"] = self._get_timers()
                self._cache["t_timers"] = now
            time.sleep(5)

    def _get_about(self):
        d = {}
        for line in run(["rclone", "about", "gdrive:"], timeout=60).splitlines():
            m = re.match(r"^\s*(Total|Used|Free|Trashed):\s+(.*)$", line)
            if m:
                d[m.group(1).lower()] = m.group(2)
        return d or None

    def _get_snapshots(self):
        res = {}
        for key, repo in REPOS.items():
            out = run(["restic", "--password-file", PWFILE, "-r", repo, "snapshots", "--compact"], timeout=120)
            rows = []
            for line in out.splitlines():
                l = line.strip()
                if not l:
                    continue
                if l.startswith(("ID", "-", "Repository", "repository", "snapshot")) or "snapshots stored" in l:
                    continue
                if re.match(r"^\d+ snapshots?$", l):
                    continue
                rows.append(l)
            res[key] = f"{len(rows)} snapshot(s) · latest {rows[-1]}" if rows else "0 snapshots yet"
        return res

    def _get_timers(self):
        res = []
        for name, timer in TIMERS.items():
            out = run(["systemctl", "show", timer, "-p", "NextElapseUSecRealtime", "--value"], timeout=10).strip()
            if not out or out.lower() in ("n/a", "none"):
                nxt = "not scheduled"
            elif out.isdigit():
                nxt = time.strftime("%a %Y-%m-%d %H:%M", time.localtime(int(out) / 1_000_000))
            else:
                # systemctl may already format it, e.g. "Sat 2026-08-15 02:22:42 SAST"
                parts = out.split()
                nxt = f"{parts[0]} {parts[1]} {parts[2][:5]}" if len(parts) >= 3 else out
            res.append((name, nxt))
        return res

    # ---------- actions ----------
    def launch(self, key):
        svc, _, _ = SERVICES[key]
        if service_running(svc):
            messagebox.showinfo("My Backups", f"{svc} is already running.")
            return
        threading.Thread(target=self._launch, args=(svc,), daemon=True).start()

    def _launch(self, svc):
        for cmd in (["pkexec", "systemctl", "start", svc],
                    ["sudo", "systemctl", "start", svc]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if r.returncode == 0:
                    self.root.after(0, lambda: self._set_log(f"Started {svc}\n"))
                    return
            except Exception:
                continue
        self.root.after(0, lambda: messagebox.showerror(
            "My Backups", f"Could not start {svc}.\nRun manually:\n  sudo systemctl start {svc}"))

    def open_drive(self):
        for cmd in (["xdg-open", DRIVE_DIR], ["gio", "open", DRIVE_DIR]):
            try:
                subprocess.Popen(cmd)
                return
            except Exception:
                continue

    def _on_close(self):
        self._stop = True
        self.root.destroy()


def main():
    root = tk.Tk()
    BackupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
