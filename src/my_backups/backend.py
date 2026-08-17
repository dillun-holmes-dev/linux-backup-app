"""Backend: talks to restic, rclone and systemd.

Refactored from the original ``backup-ui.py`` so the GTK app reuses the
same battle-tested logic (live progress, snapshots, timers, launch).
All blocking work (restic/rclone calls) happens in background threads so
the UI never freezes.
"""
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import calendar
import signal
from datetime import datetime, timedelta
from pathlib import Path

from .metadata import APP_ICON, APP_ID, APP_NAME

_ORIGINAL_RUN = getattr(subprocess, "run")
_ORIGINAL_POPEN = getattr(subprocess, "Popen")


def _child_process_env(explicit=None):
    """Return an environment without AppImage runtime paths for host tools."""
    env = dict(os.environ if explicit is None else explicit)
    system_ld = env.pop("VAULTLEAF_SYSTEM_LD_LIBRARY_PATH", "")
    system_xdg = env.pop("VAULTLEAF_SYSTEM_XDG_DATA_DIRS", "")
    for name in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH",
                 "GI_TYPELIB_PATH", "GIO_EXTRA_MODULES", "GTK_PATH",
                 "GTK_IM_MODULE", "GDK_PIXBUF_MODULEDIR",
                 "GDK_PIXBUF_MODULE_FILE"):
        env.pop(name, None)
    if system_ld:
        env["LD_LIBRARY_PATH"] = system_ld
    if system_xdg:
        env["XDG_DATA_DIRS"] = system_xdg
    else:
        env.pop("XDG_DATA_DIRS", None)
    return env


def _run_process(*args, **kwargs):
    kwargs["env"] = _child_process_env(kwargs.get("env"))
    return _ORIGINAL_RUN(*args, **kwargs)


def _popen_process(*args, **kwargs):
    kwargs["env"] = _child_process_env(kwargs.get("env"))
    return _ORIGINAL_POPEN(*args, **kwargs)


CONFIG_PATH = Path.home() / ".config" / "my-backups" / "config.json"
DATA_DIR = Path.home() / ".local" / "share" / "my-backups"
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

_HOME = str(Path.home())

DEFAULTS = {
    "daily_json": "/var/tmp/backup-daily.json",
    "weekly_json": "/var/tmp/backup-weekly.json",
    "monthly_json": f"{DATA_DIR}/state/backup-monthly.json",
    "daily_log": "/var/log/backup-daily.log",
    "weekly_log": "/var/log/backup-weekly.log",
    "monthly_log": f"{DATA_DIR}/logs/backup-monthly.log",
    "drive_dir": f"{_HOME}/MyBackups/CloudDrive",
    "pwfile": f"{DATA_DIR}/restic-passphrase.txt",
    "rclone_config": f"{_HOME}/.config/rclone/rclone.conf",
    "excludes_file": f"{DATA_DIR}/excludes.txt",
    "backup_scripts_dir": str(DATA_DIR),
    "backup_source": _HOME,
    "storage_mode": "",
    "rclone_remote": "",
    "setup_complete": False,
    "systemd_user": False,
    "scheduler_backend": "legacy",
    "speed_profile": "balanced",
    "google_client_mode": "shared",
    "smb_remote": "vaultleaf-smb",
    "smb_host": "",
    "smb_share": "",
    "smb_user": "",
    "smb_domain": "WORKGROUP",
    "mount_source": "",
    "integrity_json": f"{DATA_DIR}/state/integrity.json",
    "integrity_log": f"{DATA_DIR}/logs/integrity.log",
    "repos": {"daily": "rclone:gdrive:MyBackups/repositories/daily",
              "weekly": "rclone:gdrive:MyBackups/repositories/weekly",
              "monthly": "rclone:gdrive:MyBackups/repositories/monthly"},
    "services": {"daily": "backup-daily.service", "weekly": "backup-weekly.service",
                 "monthly": "backup-monthly.service"},
    "schedule_enabled": {"daily": True, "weekly": True, "monthly": True,
                         "integrity": True},
    "timers": {
        "Daily": "backup-daily.timer",
        "Weekly": "backup-weekly.timer",
        "Monthly": "backup-monthly.timer",
        "Integrity": "backup-integrity.timer",
    },
}


