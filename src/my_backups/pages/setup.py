"""Friendly guided setup wizard and schedule manager."""
import threading
from pathlib import Path

from gi.repository import GLib, Gtk

from .. import backend as B


class TimePicker(Gtk.Box):
    """A compact 24-hour time picker that cannot contain invalid input."""

    def __init__(self, value):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
        except (ValueError, AttributeError):
            hour, minute = 0, 0
        self.hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.minute = Gtk.SpinButton.new_with_range(0, 59, 1)
        for widget, number in ((self.hour, hour), (self.minute, minute)):
            widget.set_value(number)
            widget.set_width_chars(2)
            widget.set_numeric(True)
        self.append(self.hour)
        self.append(Gtk.Label(label=":"))
        self.append(self.minute)

    def get_text(self):
        return f"{self.hour.get_value_as_int():02d}:{self.minute.get_value_as_int():02d}"


class SetupPage(Gtk.Box):
    DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    STEP_NAMES = ("Welcome", "Storage", "Backup", "Schedule", "Review")

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.app = app
        self.cfg = app.cfg
        self.cache = app.cache
        self.step = 0
        self.set_margin_top(14)
        self.set_margin_bottom(14)
        self.set_margin_start(18)
        self.set_margin_end(18)
        self._build()

    # ---------------------------------------------------------------- wizard
    def _build(self):
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        title = Gtk.Label(label="VaultLeaf Backup setup", xalign=0)
        title.add_css_class("title-1")
        header.append(title)
        self.step_label = Gtk.Label(xalign=0)
        self.step_label.add_css_class("title-3")
        header.append(self.step_label)
        self.progress = Gtk.ProgressBar()
        header.append(self.progress)
        self.crumbs = Gtk.Label(xalign=0, wrap=True)
        self.crumbs.add_css_class("dim-label")
        header.append(self.crumbs)
        self.append(header)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        if self.cfg.get("setup_complete"):
            setup_banner = Gtk.Label(
                label="✓ Already set up — these are your current settings. "
                      "Change anything below and press Save changes.",
                xalign=0, wrap=True)
            setup_banner.add_css_class("success")
            setup_banner.set_margin_top(8)
            setup_banner.set_margin_bottom(4)
            self.append(setup_banner)

        self.wizard = Gtk.Stack()
        self.wizard.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.wizard.set_transition_duration(220)
        self.wizard.set_vexpand(True)
        self.append(self.wizard)

        self._build_welcome()
        self._build_storage()
        self._build_backup()
        self._build_schedule()
        self._build_review()

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(10)
        self.status = Gtk.Label(label="", xalign=0, wrap=True)
        self.status.set_hexpand(True)
        footer.append(self.status)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        footer.append(self.spinner)
        self.back_btn = Gtk.Button(label="Back")
        self.back_btn.connect("clicked", lambda *_: self._move(-1))
        self.next_btn = Gtk.Button(label="Next")
        self.next_btn.add_css_class("suggested-action")
        self.next_btn.connect("clicked", lambda *_: self._move(1))
        self.apply_btn = Gtk.Button(
            label="Save changes" if self.cfg.get("setup_complete") else "Finish setup")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self._apply)
        footer.append(self.back_btn)
        footer.append(self.next_btn)
        footer.append(self.apply_btn)
        self.append(footer)

        self._refresh_remotes()
        self._mode_changed()
        self._auth_mode_changed()
        self._set_step(0)

    def _new_page(self, title, subtitle):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(6)
        content.set_margin_end(12)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("title-2")
        content.append(heading)
        content.append(Gtk.Label(label=subtitle, xalign=0, wrap=True))
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(content)
        return content, scroller

    @staticmethod
    def _frame(title):
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        frame.set_child(box)
        return frame, box

    @staticmethod
    def _row(label, widget, button=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        caption = Gtk.Label(label=label, xalign=0)
        caption.set_size_request(150, -1)
        row.append(caption)
        widget.set_hexpand(True)
        row.append(widget)
        if button is not None:
            row.append(button)
        return row

    def _set_step(self, step):
        self.step = max(0, min(len(self.STEP_NAMES) - 1, step))
        self.wizard.set_visible_child_name(f"step-{self.step}")
        self.step_label.set_label(
            f"Step {self.step + 1} of {len(self.STEP_NAMES)} — {self.STEP_NAMES[self.step]}")
        self.progress.set_fraction((self.step + 1) / len(self.STEP_NAMES))
        self.crumbs.set_label("  ›  ".join(
            f"● {name}" if index == self.step else name
            for index, name in enumerate(self.STEP_NAMES)))
        self.back_btn.set_sensitive(self.step > 0)
        self.next_btn.set_visible(self.step < len(self.STEP_NAMES) - 1)
        self.apply_btn.set_visible(self.step == len(self.STEP_NAMES) - 1)
        self.status.set_label("")
        if self.step == len(self.STEP_NAMES) - 1:
            self._update_review()

    def _move(self, amount):
        if amount > 0 and not self._validate_step():
            return
        self._set_step(self.step + amount)

    def _validate_step(self):
        if self.step == 1:
            if self.mode.get_selected() == 0 and not self._selected_remote():
                return self._error("Connect or select a Google Drive account before continuing.")
            if self.mode.get_selected() == 1 and not self.folder_entry.get_text().strip():
                return self._error("Choose a storage folder before continuing.")
            if self.mode.get_selected() == 2:
                if not self.smb_host.get_text().strip():
                    return self._error("Enter the SMB server name or IP address.")
                if not self.smb_share.get_text().strip():
                    return self._error("Enter the shared folder name.")
                if not self.smb_user.get_text().strip():
                    return self._error("Enter the SMB username, or use 'guest'.")
                if not self.smb_mount.get_text().strip():
                    return self._error("Choose where the SMB share should appear locally.")
        elif self.step == 2:
            source_text = self.source_entry.get_text().strip()
            if not source_text:
                return self._error("Choose a folder to back up.")
            source = Path(source_text).expanduser().resolve()
            if not source.is_dir():
                return self._error("Choose an existing folder to back up.")
            if self.mode.get_selected() in (1, 2):
                storage_text = (self.folder_entry.get_text().strip()
                                if self.mode.get_selected() == 1 else
                                self.smb_mount.get_text().strip())
                storage = Path(storage_text).expanduser().resolve()
                if storage == source or storage in source.parents:
                    return self._error(
                        "The folder being backed up cannot be inside the storage folder.")
        return True

    def _error(self, message):
        self.status.set_label(message)
        self.app.window.toast(message, "error")
        return False

    # -------------------------------------------------------------- page one
    def _build_welcome(self):
        page, wrapper = self._new_page(
            "Welcome",
            "This assistant will create private, automatic backups without requiring "
            "technical configuration. Nothing is changed until the final step.")

        frame, box = self._frame("What the assistant will do")
        for text in (
                "✓ Connect Google Drive, an SMB network share, or a trusted folder",
                "✓ Create encrypted daily, weekly, and monthly repositories",
                "✓ Keep schedules running after restarts and catch up missed jobs",
                "✓ Monitor integrity and show a popup if a repository fails",
                "✓ Run quietly in the background with tray controls"):
            box.append(Gtk.Label(label=text, xalign=0, wrap=True))
        page.append(frame)

        if self.cfg.get("setup_complete"):
            current_frame, current_box = self._frame("Current setup")
            current_box.append(Gtk.Label(
                label="✓ VaultLeaf is already configured. Walk through the assistant to make "
                      "changes, or jump directly to the current plan.", xalign=0, wrap=True))
            review = Gtk.Button(label="Review current backup plan")
            review.set_halign(Gtk.Align.START)
            review.connect("clicked", lambda *_: self._set_step(4))
            current_box.append(review)
            page.append(current_frame)

        install_frame, install_box = self._frame("Required components")
        missing = B.missing_dependencies()
        self.install_status = Gtk.Label(xalign=0, wrap=True)
        self.install_status.set_label(
            "Missing: " + ", ".join(missing) if missing else
            "✓ restic, rclone, and FUSE are installed")
        install_box.append(self.install_status)
        self.install_btn = Gtk.Button(
            label="Install missing components — administrator approval once")
        self.install_btn.set_halign(Gtk.Align.START)
        self.install_btn.connect("clicked", self._install_components)
        self.install_btn.set_sensitive(bool(missing))
        install_box.append(self.install_btn)
        note = Gtk.Label(
            label="After installation, backups and schedules run as your normal user and do "
                  "not repeatedly ask for a password.", xalign=0, wrap=True)
        note.add_css_class("dim-label")
        install_box.append(note)
        page.append(install_frame)

        admin_frame, admin_box = self._frame("Permanent admin permission")
        self.admin_status = Gtk.Label(label="Checking…", xalign=0, wrap=True)
        admin_box.append(self.admin_status)
        self.admin_btn = Gtk.Button(
            label="Grant permanent permission — one-time password")
        self.admin_btn.set_halign(Gtk.Align.START)
        self.admin_btn.connect("clicked", self._grant_admin)
        admin_box.append(self.admin_btn)
        admin_note = Gtk.Label(
            label="Only used for bootable system-image backups. You enter your "
                  "administrator password once; afterwards the image backup runs "
                  "without asking again.", xalign=0, wrap=True)
        admin_note.add_css_class("dim-label")
        admin_box.append(admin_note)
        page.append(admin_frame)
        GLib.idle_add(self._refresh_admin_status)

        self.wizard.add_named(wrapper, "step-0")

    # -------------------------------------------------------------- page two
    def _build_storage(self):
        page, wrapper = self._new_page(
            "Choose where backups are stored",
            "Use Google Drive, a Windows/NAS network share, or a folder. VaultLeaf keeps "
            "network storage connected automatically after restarts.")

        method_frame, method_box = self._frame("Storage method")
        self.mode = Gtk.DropDown(model=Gtk.StringList.new([
            "Google Drive account",
            "Local, external, or synced folder",
            "Windows or NAS network share (SMB)"
        ]))
        mode_index = {"oauth": 0, "folder": 1, "smb": 2}
        self.mode.set_selected(mode_index.get(self.cfg.get("storage_mode"), 0))
        self.mode.connect("notify::selected", self._mode_changed)
        method_box.append(self._row("Store backups in", self.mode))
        page.append(method_frame)

        self.cloud_frame, cloud = self._frame("Google Drive")
        provider = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        logo_path = Path(__file__).parent.parent / "data" / "google-drive.svg"
        logo = Gtk.Image.new_from_file(str(logo_path))
        logo.set_pixel_size(38)
        provider.append(logo)
        provider_text = Gtk.Label(
            label="Back up securely to your Google Drive account", xalign=0)
        provider_text.add_css_class("title-3")
        provider.append(provider_text)
        cloud.append(provider)
        self.remote_dd = Gtk.DropDown()
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self._refresh_remotes())
        cloud.append(self._row("Connected account", self.remote_dd, refresh))

        self.auth_mode = Gtk.DropDown(model=Gtk.StringList.new([
            "Easy shared rclone client", "Private Google API client JSON (advanced)"
        ]))
        self.auth_mode.set_selected(
            1 if self.cfg.get("google_client_mode") == "private" else 0)
        self.auth_mode.connect("notify::selected", self._auth_mode_changed)
        cloud.append(self._row("Connection method", self.auth_mode))

        self.json_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        json_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.json_entry = Gtk.Entry()
        self.json_entry.set_placeholder_text("Google Desktop OAuth client JSON")
        self.json_entry.set_hexpand(True)
        json_choose = Gtk.Button(label="Choose JSON…")
        json_choose.connect("clicked", lambda *_: self._choose_json())
        json_find = Gtk.Button(label="Find file…")
        json_find.connect("clicked", lambda *_: self._find_json())
        json_row.append(self.json_entry)
        json_row.append(json_choose)
        json_row.append(json_find)
        self.json_box.append(json_row)
        help_label = Gtk.Label(xalign=0, wrap=True)
        help_label.set_markup(
            "Create a Desktop OAuth client, add your Google account as a test "
            "user, then download its JSON — it is saved as <b>client_secret_…"
            "json</b>, usually in your <b>Downloads</b> folder. "
            "<a href=\"https://rclone.org/drive/#making-your-own-client-id\">"
            "Open step-by-step instructions</a>.")
        help_label.add_css_class("dim-label")
        self.json_box.append(help_label)
        cloud.append(self.json_box)

        connect = Gtk.Button(label="Add a Google Drive account…")
        connect.add_css_class("suggested-action")
        connect.set_halign(Gtk.Align.START)
        connect.connect("clicked", self._connect_cloud)
        self.connect_btn = connect
        cloud.append(connect)
        page.append(self.cloud_frame)

        self.folder_frame, folder = self._frame("Storage folder")
        self.folder_entry = Gtk.Entry()
        folder_default = (self.cfg.get("drive_dir")
                          if self.cfg.get("storage_mode") == "folder"
                          else str(Path.home() / "MyBackups" / "Storage"))
        self.folder_entry.set_text(folder_default)
        choose = Gtk.Button(label="Browse…")
        choose.connect("clicked", lambda *_: self._choose_folder(self.folder_entry))
        folder.append(self._row("Folder", self.folder_entry, choose))
        safety = Gtk.Label(
            label="External and network storage receives a safety marker. If it is missing, "
                  "a scheduled backup stops instead of filling the wrong disk.",
            xalign=0, wrap=True)
        safety.add_css_class("dim-label")
        folder.append(safety)
        page.append(self.folder_frame)

        self.smb_frame, smb = self._frame("SMB network share")
        smb.append(Gtk.Label(
            label="For a Windows shared folder, NAS, home server, or Samba server. Enter "
                  "the same login you use to open the share on another computer.",
            xalign=0, wrap=True))
        self.smb_host = Gtk.Entry()
        self.smb_host.set_text(self.cfg.get("smb_host", ""))
        self.smb_host.set_placeholder_text("Example: nas.local or 192.168.1.50")
        smb.append(self._row("Server or IP", self.smb_host))
        self.smb_share = Gtk.Entry()
        self.smb_share.set_text(self.cfg.get("smb_share", ""))
        self.smb_share.set_placeholder_text("Example: Backups")
        smb.append(self._row("Shared folder name", self.smb_share))
        self.smb_user = Gtk.Entry()
        self.smb_user.set_text(self.cfg.get("smb_user", ""))
        self.smb_user.set_placeholder_text("Use guest for a guest share")
        smb.append(self._row("Username", self.smb_user))
        self.smb_password = Gtk.Entry()
        self.smb_password.set_visibility(False)
        self.smb_password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.smb_password.set_placeholder_text(
            "Leave blank to keep the saved password" if self.cfg.get("smb_host") else
            "SMB password (blank is allowed for guest)")
        show_password = Gtk.CheckButton(label="Show password")
        show_password.connect(
            "toggled", lambda button: self.smb_password.set_visibility(button.get_active()))
        password_row = self._row("Password", self.smb_password, show_password)
        smb.append(password_row)
        self.smb_domain = Gtk.Entry()
        self.smb_domain.set_text(self.cfg.get("smb_domain", "WORKGROUP"))
        self.smb_domain.set_placeholder_text("WORKGROUP")
        smb.append(self._row("Domain / workgroup", self.smb_domain))
        self.smb_mount = Gtk.Entry()
        smb_default = (self.cfg.get("drive_dir") if self.cfg.get("storage_mode") == "smb"
                       else str(Path.home() / "VaultLeaf" / "Network Share"))
        self.smb_mount.set_text(smb_default)
        smb_browse = Gtk.Button(label="Browse…")
        smb_browse.connect("clicked", lambda *_: self._choose_folder(self.smb_mount))
        smb.append(self._row("Available locally at", self.smb_mount, smb_browse))
        test_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.smb_test_btn = Gtk.Button(label="Test SMB connection")
        self.smb_test_btn.add_css_class("suggested-action")
        self.smb_test_btn.connect("clicked", self._test_smb)
        self.smb_test_status = Gtk.Label(label="", xalign=0, wrap=True)
        self.smb_test_status.add_css_class("dim-label")
        test_row.append(self.smb_test_btn)
        test_row.append(self.smb_test_status)
        smb.append(test_row)
        smb_note = Gtk.Label(
            label="The password is stored obscured in rclone's private configuration, not in "
                  "VaultLeaf settings. The share reconnects automatically after login and "
                  "retries if the network is temporarily unavailable.", xalign=0, wrap=True)
        smb_note.add_css_class("dim-label")
        smb.append(smb_note)
        page.append(self.smb_frame)
        self.wizard.add_named(wrapper, "step-1")

    # ------------------------------------------------------------ page three
    def _build_backup(self):
        page, wrapper = self._new_page(
            "Choose what to protect",
            "Most people select their home folder. The backup destination and application "
            "data are automatically excluded to prevent loops.")

        source_frame, source_box = self._frame("Backup source")
        self.source_entry = Gtk.Entry()
        self.source_entry.set_text(self.cfg.get("backup_source") or str(Path.home()))
        choose = Gtk.Button(label="Browse…")
        choose.connect("clicked", lambda *_: self._choose_folder(self.source_entry))
        source_box.append(self._row("Folder to back up", self.source_entry, choose))
        page.append(source_frame)

        speed_frame, speed_box = self._frame("Connection profile")
        self.speed = Gtk.DropDown(model=Gtk.StringList.new([
            "Reliable — slower networks and small chunks",
            "Balanced — recommended for most connections",
            "Fast — more parallel transfers and larger chunks"
        ]))
        profiles = ("reliable", "balanced", "fast")
        selected = self.cfg.get("speed_profile", "balanced")
        self.speed.set_selected(profiles.index(selected) if selected in profiles else 1)
        speed_box.append(self._row("Transfer behavior", self.speed))
        speed_box.append(Gtk.Label(
            label="The profile also adjusts retries, cloud refresh frequency, and integrity "
                  "sampling. It can be changed later without losing backups.",
            xalign=0, wrap=True))
        page.append(speed_frame)

        excludes_frame, excludes_box = self._frame("Files you do not want backed up")
        excludes_box.append(Gtk.Label(
            label="Recommended cache and trash exclusions are created automatically. You can "
                  "browse for additional files or folders in Settings.", xalign=0, wrap=True))
        excludes_btn = Gtk.Button(label="Open exclusions editor…")
        excludes_btn.set_halign(Gtk.Align.START)
        excludes_btn.connect("clicked", self._open_exclusions)
        excludes_box.append(excludes_btn)
        page.append(excludes_frame)

        image_frame, image_box = self._frame("Monthly backup type")
        self.monthly_image = Gtk.CheckButton(
            label="Bootable system image - whole OS with all files and apps")
        self.monthly_image.set_active(
            self.cfg.get("monthly_mode") == "system_image")
        image_box.append(self.monthly_image)
        self.system_disk = Gtk.Entry()
        self.system_disk.set_text(self.cfg.get("system_disk") or "")
        self.system_disk.set_placeholder_text("Auto-detect (e.g. /dev/nvme0n1)")
        image_box.append(self._row("System disk (optional)", self.system_disk))
        image_box.append(Gtk.Label(
            label="When enabled, the monthly backup is a complete bootable copy "
                  "of the operating system. Restore by copying it onto any drive "
                  "and booting from it. Requires your admin password each run.",
            xalign=0, wrap=True))
        page.append(image_frame)
        self.wizard.add_named(wrapper, "step-2")

    # ------------------------------------------------------------- page four
    def _build_schedule(self):
        page, wrapper = self._new_page(
            "Choose automatic schedules",
            "Enable only the jobs you want. Times use the computer's local timezone, and every "
            "backup remains available manually from the app menu.")
        sched = self.cfg.get("schedule", {})
        enabled = self.cfg.get("schedule_enabled", {})

        self.daily_enabled = Gtk.CheckButton(label="Daily backup")
        self.daily_enabled.set_active(enabled.get("daily", True))
        self.daily_time = TimePicker(sched.get("daily_time", "21:00"))
        page.append(self._schedule_card(
            self.daily_enabled, "A quick recovery point every day", self.daily_time))

        self.weekly_enabled = Gtk.CheckButton(label="Weekly backup")
        self.weekly_enabled.set_active(enabled.get("weekly", True))
        weekly_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.weekly_day = Gtk.DropDown(model=Gtk.StringList.new(list(self.DAYS)))
        weekly_day = sched.get("weekly_day", "Sun")
        self.weekly_day.set_selected(self.DAYS.index(weekly_day) if weekly_day in self.DAYS else 6)
        self.weekly_time = TimePicker(sched.get("weekly_time", "20:00"))
        weekly_controls.append(self.weekly_day)
        weekly_controls.append(Gtk.Label(label="at"))
        weekly_controls.append(self.weekly_time)
        page.append(self._schedule_card(
            self.weekly_enabled, "A separate longer-term weekly history", weekly_controls))

        self.monthly_enabled = Gtk.CheckButton(label="Monthly backup")
        self.monthly_enabled.set_active(enabled.get("monthly", True))
        monthly_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        monthly_days = [str(value) for value in range(1, 29)] + ["Last day"]
        self.monthly_day = Gtk.DropDown(model=Gtk.StringList.new(monthly_days))
        saved_day = sched.get("monthly_day", "1")
        try:
            month_index = 28 if saved_day == "last" else min(27, max(0, int(saved_day) - 1))
        except (TypeError, ValueError):
            month_index = 0
        self.monthly_day.set_selected(month_index)
        self.monthly_time = TimePicker(sched.get("monthly_time", "02:00"))
        monthly_controls.append(Gtk.Label(label="Day"))
        monthly_controls.append(self.monthly_day)
        monthly_controls.append(Gtk.Label(label="at"))
        monthly_controls.append(self.monthly_time)
        page.append(self._schedule_card(
            self.monthly_enabled, "A separate archive once per month", monthly_controls))

        self.integrity_enabled = Gtk.CheckButton(label="Integrity check")
        self.integrity_enabled.set_active(enabled.get("integrity", True))
        integrity_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.integrity_day = Gtk.DropDown(model=Gtk.StringList.new(list(self.DAYS)))
        integrity_day = sched.get("integrity_day", "Mon")
        self.integrity_day.set_selected(
            self.DAYS.index(integrity_day) if integrity_day in self.DAYS else 0)
        self.integrity_time = TimePicker(sched.get("integrity_time", "03:00"))
        integrity_controls.append(self.integrity_day)
        integrity_controls.append(Gtk.Label(label="at"))
        integrity_controls.append(self.integrity_time)
        page.append(self._schedule_card(
            self.integrity_enabled,
            "Checks repository structure and samples stored data; failures show a popup",
            integrity_controls))
        self.wizard.add_named(wrapper, "step-3")

    def _schedule_card(self, toggle, explanation, controls):
        frame = Gtk.Frame()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text.set_hexpand(True)
        text.append(toggle)
        note = Gtk.Label(label=explanation, xalign=0, wrap=True)
        note.add_css_class("dim-label")
        text.append(note)
        box.append(text)
        box.append(controls)
        controls.set_sensitive(toggle.get_active())
        toggle.connect("toggled", lambda button: controls.set_sensitive(button.get_active()))
        frame.set_child(box)
        return frame

    # ------------------------------------------------------------- page five
    def _build_review(self):
        page, wrapper = self._new_page(
            "Review and finish",
            "Check the summary below. Use Back to change anything. Applying updates schedules "
            "safely and never deletes existing backup snapshots.")
        review_frame, review_box = self._frame("Your backup plan")
        self.review_label = Gtk.Label(label="", xalign=0, wrap=True, selectable=True)
        review_box.append(self.review_label)
        page.append(review_frame)
        note_frame, note_box = self._frame("What happens next")
        note_box.append(Gtk.Label(
            label="The app creates private credentials, repositories, background startup, "
                  "persistent schedules, logs, and a cloud or SMB mount when selected.",
            xalign=0, wrap=True))
        note_box.append(Gtk.Label(
            label="Your original files are never changed. Existing repositories and passwords "
                  "are preserved when settings are updated.", xalign=0, wrap=True))
        page.append(note_frame)
        self.wizard.add_named(wrapper, "step-4")

    def _update_review(self):
        if self.mode.get_selected() == 0:
            mode = "Google Drive — " + (self._selected_remote() or "no account selected")
        elif self.mode.get_selected() == 1:
            mode = "Folder — " + self.folder_entry.get_text().strip()
        else:
            mode = (f"SMB — smb://{self.smb_host.get_text().strip()}/"
                    f"{self.smb_share.get_text().strip()}\n"
                    f"Mounted at: {self.smb_mount.get_text().strip()}")
        speeds = ("Reliable", "Balanced", "Fast")
        jobs = []
        if self.daily_enabled.get_active():
            jobs.append(f"Daily at {self.daily_time.get_text()}")
        if self.weekly_enabled.get_active():
            jobs.append(f"Weekly on {self.DAYS[self.weekly_day.get_selected()]} "
                        f"at {self.weekly_time.get_text()}")
        if self.monthly_enabled.get_active():
            month = self.monthly_day.get_selected()
            day = "last day" if month == 28 else f"day {month + 1}"
            if self.monthly_image.get_active():
                jobs.append("Monthly: bootable system image of the whole OS")
            else:
                jobs.append(f"Monthly on {day} at {self.monthly_time.get_text()}")
        if self.integrity_enabled.get_active():
            jobs.append(f"Integrity check on {self.DAYS[self.integrity_day.get_selected()]} "
                        f"at {self.integrity_time.get_text()}")
        schedule = "\n  • ".join(jobs) if jobs else "Manual backups only"
        self.review_label.set_label(
            f"Storage: {mode}\n"
            f"Backup source: {self.source_entry.get_text().strip()}\n"
            f"Connection profile: {speeds[self.speed.get_selected()]}\n\n"
            f"Automatic jobs:\n  • {schedule}")

    # --------------------------------------------------------------- storage
    def _mode_changed(self, *_args):
        selected = self.mode.get_selected()
        self.cloud_frame.set_visible(selected == 0)
        self.folder_frame.set_visible(selected == 1)
        self.smb_frame.set_visible(selected == 2)

    def _auth_mode_changed(self, *_args):
        self.json_box.set_visible(self.auth_mode.get_selected() == 1)

    def _refresh_remotes(self, select=None):
        remotes = B.configured_drive_remotes(self.cfg.get("rclone_config"))
        self.remote_dd.set_model(Gtk.StringList.new(remotes))
        wanted = select or self.cfg.get("rclone_remote")
        if wanted in remotes:
            self.remote_dd.set_selected(remotes.index(wanted))
        elif remotes:
            self.remote_dd.set_selected(0)
        else:
            self.remote_dd.set_selected(Gtk.INVALID_LIST_POSITION)

    def _selected_remote(self):
        item = self.remote_dd.get_selected_item()
        return item.get_string() if item is not None else ""

    def _connect_cloud(self, _button):
        dialog = Gtk.Dialog(title="Connect Google Drive", transient_for=self.app.window,
                            modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Open secure sign-in", Gtk.ResponseType.ACCEPT)
        area = dialog.get_content_area()
        area.set_spacing(8)
        for method, value in ((area.set_margin_top, 12), (area.set_margin_bottom, 12),
                              (area.set_margin_start, 12), (area.set_margin_end, 12)):
            method(value)
        area.append(Gtk.Label(
            label="Give the account a short name. Your browser opens for Google OAuth sign-in.",
            xalign=0, wrap=True))
        name = Gtk.Entry()
        name.set_text("gdrive-private" if self.auth_mode.get_selected() == 1 else "gdrive")
        name.set_placeholder_text("Example: personal-drive")
        area.append(name)
        dialog.connect("response", self._connect_response, name)
        dialog.present()

    def _connect_response(self, dialog, response, name_entry):
        name = name_entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        callback = lambda success, message, remote: GLib.idle_add(
            self._oauth_finished, success, message, remote)
        if self.auth_mode.get_selected() == 1:
            ok, message = B.create_google_drive_remote_with_client(
                name, self.cfg.get("rclone_config"),
                self.json_entry.get_text().strip(), callback)
        else:
            ok, message = B.create_google_drive_remote(
                name, self.cfg.get("rclone_config"), callback)
        self.status.set_label(message)
        self.connect_btn.set_sensitive(not ok)
        if not ok:
            self.app.window.toast(message, "error")

    def _oauth_finished(self, success, message, remote):
        self.connect_btn.set_sensitive(True)
        self._refresh_remotes(remote if success else None)
        self.status.set_label(message)
        self.app.window.toast(message, "info" if success else "error")
        return False

    # -------------------------------------------------------------- choosers
    def _choose_folder(self, entry):
        dialog = Gtk.FileChooserNative(
            title="Choose a folder", transient_for=self.app.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            accept_label="Choose this folder", cancel_label="Cancel")
        dialog.connect("response", self._folder_response, entry)
        dialog.show()

    def _folder_response(self, dialog, response, entry):
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            path = selected.get_path() if selected else None
            if path:
                entry.set_text(path)
        dialog.destroy()

    def _choose_json(self):
        dialog = Gtk.FileChooserNative(
            title="Choose Google Desktop OAuth JSON", transient_for=self.app.window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Use this JSON", cancel_label="Cancel")
        current = self.json_entry.get_text().strip()
        if current and Path(current).expanduser().is_file():
            dialog.set_current_folder(str(Path(current).expanduser().parent))
        else:
            for folder in (Path.home() / "Downloads", Path.home()):
                if folder.is_dir():
                    dialog.set_current_folder(str(folder))
                    break
        file_filter = Gtk.FileFilter()
        file_filter.set_name("JSON files")
        file_filter.add_pattern("*.json")
        dialog.add_filter(file_filter)
        dialog.connect("response", self._json_response)
        dialog.show()

    def _json_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            path = selected.get_path() if selected else None
            if path:
                self.json_entry.set_text(path)
        dialog.destroy()

    def _find_json(self):
        paths = B.find_oauth_client_files()
        if not paths:
            self.app.window.toast(
                "No Google OAuth JSON found. Check Downloads/Desktop, or use "
                "Choose JSON… to browse.", "error")
            return
        if len(paths) == 1:
            self.json_entry.set_text(paths[0])
            self.app.window.toast("Found " + Path(paths[0]).name, "info")
            return
        dialog = Gtk.Dialog(title="Choose an OAuth JSON file",
                            transient_for=self.app.window, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Use this file", Gtk.ResponseType.ACCEPT)
        area = dialog.get_content_area()
        area.set_spacing(8)
        area.set_margin_top(12)
        area.set_margin_bottom(12)
        area.set_margin_start(12)
        area.set_margin_end(12)
        area.append(Gtk.Label(label="Found more than one client JSON:", xalign=0))
        model = Gtk.StringList.new([Path(p).name for p in paths])
        dropdown = Gtk.DropDown(model=model)
        dropdown.set_selected(0)
        area.append(dropdown)
        dialog.connect("response", self._find_json_response, dropdown, paths)
        dialog.present()

    def _find_json_response(self, dialog, response, dropdown, paths):
        if response == Gtk.ResponseType.ACCEPT:
            index = dropdown.get_selected()
            if 0 <= index < len(paths):
                self.json_entry.set_text(paths[index])
        dialog.destroy()

    def _test_smb(self, _button):
        host = self.smb_host.get_text().strip()
        share = self.smb_share.get_text().strip()
        user = self.smb_user.get_text().strip()
        domain = self.smb_domain.get_text().strip() or "WORKGROUP"
        if not all((host, share, user)):
            return self._error("Enter the SMB server, share, and username first.")
        password = self.smb_password.get_text()
        saved_unchanged = (
            not password and self.cfg.get("storage_mode") == "smb" and
            host == self.cfg.get("smb_host", "") and
            share.strip("/\\") == self.cfg.get("smb_share", "") and
            user == self.cfg.get("smb_user", "") and
            domain == self.cfg.get("smb_domain", "WORKGROUP"))
        if not password and self.cfg.get("storage_mode") == "smb" and not saved_unchanged:
            return self._error("Enter the SMB password to test changed connection details.")
        self.smb_test_btn.set_sensitive(False)
        self.smb_test_status.set_label("Connecting…")

        def work():
            try:
                if saved_unchanged:
                    message = B.test_saved_smb_connection(self.cfg)
                else:
                    message = B.test_smb_connection(
                        self.cfg.get("rclone_config"), host, share, user, password, domain)
                GLib.idle_add(self._smb_test_done, True, message)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._smb_test_done, False, str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _smb_test_done(self, ok, message):
        self.smb_test_btn.set_sensitive(True)
        self.smb_test_status.set_label(("✓ " if ok else "✗ ") + message)
        self.app.window.toast(message, "info" if ok else "error")
        return False

    def _open_exclusions(self, _button):
        settings = self.app.window._pages.get("settings")
        if settings is not None:
            settings.exclude_source_override = self.source_entry.get_text().strip()
        self.app.window.stack.set_visible_child_name("settings")
        self.app.window.toast(
            "Use Add files or Add folders. Return to Setup & schedule when finished.")

    def open_step(self, step):
        """Open a specific assistant section when linked from Settings."""
        self._set_step(step)

    # ------------------------------------------------------------ components
    def _install_components(self, _button):
        self.install_btn.set_sensitive(False)
        self.install_status.set_label("Waiting for administrator approval…")
        B.install_dependencies(lambda ok, message: GLib.idle_add(
            self._install_done, ok, message))

    def _install_done(self, ok, message):
        self.install_btn.set_sensitive(not ok)
        self.install_status.set_label(message)
        if ok:
            self.install_btn.set_label("✓ Components installed")
        self.app.window.toast(message, "info" if ok else "error")
        return False

    def _refresh_admin_status(self):
        granted = B.admin_rights_granted()
        self.admin_status.set_label(
            "✓ Permanent permission is active" if granted else
            "System-image backups will ask for your password each run")
        self.admin_btn.set_sensitive(not granted)
        self.admin_btn.set_label(
            "Grant permanent permission — one-time password" if not granted else
            "Permanent permission is active")
        return False

    def _grant_admin(self, _button):
        self.admin_btn.set_sensitive(False)
        self.admin_status.set_label("Waiting for one-time administrator approval…")
        B.grant_admin_rights(self.cfg, lambda ok, message: GLib.idle_add(
            self._admin_done, ok, message))

    def _admin_done(self, ok, message):
        granted = B.admin_rights_granted()
        self.admin_status.set_label(("✓ " if ok else "") + message)
        self.admin_btn.set_sensitive(not granted)
        self.admin_btn.set_label(
            "Grant permanent permission — one-time password" if not granted else
            "Permanent permission is active")
        self.app.window.toast(message, "info" if ok else "error")
        return False

    # ---------------------------------------------------------------- apply
    def _apply(self, _button):
        if not self._validate_all():
            return
        modes = ("oauth", "folder", "smb")
        mode = modes[self.mode.get_selected()]
        location = (self.folder_entry.get_text().strip() if mode == "folder" else
                    self._selected_remote() if mode == "oauth" else "")
        speeds = ("reliable", "balanced", "fast")
        selected_month = self.monthly_day.get_selected()
        monthly_day = "last" if selected_month == 28 else str(selected_month + 1)
        args = (
            self.cfg, mode, self.source_entry.get_text().strip(), location,
            self.daily_time.get_text(), self.DAYS[self.weekly_day.get_selected()],
            self.weekly_time.get_text(), speeds[self.speed.get_selected()],
            "private" if self.auth_mode.get_selected() == 1 else "shared",
            monthly_day, self.monthly_time.get_text(),
            self.DAYS[self.integrity_day.get_selected()], self.integrity_time.get_text(),
            self.daily_enabled.get_active(), self.weekly_enabled.get_active(),
            self.monthly_enabled.get_active(), self.integrity_enabled.get_active(),
            ("system_image" if self.monthly_image.get_active() else "restic"),
            self.system_disk.get_text().strip(),
            {"remote": self.cfg.get("smb_remote", "vaultleaf-smb"),
             "host": self.smb_host.get_text().strip(),
             "share": self.smb_share.get_text().strip(),
             "user": self.smb_user.get_text().strip(),
             "password": self.smb_password.get_text(),
             "domain": self.smb_domain.get_text().strip() or "WORKGROUP",
             "mount_dir": self.smb_mount.get_text().strip()})
        self.apply_btn.set_sensitive(False)
        self.back_btn.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.status.set_label("Creating secure storage, background services, and schedules…")

        def work():
            try:
                result = B.apply_setup(*args)
                GLib.idle_add(self._apply_done, result, None)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._apply_done, None, str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _validate_all(self):
        original = self.step
        for step in (1, 2):
            self.step = step
            if not self._validate_step():
                message = self.status.get_label()
                self._set_step(step)
                self.status.set_label(message)
                return False
        self.step = original
        return True

    def _apply_done(self, result, error):
        self.apply_btn.set_sensitive(True)
        self.back_btn.set_sensitive(True)
        self.spinner.stop()
        self.spinner.set_visible(False)
        if error:
            self.status.set_label(f"Setup could not finish: {error}")
            self.app.window.toast(f"Setup failed: {error}", "error")
            return False
        self.cfg.clear()
        self.cfg.update(result)
        settings = self.app.window._pages.get("settings")
        if settings is not None:
            settings.exclude_source_override = None
        self.cache.snapshots = {"daily": [], "weekly": [], "monthly": []}
        self.cache.about = None
        self.cache.timers = []
        self.cache._t = {"about": 0.0, "snap": 0.0, "timers": 0.0}
        self.apply_btn.set_label("Save changes")
        self.status.set_label("✓ Setup complete. Your backup plan is active.")
        self._update_review()
        self.app.window.toast("Setup complete — automatic backups are active.")
        self.app.window.refresh_all()
        return False

    def refresh(self):
        pass