def _deep_update(base, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def load_config(path=CONFIG_PATH):
    """Return the config dict: defaults merged with the user's JSON file."""
    data = json.loads(json.dumps(DEFAULTS))  # deep copy
    loaded = {}
    try:
        if Path(path).exists():
            loaded = json.loads(Path(path).read_text())
            _deep_update(data, loaded)
    except Exception:
        pass
    if loaded.get("setup_complete") and "monthly" not in loaded.get("repos", {}):
        weekly = data["repos"]["weekly"]
        data["repos"]["monthly"] = (weekly[:-len("weekly")] + "monthly"
                                      if weekly.endswith("weekly") else weekly + "-monthly")
        data["schedule_enabled"]["monthly"] = False
        if data.get("systemd_user"):
            data["services"]["monthly"] = "my-backups-monthly.service"
            data["timers"]["Monthly"] = "my-backups-monthly.timer"
    return data


def save_config(cfg, path=CONFIG_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def run(cmd, timeout=30, cwd=None, env_updates=None):
    env = os.environ.copy()
    env.setdefault("RCLONE_CONFIG", str(Path.home() / ".config/rclone/rclone.conf"))
    if env_updates:
        env.update(env_updates)
    try:
        r = _run_process(cmd, capture_output=True, text=True,
                           timeout=timeout, env=env, cwd=cwd)
        return (r.stdout + r.stderr).strip()
    except Exception:
        return ""


def tail(path, nbytes=100 * 1024):
    """Return the last lines of a file (reads from the tail, no full read)."""
    try:
        with open(path, "rb") as f:
            size = os.path.getsize(path)
            f.seek(max(0, size - nbytes))
            return f.read().decode(errors="replace").splitlines()
    except OSError:
        return []


def last_status(path):
    """Parse the most recent restic --json status/summary line."""
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


def service_running(svc, cfg=None):
    try:
        if cfg and cfg.get("scheduler_backend") == "internal":
            key = ("daily" if "daily" in svc else "weekly" if "weekly" in svc
                   else "monthly" if "monthly" in svc else "")
            if not key or not shutil.which("pgrep"):
                return False
            pattern = f"{DATA_DIR / 'run-backup.sh'} {key}"
            return _run_process(["pgrep", "-f", pattern], capture_output=True,
                                  timeout=5).returncode == 0
        cmd = ["systemctl"] + (["--user"] if cfg and cfg.get("systemd_user") else [])
        cmd += ["is-active", svc]
        out = _run_process(cmd,
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return out in ("activating", "active")
    except Exception:
        return False


def _systemctl(cfg, *args, timeout=20):
    cmd = ["systemctl"]
    if cfg.get("systemd_user"):
        cmd.append("--user")
    cmd.extend(args)
    return _run_process(cmd, capture_output=True, text=True, timeout=timeout)


def user_systemd_available():
    if not shutil.which("systemctl"):
        return False
    try:
        return _run_process(["systemctl", "--user", "show-environment"],
                              capture_output=True, timeout=10).returncode == 0
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


# ---------------------------------------------------------------------------
# Google Drive + restic
# ---------------------------------------------------------------------------

def get_about(cfg):
    """Drive total/used/free from `rclone about`."""
    if cfg.get("storage_mode") in ("folder", "smb"):
        return None
    d = {}
    remote = cfg.get("rclone_remote") or "gdrive"
    for line in run(["rclone", "about", f"{remote}:"], timeout=20,
                    env_updates={"RCLONE_CONFIG": cfg["rclone_config"]}).splitlines():
        m = re.match(r"^\s*(Total|Used|Free|Trashed):\s+(.*)$", line)
        if m:
            d[m.group(1).lower()] = m.group(2)
    return d or None


SNAP_RE = re.compile(
    r"^([0-9a-f]{8,})\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)$"
)


def get_snapshots(cfg, repo):
    """List restic snapshots for a repo (newest first)."""
    out = run(["restic", "--password-file", cfg["pwfile"], "-r", repo,
               "snapshots", "--compact"], timeout=60,
              env_updates={"RCLONE_CONFIG": cfg["rclone_config"]})
    snaps = []
    for line in out.splitlines():
        m = SNAP_RE.match(line.strip())
        if m:
            snaps.append({"id": m.group(1), "time": m.group(2),
                          "host": m.group(3), "paths": m.group(4).strip()})
    return snaps


def prepare_restore_target(base, snapshot_time, use_subfolder=True):
    """Validate a restore destination and return a collision-free target path."""
    base = Path(base).expanduser().resolve()
    if use_subfolder:
        stamp = re.sub(r"[^0-9-]", "-", snapshot_time[:16]).strip("-")
        wanted = base / f"VaultLeaf Restore {stamp}"
        target = wanted
        number = 2
        while target.exists():
            target = Path(f"{wanted} ({number})")
            number += 1
    else:
        target = base

    existing = target
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir() or not os.access(existing, os.W_OK):
        raise ValueError("Choose a folder you can write to")
    return str(target)


def get_timers(cfg):
    """Next fire time for each systemd timer."""
    if cfg.get("scheduler_backend") == "internal":
        sched = cfg.get("schedule", {})
        now = datetime.now().astimezone()
        daily = _next_daily(now, sched.get("daily_time", "21:00"))
        weekly = _next_weekly(now, sched.get("weekly_day", "Sun"),
                              sched.get("weekly_time", "20:00"))
        monthly = _next_monthly(now, sched.get("monthly_day", "1"),
                                sched.get("monthly_time", "02:00"))
        integrity = _next_weekly(now, sched.get("integrity_day", "Mon"),
                                 sched.get("integrity_time", "03:00"))
        enabled = cfg.get("schedule_enabled", {})
        values = (("Daily", daily), ("Weekly", weekly), ("Monthly", monthly),
                  ("Integrity", integrity))
        return [(name, value.strftime("%a %Y-%m-%d %H:%M"))
                for name, value in values if enabled.get(name.lower(), True)]
    res = []
    for name, timer in cfg["timers"].items():
        if not cfg.get("schedule_enabled", {}).get(name.lower(), True):
            continue
        cmd = ["systemctl"] + (["--user"] if cfg.get("systemd_user") else [])
        cmd += ["show", timer, "-p", "NextElapseUSecRealtime", "--value"]
        out = run(cmd, timeout=10).strip()
        if not out or out.lower() in ("n/a", "none"):
            nxt = "not scheduled"
        elif out.isdigit():
            nxt = time.strftime("%a %Y-%m-%d %H:%M", time.localtime(int(out) / 1_000_000))
        else:
            parts = out.split()
            nxt = f"{parts[0]} {parts[1]} {parts[2][:5]}" if len(parts) >= 3 else out
        res.append((name, nxt))
    return res


def _parse_clock(value):
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour, minute


def _next_daily(now, clock):
    hour, minute = _parse_clock(clock)
    result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return result if result > now else result + timedelta(days=1)


def _next_weekly(now, day, clock):
    day_index = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun").index(day)
    hour, minute = _parse_clock(clock)
    delta = (day_index - now.weekday()) % 7
    result = (now + timedelta(days=delta)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    return result if result > now else result + timedelta(days=7)


def _next_monthly(now, day, clock):
    hour, minute = _parse_clock(clock)
    for offset in (0, 1):
        year = now.year + (now.month - 1 + offset) // 12
        month = (now.month - 1 + offset) % 12 + 1
        last = calendar.monthrange(year, month)[1]
        number = last if str(day) == "last" else min(int(day), last)
        result = now.replace(year=year, month=month, day=number, hour=hour,
                             minute=minute, second=0, microsecond=0)
        if result > now:
            return result
    return result


# ---------------------------------------------------------------------------
# Excludes
# ---------------------------------------------------------------------------

def get_excludes(cfg):
    try:
        return Path(cfg["excludes_file"]).read_text()
    except OSError:
        return ""


def save_excludes(cfg, text):
    source = Path(cfg.get("backup_source", Path.home())).expanduser().resolve()
    for raw in text.splitlines():
        value = raw.strip()
        if not value or value.startswith("#") or any(char in value for char in "*?["):
            continue
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            candidate = candidate.resolve()
            if candidate == source or candidate in source.parents:
                raise ValueError("An exclusion cannot contain the entire backup source")
    Path(cfg["excludes_file"]).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg["excludes_file"]).write_text(text)
    return True


def integrity_status(cfg):
    try:
        data = json.loads(Path(cfg["integrity_json"]).read_text())
        if isinstance(data.get("ok"), bool) and data.get("checked_at"):
            return data
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def _portable_state_path():
    return DATA_DIR / "state" / "portable-schedule.json"


def initialize_portable_schedule():
    path = _portable_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().isoformat()
    _write_private(path, json.dumps({"daily": stamp, "weekly": stamp, "monthly": stamp,
                                     "integrity": stamp}) + "\n")


def run_portable_schedule(cfg):
    """Launch due jobs on desktops without a systemd user manager."""
    if cfg.get("scheduler_backend") != "internal":
        return []
    path = _portable_state_path()
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    now = datetime.now().astimezone()
    sched = cfg.get("schedule", {})
    daily_latest = _next_daily(now, sched.get("daily_time", "21:00")) - timedelta(days=1)
    weekly_latest = (_next_weekly(now, sched.get("weekly_day", "Sun"),
                                  sched.get("weekly_time", "20:00")) - timedelta(days=7))
    next_monthly = _next_monthly(now, sched.get("monthly_day", "1"),
                                 sched.get("monthly_time", "02:00"))
    previous_month = next_monthly.replace(day=1) - timedelta(days=1)
    monthly_latest = _next_monthly(
        previous_month.replace(day=1) - timedelta(seconds=1),
        sched.get("monthly_day", "1"), sched.get("monthly_time", "02:00"))
    integrity_latest = (_next_weekly(now, sched.get("integrity_day", "Mon"),
                                     sched.get("integrity_time", "03:00")) -
                        timedelta(days=7))
    due = {"daily": daily_latest, "weekly": weekly_latest, "monthly": monthly_latest,
           "integrity": integrity_latest}
    enabled = cfg.get("schedule_enabled", {})
    launched = []
    for key, latest in due.items():
        if not enabled.get(key, True):
            continue
        try:
            previous = datetime.fromisoformat(state.get(key, "1970-01-01T00:00:00+00:00"))
        except ValueError:
            previous = datetime.fromtimestamp(0, now.tzinfo)
        if previous >= latest:
            continue
        runner = DATA_DIR / ("run-integrity.sh" if key == "integrity" else "run-backup.sh")
        args = [str(runner)] + ([] if key == "integrity" else [key])
        try:
            _popen_process(args, start_new_session=True)
            state[key] = now.isoformat()
            launched.append(key)
        except OSError:
            continue
    if launched:
        _write_private(path, json.dumps(state, indent=2) + "\n")
    return launched


def ensure_portable_mount(cfg):
    """Start the cloud mount when systemd is unavailable."""
    if (cfg.get("scheduler_backend") != "internal" or
            cfg.get("storage_mode") not in ("oauth", "smb")):
        return True
    mount_dir = cfg["drive_dir"]
    if shutil.which("mountpoint"):
        if _run_process(["mountpoint", "-q", mount_dir],
                          capture_output=True).returncode == 0:
            return True
    profile = SPEED_PROFILES.get(cfg.get("speed_profile"), SPEED_PROFILES["balanced"])
    cache_dir = DATA_DIR / "rclone-cache"
    mount_source = cfg.get("mount_source") or f"{cfg['rclone_remote']}:"
    cmd = ["rclone", "mount", mount_source, mount_dir,
           "--config", cfg["rclone_config"], "--cache-dir", str(cache_dir),
           "--vfs-cache-mode", "writes", "--dir-cache-time", "5m",
           "--transfers", profile["transfers"], "--checkers", profile["checkers"],
           "--retries", "10", "--low-level-retries", "20", "--timeout", "5m",
           "--daemon"]
    if cfg.get("storage_mode") == "oauth":
        cmd += ["--drive-chunk-size", profile["chunk"]]
    try:
        return _run_process(cmd, capture_output=True, timeout=40).returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# First-run setup, persistent mount and user schedules
# ---------------------------------------------------------------------------

def configured_remotes(config_path=None):
    """Return rclone remote names without the trailing colon."""
    if not shutil.which("rclone"):
        return []
    env = {"RCLONE_CONFIG": str(config_path or DEFAULTS["rclone_config"])}
    out = run(["rclone", "listremotes"], timeout=15, env_updates=env)
    return [line.strip().rstrip(":") for line in out.splitlines() if line.strip()]


def configured_drive_remotes(config_path=None):
    """Return only Google Drive remotes, excluding incompatible backends."""
    result = []
    env = {"RCLONE_CONFIG": str(config_path or DEFAULTS["rclone_config"])}
    for name in configured_remotes(config_path):
        shown = run(["rclone", "config", "show", name], timeout=10,
                    env_updates=env)
        if re.search(r"(?m)^type\s*=\s*drive\s*$", shown):
            result.append(name)
    return result


def configured_smb_remotes(config_path=None):
    """Return rclone remotes using the SMB backend."""
    result = []
    env = {"RCLONE_CONFIG": str(config_path or DEFAULTS["rclone_config"])}
    for name in configured_remotes(config_path):
        shown = run(["rclone", "config", "show", name], timeout=10,
                    env_updates=env)
        if re.search(r"(?m)^type\s*=\s*smb\s*$", shown):
            result.append(name)
    return result


def _validate_smb_values(host, share, user, domain):
    host = host.strip()
    share = share.strip().strip("/\\")
    user = user.strip()
    domain = domain.strip() or "WORKGROUP"
    if not host or "/" in host or "\\" in host or host.startswith("smb:"):
        raise ValueError("Enter only the SMB server name or IP address")
    if not share or "/" in share or "\\" in share:
        raise ValueError("Enter only the shared folder name")
    if not user:
        raise ValueError("Enter an SMB username (use 'guest' for guest shares)")
    return host, share, user, domain


def configure_smb_remote(config_path, remote, host, share, user, password, domain,
                         write_marker=True, _transaction=True):
    """Create/update a private rclone SMB remote and prove the share is writable."""
    if not shutil.which("rclone"):
        raise RuntimeError("rclone is not installed")
    if _transaction:
        target = Path(config_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        working = target.with_name(
            f".{target.name}.vaultleaf-{secrets.token_hex(6)}.tmp")
        if target.exists():
            shutil.copy2(target, working)
        try:
            configured = configure_smb_remote(
                working, remote, host, share, user, password, domain,
                write_marker=write_marker, _transaction=False)
            os.chmod(working, 0o600)
            working.replace(target)
            return configured
        finally:
            try:
                working.unlink()
            except FileNotFoundError:
                pass
    host, share, user, domain = _validate_smb_values(host, share, user, domain)
    remote = (remote or "vaultleaf-smb").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", remote):
        raise ValueError("The SMB connection name is invalid")
    existing = configured_remotes(config_path)
    if remote in existing and remote not in configured_smb_remotes(config_path):
        raise ValueError(f"A non-SMB connection already uses the name '{remote}'")
    cmd = ["rclone", "config", "update" if remote in existing else "create",
           remote]
    if remote not in existing:
        cmd.append("smb")
    cmd += ["host", host, "user", user, "domain", domain]
    if password:
        obscured = _run_process(
            ["rclone", "obscure", "-"], input=password + "\n", capture_output=True,
            text=True, timeout=15).stdout.strip()
        if not obscured:
            raise RuntimeError("Could not protect the SMB password")
        cmd += ["pass", obscured, "--no-obscure"]
    elif remote not in existing:
        cmd += ["pass", "", "--no-obscure"]
    env = {**os.environ, "RCLONE_CONFIG": str(config_path)}
    result = _run_process(cmd, capture_output=True, text=True, timeout=30, env=env)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Could not save the SMB connection")
    config_file = Path(config_path)
    if config_file.exists():
        os.chmod(config_file, 0o600)
    root = f"{remote}:{share}"
    check = _run_process(["rclone", "lsd", root], capture_output=True, text=True,
                           timeout=45, env=env)
    if check.returncode:
        raise RuntimeError(check.stderr.strip() or
                           "Could not connect. Check the server, share, and login.")
    if write_marker:
        marker = f"{root}/.my-backups-storage"
        check = _run_process(["rclone", "touch", marker], capture_output=True,
                               text=True, timeout=45, env=env)
        if check.returncode:
            raise RuntimeError(check.stderr.strip() or
                               "Connected, but this account cannot write to the share")
    return {"remote": remote, "host": host, "share": share,
            "user": user, "domain": domain, "root": root}


def test_smb_connection(config_path, host, share, user, password, domain):
    """Test SMB settings with a temporary rclone config, leaving user config unchanged."""
    import tempfile
    host, share, user, domain = _validate_smb_values(host, share, user, domain)
    with tempfile.TemporaryDirectory(prefix="vaultleaf-smb-") as directory:
        temp_config = Path(directory) / "rclone.conf"
        configured = configure_smb_remote(
            temp_config, "vaultleaf-test", host, share, user, password, domain,
            write_marker=False)
        env = {**os.environ, "RCLONE_CONFIG": str(temp_config)}
        probe = f"{configured['root']}/.vaultleaf-write-test-{secrets.token_hex(6)}"
        written = _run_process(["rclone", "touch", probe], capture_output=True,
                                 text=True, timeout=45, env=env)
        if written.returncode:
            raise RuntimeError(written.stderr.strip() or
                               "Connected, but this account cannot write to the share")
        _run_process(["rclone", "deletefile", probe], capture_output=True,
                       text=True, timeout=30, env=env)
    return f"Connected to {configured['root']} successfully."


def test_saved_smb_connection(cfg):
    """Re-test the already saved SMB login without exposing its password."""
    remote = cfg.get("smb_remote") or cfg.get("rclone_remote")
    _, share, _, _ = _validate_smb_values(
        cfg.get("smb_host", ""), cfg.get("smb_share", ""),
        cfg.get("smb_user", ""), cfg.get("smb_domain", "WORKGROUP"))
    if remote not in configured_smb_remotes(cfg.get("rclone_config")):
        raise ValueError("The saved SMB connection is missing; enter the password again")
    root = f"{remote}:{share}"
    env = {**os.environ, "RCLONE_CONFIG": cfg["rclone_config"]}
    check = _run_process(["rclone", "lsd", root], capture_output=True, text=True,
                           timeout=45, env=env)
    if check.returncode:
        raise RuntimeError(check.stderr.strip() or "Could not connect to the saved SMB share")
    return f"Connected to {root} successfully."


def open_rclone_config(config_path=None, on_done=None):
    """Open rclone's official interactive OAuth setup in a terminal."""
    terminals = (
        ["kgx", "--", "rclone", "config"],
        ["gnome-terminal", "--", "rclone", "config"],
        ["konsole", "-e", "rclone", "config"],
        ["xfce4-terminal", "-e", "rclone config"],
        ["xterm", "-e", "rclone", "config"],
    )
    for cmd in terminals:
        if shutil.which(cmd[0]):
            try:
                env = os.environ.copy()
                env["RCLONE_CONFIG"] = str(config_path or DEFAULTS["rclone_config"])
                proc = _popen_process(cmd, env=env)
                if on_done:
                    threading.Thread(target=lambda: (proc.wait(), on_done()),
                                     daemon=True).start()
                return True, "Complete the sign-in in the terminal, then return here."
            except OSError:
                continue
    return False, "No terminal app was found. Run 'rclone config' in a terminal."


def create_google_drive_remote(name, config_path, on_done):
    """Create a Google Drive remote and let rclone perform browser OAuth."""
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        return False, "Use 1–40 letters, numbers, dashes, or underscores for the account name."
    if name in configured_remotes(config_path):
        return False, f"An account named '{name}' already exists."
    if not shutil.which("rclone"):
        return False, "rclone is not installed."

    def work():
        try:
            env = os.environ.copy()
            env["RCLONE_CONFIG"] = str(config_path or DEFAULTS["rclone_config"])
            result = _run_process(
                ["rclone", "config", "create", name, "drive", "scope", "drive",
                 "config_is_local", "true"],
                capture_output=True, text=True, timeout=600, env=env)
            if result.returncode == 0 and name in configured_remotes(config_path):
                on_done(True, "Google Drive connected successfully.", name)
            else:
                on_done(False, "Google Drive sign-in was cancelled or failed.", name)
        except subprocess.TimeoutExpired:
            on_done(False, "Google Drive sign-in timed out. Please try again.", name)
        except Exception as exc:  # noqa: BLE001
            on_done(False, f"Could not start Google Drive sign-in: {exc}", name)

    threading.Thread(target=work, daemon=True).start()
    return True, "Your browser will open. Sign in and allow rclone access to Google Drive."


def google_client_credentials(json_path):
    """Read a Google Desktop OAuth client JSON without retaining a second copy."""
    try:
        payload = json.loads(Path(json_path).expanduser().read_text())
        client = payload["installed"]
        client_id = client["client_id"].strip()
        client_secret = client["client_secret"].strip()
        if not client_id or not client_secret:
            raise ValueError
        return client_id, client_secret
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Choose a Google Desktop OAuth client JSON file") from exc


def create_google_drive_remote_with_client(name, config_path, json_path, on_done):
    """Create a Drive remote using the user's own Google API OAuth client."""
    try:
        client_id, client_secret = google_client_credentials(json_path)
    except ValueError as exc:
        return False, str(exc)
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        return False, "Use 1–40 letters, numbers, dashes, or underscores for the account name."
    if name in configured_remotes(config_path):
        return False, f"An account named '{name}' already exists."
    if not shutil.which("rclone"):
        return False, "rclone is not installed."

    def work():
        try:
            env = os.environ.copy()
            env["RCLONE_CONFIG"] = str(config_path or DEFAULTS["rclone_config"])
            result = _run_process(
                ["rclone", "config", "create", name, "drive", "scope", "drive",
                 "client_id", client_id, "client_secret", client_secret,
                 "config_is_local", "true"], capture_output=True, text=True,
                timeout=600, env=env)
            if result.returncode == 0 and name in configured_remotes(config_path):
                on_done(True, "Google Drive connected with your private API client.", name)
            else:
                on_done(False, "Google Drive sign-in was cancelled or failed.", name)
        except subprocess.TimeoutExpired:
            on_done(False, "Google Drive sign-in timed out. Please try again.", name)
        except Exception as exc:  # noqa: BLE001
            on_done(False, f"Could not start Google Drive sign-in: {exc}", name)

    threading.Thread(target=work, daemon=True).start()
    return True, "Your browser will open for your private Google API OAuth sign-in."


SPEED_PROFILES = {
    "reliable": {"transfers": "2", "checkers": "4", "chunk": "8M",
                 "integrity_subset": "1%"},
    "balanced": {"transfers": "4", "checkers": "8", "chunk": "16M",
                 "integrity_subset": "5%"},
    "fast": {"transfers": "8", "checkers": "16", "chunk": "64M",
             "integrity_subset": "10%"},
}


def missing_dependencies():
    required = (("restic", "restic"), ("rclone", "rclone"))
    missing = [label for command, label in required if not shutil.which(command)]
    if not (shutil.which("fusermount3") or shutil.which("fusermount")):
        missing.append("FUSE")
    return missing


def install_dependencies(on_done=None):
    """Ask for administrator access once and install distro dependencies."""
    script = DATA_DIR / "install-dependencies.sh"
    content = '''#!/bin/sh
set -eu
if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y restic rclone fuse3 python3-gi gir1.2-gtk-4.0
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y restic rclone fuse3 python3-gobject gtk4
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive install restic rclone fuse3 python3-gobject gtk4
elif command -v pacman >/dev/null 2>&1; then
  pacman -S --needed --noconfirm restic rclone fuse3 python-gobject gtk4
elif command -v apk >/dev/null 2>&1; then
  apk add restic rclone fuse3 py3-gobject3 gtk4.0
else
  echo "Unsupported package manager" >&2
  exit 2
fi
'''
    _write_private(script, content, executable=True)

    def work():
        try:
            result = _run_process(["pkexec", str(script)], capture_output=True,
                                    text=True, timeout=1800)
            ok = result.returncode == 0
            message = ("Required components are installed." if ok else
                       "Installation was cancelled or failed. Install restic, rclone, and FUSE manually.")
        except Exception as exc:  # noqa: BLE001
            ok, message = False, f"Could not install components: {exc}"
        if on_done:
            on_done(ok, message)

    threading.Thread(target=work, daemon=True).start()
    return True


def _write_private(path, content, executable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, 0o700 if executable else 0o600)


def _unit_quote(value):
    """Quote a systemd argument, including literal percent characters."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _calendar(day, clock):
    return f"{day} *-*-* {clock}:00" if day else f"*-*-* {clock}:00"


def _calendar_monthly(day, clock):
    date = "*-*~1" if str(day) == "last" else f"*-*-{int(day):02d}"
    return f"{date} {clock}:00"


def ensure_desktop_identity(desktop_exec=None):
    """Install the canonical desktop ID and leaf icon for docks/taskbars."""
    if desktop_exec is None:
        appimage = os.environ.get("APPIMAGE")
        if appimage:
            executable = str(Path(appimage).resolve())
            desktop_exec = ('"' + executable.replace("\\", "\\\\")
                            .replace('"', '\\"') + '"')
        else:
            launcher = DATA_DIR / "start-app.sh"
            if not launcher.is_file():
                return False
            desktop_exec = ('"' + str(launcher).replace("\\", "\\\\")
                            .replace('"', '\\"') + '"')

    icon_dir = (Path.home() / ".local" / "share" / "icons" / "hicolor" /
                "256x256" / "apps")
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_target = icon_dir / f"{APP_ICON}.png"
    shutil.copy2(Path(__file__).parent / "data" / "icon.png", icon_target)

    menu_entry = (Path.home() / ".local" / "share" / "applications" /
                  f"{APP_ID}.desktop")
    menu_entry.parent.mkdir(parents=True, exist_ok=True)
    menu_entry.write_text(
        f"[Desktop Entry]\nType=Application\nVersion=1.0\nName={APP_NAME}\n"
        "GenericName=Backup manager\n"
        "Comment=Friendly encrypted backups and safe file recovery\n"
        f"Exec={desktop_exec}\nIcon={icon_target}\n"
        f"StartupWMClass={APP_ID}\n"
        "Terminal=false\nCategories=Utility;Archiving;FileTools;\n"
        "StartupNotify=true\n")
    os.chmod(menu_entry, 0o644)

    for command, target in (("update-desktop-database", menu_entry.parent),
                            ("gtk-update-icon-cache", icon_dir.parents[1])):
        if shutil.which(command):
            try:
                _run_process([command, str(target)], capture_output=True, timeout=20)
            except Exception:
                pass
    return True


def _install_autostart():
    """Start the tray/background controller after desktop login."""
    launcher = DATA_DIR / "start-app.sh"
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        installed_dir = Path.home() / ".local" / "lib" / "my-backups"
        installed_dir.mkdir(parents=True, exist_ok=True)
        installed_app = installed_dir / "MyBackups.AppImage"
        source_app = Path(appimage).resolve()
        if source_app != installed_app.resolve():
            shutil.copy2(source_app, installed_app)
        os.chmod(installed_app, 0o755)
        command = f"exec {shlex.quote(str(installed_app))} \"$@\"\n"
    else:
        installed_python = DATA_DIR / "app"
        source_package = Path(__file__).resolve().parent
        installed_package = installed_python / "my_backups"
        if source_package != installed_package.resolve():
            shutil.copytree(source_package, installed_package,
                            dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        command = (f"export PYTHONPATH={shlex.quote(str(installed_python))}\n"
                   f"exec {shlex.quote(sys.executable)} -m my_backups \"$@\"\n")
    _write_private(launcher, "#!/bin/sh\n" + command, executable=True)
    desktop_exec = '"' + str(launcher).replace("\\", "\\\\").replace('"', '\\"') + '"'
    autostart = Path.home() / ".config" / "autostart" / f"{APP_ID}.desktop"
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(
        f"[Desktop Entry]\nType=Application\nName={APP_NAME}\n"
        f"Exec={desktop_exec} --background\nIcon={APP_ICON}\n"
        f"StartupWMClass={APP_ID}\n"
        "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n")
    ensure_desktop_identity(desktop_exec)
    bundled_bin = os.environ.get("VAULTLEAF_BUNDLED_BIN")
    if bundled_bin:
        uninstaller = Path(bundled_bin) / "vaultleaf-uninstall"
        if uninstaller.is_file():
            local_bin = Path.home() / ".local" / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            shutil.copy2(uninstaller, local_bin / "vaultleaf-uninstall")
            os.chmod(local_bin / "vaultleaf-uninstall", 0o755)


def _install_bundled_tools():
    """Keep AppImage CLI tools available to timers after it is unmounted."""
    bundled = os.environ.get("VAULTLEAF_BUNDLED_BIN")
    if not bundled:
        return None
    source_dir = Path(bundled)
    tool_dir = DATA_DIR / "bin"
    tool_dir.mkdir(parents=True, exist_ok=True)
    copied = False
    for name in ("restic", "rclone"):
        source = source_dir / name
        if source.is_file():
            target = tool_dir / name
            shutil.copy2(source, target)
            os.chmod(target, 0o755)
            copied = True
    return tool_dir if copied else None


def launch_application(path):
    """Launch an updated AppImage with a clean host environment."""
    _popen_process([str(path)], start_new_session=True)


def uninstall_application():
    """Remove user-level integration while preserving configuration and backups."""
    unit_names = [
        "my-backups-daily.timer", "my-backups-weekly.timer",
        "my-backups-monthly.timer", "my-backups-integrity.timer",
        "my-backups-rclone.service",
    ]
    if user_systemd_available():
        _run_process(["systemctl", "--user", "disable", "--now", *unit_names],
                     capture_output=True, timeout=60)
    for stem in ("daily", "weekly", "monthly", "integrity"):
        for suffix in ("service", "timer"):
            (USER_UNIT_DIR / f"my-backups-{stem}.{suffix}").unlink(missing_ok=True)
    (USER_UNIT_DIR / "my-backups-rclone.service").unlink(missing_ok=True)
    if user_systemd_available():
        _run_process(["systemctl", "--user", "daemon-reload"],
                     capture_output=True, timeout=20)

    home = Path.home()
    paths = [
        home / ".config" / "autostart" / f"{APP_ID}.desktop",
        home / ".config" / "autostart" / "my-backups.desktop",
        home / ".local" / "share" / "applications" / f"{APP_ID}.desktop",
        home / ".local" / "share" / "applications" / "my-backups.desktop",
        home / ".local" / "share" / "icons" / "hicolor" / "scalable" /
        "apps" / f"{APP_ICON}.svg",
        home / ".local" / "share" / "icons" / "hicolor" / "256x256" /
        "apps" / f"{APP_ICON}.png",
        home / ".local" / "bin" / "my-backups",
        home / ".local" / "bin" / "vaultleaf-backup",
        home / ".local" / "bin" / "vaultleaf-uninstall",
    ]
    for path in paths:
        path.unlink(missing_ok=True)
    shutil.rmtree(home / ".local" / "lib" / "my-backups", ignore_errors=True)
    shutil.rmtree(DATA_DIR / "bin", ignore_errors=True)
    for name in ("run-backup.sh", "run-integrity.sh", "start-app.sh",
                 "install-dependencies.sh"):
        (DATA_DIR / name).unlink(missing_ok=True)
    return ("VaultLeaf was removed. Backup repositories, encryption keys, "
            "settings, and logs were preserved.")


def _install_user_units(cfg, daily_time, weekly_day, weekly_time, mount_remote=None):
    has_systemd = user_systemd_available()
    USER_UNIT_DIR.mkdir(parents=True, exist_ok=True)
    bundled_tools = _install_bundled_tools()
    timer_path = (f"{bundled_tools}:/usr/local/bin:/usr/bin:/bin"
                  if bundled_tools else "/usr/local/bin:/usr/bin:/bin")
    runner = DATA_DIR / "run-backup.sh"
    q = shlex.quote
    script = f'''#!/bin/sh
set -eu
export PATH={q(timer_path)}
kind="$1"
case "$kind" in
  daily) repo={q(cfg["repos"]["daily"])}; output={q(cfg["daily_json"])}; log={q(cfg["daily_log"])} ;;
  weekly) repo={q(cfg["repos"]["weekly"])}; output={q(cfg["weekly_json"])}; log={q(cfg["weekly_log"])} ;;
  monthly) repo={q(cfg["repos"]["monthly"])}; output={q(cfg["monthly_json"])}; log={q(cfg["monthly_log"])} ;;
  *) exit 2 ;;
esac
export RCLONE_CONFIG={q(cfg["rclone_config"])}
export RCLONE_TRANSFERS={SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["transfers"]}
export RCLONE_CHECKERS={SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["checkers"]}
export RCLONE_DRIVE_CHUNK_SIZE={SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["chunk"]}
export RCLONE_RETRIES=10
export RCLONE_LOW_LEVEL_RETRIES=20
mkdir -p "$(dirname "$output")" "$(dirname "$log")"
if [ -f "$log" ] && [ "$(wc -c <"$log")" -gt 10485760 ]; then
  mv "$log" "$log.previous"
fi
'''
    if cfg.get("storage_mode") in ("folder", "smb"):
        script += f'''if [ ! -f {q(str(Path(cfg["drive_dir"]) / ".my-backups-storage"))} ]; then
  echo "Storage folder is unavailable; backup not started." >>"$log"
  exit 1
fi
'''
    script += f'''\
if ! restic --password-file {q(cfg["pwfile"])} -r "$repo" snapshots >/dev/null 2>&1; then
  restic --password-file {q(cfg["pwfile"])} -r "$repo" init >>"$log" 2>&1 || true
fi
restic --password-file {q(cfg["pwfile"])} -r "$repo" backup {q(cfg["backup_source"])} \\
  --exclude {q(cfg["drive_dir"])} --exclude {q(str(DATA_DIR))} \\
  --exclude-file {q(cfg["excludes_file"])} --retry-lock 10m \\
  --json >"$output" 2>>"$log"
'''
    _write_private(runner, script, executable=True)

    integrity_runner = DATA_DIR / "run-integrity.sh"
    integrity_script = f'''#!/bin/sh
set -u
export PATH={q(timer_path)}
export RCLONE_CONFIG={q(cfg["rclone_config"])}
export RCLONE_TRANSFERS={SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["transfers"]}
export RCLONE_CHECKERS={SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["checkers"]}
output={q(cfg["integrity_json"])}
log={q(cfg["integrity_log"])}
mkdir -p "$(dirname "$output")" "$(dirname "$log")"
if [ -f "$log" ] && [ "$(wc -c <"$log")" -gt 10485760 ]; then
  mv "$log" "$log.previous"
fi
ok=true
failed=""
checked=false
if [ -s {q(cfg["daily_json"])} ]; then
  checked=true
  if ! restic --password-file {q(cfg["pwfile"])} -r {q(cfg["repos"]["daily"])} check --retry-lock 10m --read-data-subset {SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["integrity_subset"]} >>"$log" 2>&1; then
    ok=false; failed="daily"
  fi
fi
if [ -s {q(cfg["weekly_json"])} ]; then
  checked=true
  if ! restic --password-file {q(cfg["pwfile"])} -r {q(cfg["repos"]["weekly"])} check --retry-lock 10m --read-data-subset {SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["integrity_subset"]} >>"$log" 2>&1; then
    ok=false; failed="${{failed:+$failed,}}weekly"
  fi
fi
if [ -s {q(cfg["monthly_json"])} ]; then
  checked=true
  if ! restic --password-file {q(cfg["pwfile"])} -r {q(cfg["repos"]["monthly"])} check --retry-lock 10m --read-data-subset {SPEED_PROFILES[cfg.get("speed_profile", "balanced")]["integrity_subset"]} >>"$log" 2>&1; then
    ok=false; failed="${{failed:+$failed,}}monthly"
  fi
fi
stamp="$(date +%Y-%m-%dT%H:%M:%S%z)"
tmp="$output.tmp"
printf '{{"ok":%s,"checked":%s,"checked_at":"%s","failed":"%s"}}\n' "$ok" "$checked" "$stamp" "$failed" >"$tmp"
mv "$tmp" "$output"
[ "$ok" = true ]
'''
    _write_private(integrity_runner, integrity_script, executable=True)

    for key, description in (("daily", "Daily"), ("weekly", "Weekly"),
                             ("monthly", "Monthly")):
        mount_want = " my-backups-rclone.service" if mount_remote else ""
        service = f'''[Unit]
Description=VaultLeaf {description.lower()} backup
After=network-online.target my-backups-rclone.service
Wants=network-online.target{mount_want}

[Service]
Type=oneshot
TimeoutStartSec=infinity
ExecStart={_unit_quote(runner)} {key}
'''
        if key == "daily":
            timer_value = _calendar(None, daily_time)
        elif key == "weekly":
            timer_value = _calendar(weekly_day, weekly_time)
        else:
            timer_value = _calendar_monthly(
                cfg["schedule"]["monthly_day"], cfg["schedule"]["monthly_time"])
        timer = f'''[Unit]
Description=Schedule VaultLeaf {description.lower()} backup

[Timer]
OnCalendar={timer_value}
Persistent=true

[Install]
WantedBy=timers.target
'''
        _write_private(USER_UNIT_DIR / f"my-backups-{key}.service", service)
        _write_private(USER_UNIT_DIR / f"my-backups-{key}.timer", timer)

    integrity_service = f'''[Unit]
Description=VaultLeaf repository integrity check
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
TimeoutStartSec=infinity
ExecStart={_unit_quote(integrity_runner)}
'''
    integrity_timer = f'''[Unit]
Description=Schedule VaultLeaf integrity check

[Timer]
OnCalendar={_calendar(cfg["schedule"]["integrity_day"], cfg["schedule"]["integrity_time"])}
Persistent=true

[Install]
WantedBy=timers.target
'''
    _write_private(USER_UNIT_DIR / "my-backups-integrity.service", integrity_service)
    _write_private(USER_UNIT_DIR / "my-backups-integrity.timer", integrity_timer)

    mount_unit = USER_UNIT_DIR / "my-backups-rclone.service"
    if mount_remote:
        cache_dir = DATA_DIR / "rclone-cache"
        profile = SPEED_PROFILES[cfg.get("speed_profile", "balanced")]
        unmount = shutil.which("fusermount3") or shutil.which("fusermount") or "/bin/fusermount"
        backend_option = (f" --drive-chunk-size {profile['chunk']}"
                          if cfg.get("storage_mode") == "oauth" else "")
        mount = f'''[Unit]
Description=VaultLeaf persistent storage folder
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
ExecStart={_unit_quote(str((bundled_tools / "rclone") if bundled_tools else (shutil.which("rclone") or "/usr/bin/rclone")))} mount {_unit_quote(mount_remote)} {_unit_quote(cfg["drive_dir"])} --config {_unit_quote(cfg["rclone_config"])} --cache-dir {_unit_quote(cache_dir)} --vfs-cache-mode writes --dir-cache-time 5m --transfers {profile["transfers"]} --checkers {profile["checkers"]}{backend_option} --retries 10 --low-level-retries 20 --timeout 5m
ExecStop={_unit_quote(unmount)} -uz {_unit_quote(cfg["drive_dir"])}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
'''
        _write_private(mount_unit, mount)
    elif mount_unit.exists():
        if has_systemd:
            _run_process(["systemctl", "--user", "disable", "--now",
                            "my-backups-rclone.service"], capture_output=True, timeout=20)
        mount_unit.unlink()

    if not has_systemd:
        _install_autostart()
        return False

    r = _run_process(["systemctl", "--user", "daemon-reload"],
                       capture_output=True, text=True, timeout=20)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "Could not reload the user service manager")
    timer_units = (("daily", "my-backups-daily.timer"),
                   ("weekly", "my-backups-weekly.timer"),
                   ("monthly", "my-backups-monthly.timer"),
                   ("integrity", "my-backups-integrity.timer"))
    for key, unit in timer_units:
        if not cfg.get("schedule_enabled", {}).get(key, True):
            _run_process(["systemctl", "--user", "disable", "--now", unit],
                           capture_output=True, text=True, timeout=30)
            continue
        r = _run_process(["systemctl", "--user", "enable", "--now", unit],
                           capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or f"Could not enable {unit}")
        _run_process(["systemctl", "--user", "restart", unit],
                       capture_output=True, text=True, timeout=30)
    if mount_remote:
        r = _run_process(["systemctl", "--user", "enable", "--now",
                            "my-backups-rclone.service"], capture_output=True,
                           text=True, timeout=40)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or "Could not start the cloud mount")
        r = _run_process(["systemctl", "--user", "restart",
                            "my-backups-rclone.service"], capture_output=True,
                           text=True, timeout=40)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or "Could not restart the cloud mount")
    _install_autostart()
    return True


def apply_setup(current_cfg, mode, source, location, daily_time="21:00",
                weekly_day="Sun", weekly_time="20:00", speed_profile="balanced",
                google_client_mode="shared", monthly_day="1", monthly_time="02:00",
                integrity_day="Mon", integrity_time="03:00", daily_enabled=True,
                weekly_enabled=True, monthly_enabled=True, integrity_enabled=True,
                smb_config=None):
    """Validate choices, create stable storage, and install persistent timers."""
    if not shutil.which("restic"):
        raise RuntimeError("restic is not installed")
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_dir():
        raise ValueError("The backup source folder does not exist")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_time):
        raise ValueError("Daily time must use HH:MM (24-hour time)")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", weekly_time):
        raise ValueError("Weekly time must use HH:MM (24-hour time)")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", monthly_time):
        raise ValueError("Monthly time must use HH:MM (24-hour time)")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", integrity_time):
        raise ValueError("Integrity time must use HH:MM (24-hour time)")
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    if weekly_day not in days or integrity_day not in days:
        raise ValueError("Choose a valid weekly day")
    if str(monthly_day) != "last":
        try:
            if not 1 <= int(monthly_day) <= 28:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a monthly day from 1–28 or last day") from exc
    if speed_profile not in SPEED_PROFILES:
        raise ValueError("Choose a valid connection speed")

    cfg = json.loads(json.dumps(current_cfg))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_dir = DATA_DIR / "logs"
    state_dir = DATA_DIR / "state"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    pwfile = DATA_DIR / "restic-passphrase.txt"
    excludes = DATA_DIR / "excludes.txt"
    if not pwfile.exists():
        _write_private(pwfile, secrets.token_urlsafe(36) + "\n")
    if not excludes.exists():
        _write_private(excludes, ".cache\n.Trash-*\n")

    mount_remote = None
    if mode == "oauth":
        if not shutil.which("rclone"):
            raise RuntimeError("rclone is not installed")
        remote = location.strip().rstrip(":")
        if remote not in configured_drive_remotes(cfg["rclone_config"]):
            raise ValueError("Choose a configured Google Drive account first")
        check = _run_process(["rclone", "lsd", f"{remote}:"], capture_output=True,
                               text=True, timeout=30,
                               env={**os.environ, "RCLONE_CONFIG": cfg["rclone_config"]})
        if check.returncode:
            raise RuntimeError(check.stderr.strip() or "Could not access that cloud account")
        drive_dir = Path.home() / "MyBackups" / "CloudDrive"
        if drive_dir == source_path or drive_dir in source_path.parents:
            raise ValueError("The folder being backed up cannot be inside the storage folder")
        drive_dir.mkdir(parents=True, exist_ok=True)
        base = f"rclone:{remote}:MyBackups/repositories"
        cfg["rclone_remote"] = remote
        mount_remote = f"{remote}:"
        cfg["mount_source"] = mount_remote
        cfg.update({"smb_host": "", "smb_share": "", "smb_user": ""})
    elif mode == "smb":
        if not shutil.which("rclone"):
            raise RuntimeError("rclone is not installed")
        values = smb_config or {}
        configured = configure_smb_remote(
            cfg["rclone_config"], values.get("remote", "vaultleaf-smb"),
            values.get("host", ""), values.get("share", ""),
            values.get("user", ""), values.get("password", ""),
            values.get("domain", "WORKGROUP"))
        drive_dir = Path(values.get("mount_dir") or
                         (Path.home() / "VaultLeaf" / "Network Share")).expanduser().resolve()
        if drive_dir == source_path or drive_dir in source_path.parents:
            raise ValueError("The folder being backed up cannot be inside the SMB mount folder")
        drive_dir.mkdir(parents=True, exist_ok=True)
        base = f"rclone:{configured['root']}/VaultLeaf/repositories"
        mount_remote = configured["root"]
        cfg["rclone_remote"] = configured["remote"]
        cfg["mount_source"] = mount_remote
        cfg.update({"smb_remote": configured["remote"],
                    "smb_host": configured["host"],
                    "smb_share": configured["share"],
                    "smb_user": configured["user"],
                    "smb_domain": configured["domain"]})
    elif mode == "folder":
        drive_dir = Path(location).expanduser().resolve()
        drive_dir.mkdir(parents=True, exist_ok=True)
        if not drive_dir.is_dir() or not os.access(drive_dir, os.W_OK):
            raise ValueError("The storage folder is not writable")
        if drive_dir == source_path or drive_dir in source_path.parents:
            raise ValueError("The folder being backed up cannot be inside the storage folder")
        repo_root = drive_dir / "MyBackups" / "repositories"
        repo_root.mkdir(parents=True, exist_ok=True)
        (drive_dir / ".my-backups-storage").touch(exist_ok=True)
        base = str(repo_root)
        cfg["rclone_remote"] = ""
        cfg["mount_source"] = ""
        cfg.update({"smb_host": "", "smb_share": "", "smb_user": ""})
    else:
        raise ValueError("Choose Google Drive, an SMB share, or folder storage")

    cfg.update({
        "setup_complete": True, "storage_mode": mode, "systemd_user": True,
        "speed_profile": speed_profile, "google_client_mode": google_client_mode,
        "backup_source": str(source_path), "drive_dir": str(drive_dir),
        "pwfile": str(pwfile), "excludes_file": str(excludes),
        "backup_scripts_dir": str(DATA_DIR),
        "daily_json": str(state_dir / "backup-daily.json"),
        "weekly_json": str(state_dir / "backup-weekly.json"),
        "monthly_json": str(state_dir / "backup-monthly.json"),
        "daily_log": str(log_dir / "backup-daily.log"),
        "weekly_log": str(log_dir / "backup-weekly.log"),
        "monthly_log": str(log_dir / "backup-monthly.log"),
        "integrity_json": str(state_dir / "integrity.json"),
        "integrity_log": str(log_dir / "integrity.log"),
        "repos": {"daily": f"{base}/daily", "weekly": f"{base}/weekly",
                  "monthly": f"{base}/monthly"},
        "services": {"daily": "my-backups-daily.service",
                     "weekly": "my-backups-weekly.service",
                     "monthly": "my-backups-monthly.service"},
        "timers": {"Daily": "my-backups-daily.timer",
                   "Weekly": "my-backups-weekly.timer",
                   "Monthly": "my-backups-monthly.timer",
                   "Integrity": "my-backups-integrity.timer"},
        "schedule": {"daily_time": daily_time, "weekly_day": weekly_day,
                     "weekly_time": weekly_time, "monthly_day": str(monthly_day),
                     "monthly_time": monthly_time, "integrity_day": integrity_day,
                     "integrity_time": integrity_time},
        "schedule_enabled": {"daily": bool(daily_enabled),
                             "weekly": bool(weekly_enabled),
                             "monthly": bool(monthly_enabled),
                             "integrity": bool(integrity_enabled)},
    })
    # Revalidate manually edited exclusions against the newly selected source.
    save_excludes(cfg, get_excludes(cfg))
    has_systemd = _install_user_units(
        cfg, daily_time, weekly_day, weekly_time, mount_remote)
    cfg["scheduler_backend"] = "systemd" if has_systemd else "internal"
    cfg["systemd_user"] = has_systemd
    if not has_systemd:
        initialize_portable_schedule()
        if mount_remote and not ensure_portable_mount(cfg):
            raise RuntimeError("Could not start the portable cloud mount")
    save_config(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def start_backup(cfg, key, on_done=None):
    """Start a backup service via pkexec/sudo in a background thread."""
    svc = cfg["services"].get(key)
    if not svc:
        return

    def _run():
        if cfg.get("scheduler_backend") == "internal":
            try:
                _popen_process([str(DATA_DIR / "run-backup.sh"), key],
                                 start_new_session=True)
                if on_done:
                    on_done(True, f"Started {key} backup")
            except Exception as exc:  # noqa: BLE001
                if on_done:
                    on_done(False, str(exc))
            return
        if cfg.get("systemd_user"):
            try:
                r = _systemctl(cfg, "start", "--no-block", svc, timeout=30)
                ok = r.returncode == 0
                if on_done:
                    on_done(ok, f"Started {svc}" if ok else
                            (r.stderr.strip() or f"Could not start {svc}"))
                return
            except Exception as e:  # noqa: BLE001
                if on_done:
                    on_done(False, str(e))
                return
        for cmd in (["pkexec", "systemctl", "start", svc],
                    ["sudo", "systemctl", "start", svc]):
            try:
                r = _run_process(cmd, capture_output=True, text=True, timeout=120)
                if r.returncode == 0:
                    if on_done:
                        on_done(True, f"Started {svc}")
                    return
            except Exception:
                continue
        if on_done:
            on_done(False, f"Could not start {svc} — run: sudo systemctl start {svc}")

    threading.Thread(target=_run, daemon=True).start()


def start_integrity_check(cfg, on_done=None):
    def work():
        try:
            if cfg.get("scheduler_backend") == "internal":
                _popen_process([str(DATA_DIR / "run-integrity.sh")],
                                 start_new_session=True)
                ok, message = True, "Integrity check started in the background."
            else:
                result = _systemctl(cfg, "start", "--no-block",
                                    "my-backups-integrity.service", timeout=30)
                ok = result.returncode == 0
                message = ("Integrity check started in the background." if ok else
                           (result.stderr.strip() or "Could not start the integrity check."))
        except Exception as exc:  # noqa: BLE001
            ok, message = False, str(exc)
        if on_done:
            on_done(ok, message)
    threading.Thread(target=work, daemon=True).start()


def open_folder(path):
    for cmd in (["xdg-open", path], ["gio", "open", path]):
        try:
            _popen_process(cmd)
            return
        except Exception:
            continue


class RestoreJob:
    """Runs `restic restore` in the background, streaming readable output.

    Uses ``--json`` so we can show a progress bar and a clean summary.
    ``percent`` and ``lines`` are safe to read from the UI thread.
    """

    def __init__(self, cfg, repo, snapshot, target, include=None):
        self.cfg = cfg
        self.repo = repo
        self.snapshot = snapshot
        self.target = target
        self.include = include
        self.lines = []
        self.lock = threading.Lock()
        self.percent = None
        self.done = False
        self.ok = None
        self.error = None
        self.cancelled = False
        self._proc = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def cancel(self):
        """Ask restic to stop, without blocking the UI thread."""
        self.cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGINT)
            except OSError:
                pass

    def _run(self):
        try:
            Path(self.target).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.ok = False
            self.error = f"Could not create the restore folder: {exc}"
            self.done = True
            return
        cmd = ["restic", "--password-file", self.cfg["pwfile"], "-r", self.repo,
               "restore", self.snapshot, "--target", self.target, "--json"]
        if self.include:
            cmd += ["--include", self.include]
        env = os.environ.copy()
        env["RCLONE_CONFIG"] = self.cfg["rclone_config"]
        last_shown = -1.0
        try:
            proc = _popen_process(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, env=env)
            self._proc = proc
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    with self.lock:
                        self.lines.append(line)
                    continue
                mt = d.get("message_type")
                if mt == "status" and "percent_done" in d:
                    pct = d["percent_done"]
                    self.percent = pct
                    shown = int(pct * 100)
                    if shown > last_shown:
                        last_shown = shown
                        with self.lock:
                            self.lines.append(
                                f"restoring… {shown}%  "
                                f"({fmt_bytes(d.get('bytes_done', 0))} / "
                                f"{fmt_bytes(d.get('total_bytes', 0))})")
                elif mt == "summary":
                    with self.lock:
                        self.lines.append(
                            f"✓ Restored {d.get('files_restored', 0)} files "
                            f"({fmt_bytes(d.get('total_bytes_restored', 0))})")
                elif mt in ("error", "fatal"):
                    with self.lock:
                        self.lines.append("✗ " + line)
            proc.wait()
            self.ok = proc.returncode == 0 and not self.cancelled
            if self.cancelled:
                self.error = "Restore cancelled"
            elif not self.ok:
                self.error = f"restic exited with code {proc.returncode}"
        except Exception as e:  # noqa: BLE001
            self.ok = False
            self.error = str(e)
        self.done = True
        self._proc = None

    def snapshot_lines(self):
        """Drain buffered output (called from the UI thread)."""
        with self.lock:
            out = list(self.lines)
        self.lines.clear()
        return out


class Cache:
    """Periodically refreshes heavy data (Drive space, snapshots, timers)
    in a background thread; the UI polls these cached values every tick."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.about = None
        self.snapshots = {"daily": [], "weekly": [], "monthly": []}
        self.timers = []
        self._stop = False
        self._t = {"about": 0.0, "snap": 0.0, "timers": 0.0}
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        while not self._stop:
            now = time.time()
            speed = self.cfg.get("speed_profile", "balanced")
            cloud_interval = {"reliable": 300, "balanced": 60, "fast": 30}.get(speed, 60)
            if now - self._t["about"] > cloud_interval:
                try:
                    self.about = get_about(self.cfg)
                except Exception:
                    pass
                self._t["about"] = now
            if now - self._t["snap"] > cloud_interval:
                for key, repo in self.cfg["repos"].items():
                    try:
                        self.snapshots[key] = get_snapshots(self.cfg, repo)
                    except Exception:
                        pass
                self._t["snap"] = now
            if now - self._t["timers"] > 30:
                try:
                    self.timers = get_timers(self.cfg)
                except Exception:
                    pass
                self._t["timers"] = now
            time.sleep(5)
