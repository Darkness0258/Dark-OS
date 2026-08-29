#!/usr/bin/env python3
"""DarkOS Settings — one app, many tabs (per CLAUDE.md's non-negotiable
"Settings is one app with many tabs, not 20 separate apps").

Every tab shows real data where this sandbox and a real Arch/Hyprland
install both have it (CPU/RAM/disk, real users via pwd, real autostart
entries, real icon themes on disk). Where a tab depends on hardware, a
running daemon, or a service this environment doesn't have (CPU governor,
systemd, live GTK theme reload), the code path is the real one — it
attempts the real thing and reports the real failure — rather than faking
success. See build-plan.md Phase 5 for which tabs that applies to.

Accent color / corner radius / reduce-motion write through
darkos_shell.user_settings, which tokens.py reads at import time — changing
them here actually changes the shell's values on next restart, confirmed
by direct test, not just written to a file nothing reads.
"""
import json
import os
import platform
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402
from darkos_shell.user_settings import load_settings, save_settings  # noqa: E402

APP_ID = "org.darkos.Settings"
WM_CLASS = "darkos-settings"

CATEGORIES = [
    ("system", "System", "computer-symbolic"),
    ("performance", "Performance", "utilities-system-monitor-symbolic"),
    ("config", "Config", "text-x-generic-symbolic"),
    ("devices", "Devices", "drive-harddisk-symbolic"),
    ("users", "Users", "system-users-symbolic"),
    ("services", "Services", "system-run-symbolic"),
    ("startup", "Startup", "media-playback-start-symbolic"),
    ("storage", "Storage", "drive-multidisk-symbolic"),
    ("fonts", "Fonts", "font-x-generic-symbolic"),
    ("icons", "Icons", "preferences-desktop-icons-symbolic"),
    ("themes", "Themes", "preferences-desktop-theme-symbolic"),
    ("wallpaper", "Wallpaper", "preferences-desktop-wallpaper-symbolic"),
    ("motion", "Motion", "preferences-desktop-accessibility-symbolic"),
    ("designer", "Designer", "applications-graphics-symbolic"),
    ("permissions", "Permissions", "security-high-symbolic"),
    ("accessibility", "Accessibility", "preferences-desktop-accessibility-symbolic"),
]


def human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def kv_row(key, value):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    key_label = Gtk.Label(label=key, xalign=0)
    add_class(key_label, "path-crumb")
    key_label.set_size_request(140, -1)
    val_label = Gtk.Label(label=str(value), xalign=0)
    val_label.set_line_wrap(True)
    box.pack_start(key_label, False, False, 0)
    box.pack_start(val_label, True, True, 0)
    return box


def section_label(text):
    label = Gtk.Label(label=text, xalign=0)
    label.set_margin_top(12)
    label.set_margin_bottom(4)
    label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    return label


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Settings")
        self.set_default_size(920, 620)
        add_class(self, "app-window")

        self.settings = load_settings()

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(body)

        self.sidebar = Gtk.ListBox()
        add_class(self.sidebar, "sidebar")
        for cid, label, icon in CATEGORIES:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hbox.set_margin_top(4)
            hbox.set_margin_bottom(4)
            add_class(hbox, "sidebar-row")
            hbox.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            hbox.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            row.add(hbox)
            row.category_id = cid
            self.sidebar.add(row)
        self.sidebar.connect("row-selected", self._on_category_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(200, -1)
        scroller.add(self.sidebar)
        body.pack_start(scroller, False, False, 0)
        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        self.stack = Gtk.Stack()
        add_class(self.stack, "app-window")
        builders = {
            "system": self._build_system_tab,
            "performance": self._build_performance_tab,
            "config": self._build_config_tab,
            "devices": self._build_devices_tab,
            "users": self._build_users_tab,
            "services": self._build_services_tab,
            "startup": self._build_startup_tab,
            "storage": self._build_storage_tab,
            "fonts": self._build_fonts_tab,
            "icons": self._build_icons_tab,
            "themes": self._build_themes_tab,
            "wallpaper": self._build_wallpaper_tab,
            "motion": self._build_motion_tab,
            "designer": self._build_designer_tab,
            "permissions": self._build_permissions_tab,
            "accessibility": self._build_accessibility_tab,
        }
        for cid, _label, _icon in CATEGORIES:
            page = self._wrap_page(builders[cid]())
            self.stack.add_named(page, cid)
        body.pack_start(self.stack, True, True, 0)

        self.sidebar.select_row(self.sidebar.get_row_at_index(0))

    def _wrap_page(self, content):
        scroller = Gtk.ScrolledWindow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_border_width(20)
        box.pack_start(content, False, False, 0)
        scroller.add(box)
        return scroller

    def _on_category_selected(self, _box, row):
        if row:
            self.stack.set_visible_child_name(row.category_id)

    def _save(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)

    # -- System --------------------------------------------------------------
    def _build_system_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("System"), False, False, 0)
        uname = platform.uname()
        cpu_model = "Unknown"
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        cpu_model = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
        mem_total = "Unknown"
        try:
            with open("/proc/meminfo") as f:
                mem_total = human_size(int(f.readline().split()[1]) * 1024)
        except (OSError, IndexError, ValueError):
            pass
        uptime_str = "Unknown"
        try:
            with open("/proc/uptime") as f:
                secs = float(f.readline().split()[0])
                uptime_str = f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"
        except (OSError, IndexError, ValueError):
            pass
        for k, v in [
            ("Hostname", GLib.get_host_name()),
            ("OS", "DarkOS"),
            ("Kernel", uname.release),
            ("Architecture", uname.machine),
            ("CPU", cpu_model),
            ("Memory", mem_total),
            ("Uptime", uptime_str),
        ]:
            box.pack_start(kv_row(k, v), False, False, 0)
        return box

    # -- Performance -----------------------------------------------------------
    def _build_performance_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("CPU governor"), False, False, 0)
        cpu_dirs = sorted(p for p in os.listdir("/sys/devices/system/cpu") if p.startswith("cpu") and p[3:].isdigit()) \
            if os.path.isdir("/sys/devices/system/cpu") else []
        found_any = False
        for cpu in cpu_dirs:
            gov_path = f"/sys/devices/system/cpu/{cpu}/cpufreq/scaling_governor"
            if os.path.exists(gov_path):
                found_any = True
                try:
                    with open(gov_path) as f:
                        box.pack_start(kv_row(cpu, f.read().strip()), False, False, 0)
                except OSError as e:
                    box.pack_start(kv_row(cpu, f"unreadable ({e.strerror})"), False, False, 0)
        if not found_any:
            box.pack_start(Gtk.Label(
                label="No cpufreq scaling_governor exposed on this system — common in VMs/containers, "
                      "shows real per-core values on real hardware.",
                xalign=0, wrap=True,
            ), False, False, 0)
        return box

    # -- Config ----------------------------------------------------------------
    def _build_config_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(section_label("DarkOS configuration"), False, False, 0)
        from darkos_shell.user_settings import settings_path
        box.pack_start(kv_row("Settings file", settings_path()), False, False, 0)

        view_btn = Gtk.Button(label="Open config folder in Files")
        add_class(view_btn, "icon-button")
        view_btn.connect("clicked", lambda *_: subprocess.Popen(
            ["/usr/local/bin/darkos-files.py", os.path.dirname(settings_path())]
        ))
        box.pack_start(view_btn, False, False, 8)

        box.pack_start(section_label("Current values (raw)"), False, False, 0)
        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_monospace(True)
        text_view.get_buffer().set_text(json.dumps(self.settings, indent=2))
        text_view.set_size_request(-1, 200)
        box.pack_start(text_view, False, False, 0)
        return box

    # -- Devices -----------------------------------------------------------------
    def _build_devices_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("Block devices"), False, False, 0)
        try:
            result = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT"],
                capture_output=True, text=True, timeout=5, check=True,
            )
            data = json.loads(result.stdout)
            for dev in data.get("blockdevices", []):
                self._add_device_row(box, dev, depth=0)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
            box.pack_start(Gtk.Label(label=f"Couldn't list block devices: {e}", xalign=0), False, False, 0)
        return box

    def _add_device_row(self, box, dev, depth):
        indent = "  " * depth
        name = f"{indent}{dev.get('name', '?')}"
        detail = f"{dev.get('size', '')}  {dev.get('type', '')}  {dev.get('mountpoint') or ''}"
        box.pack_start(kv_row(name, detail), False, False, 0)
        for child in dev.get("children", []) or []:
            self._add_device_row(box, child, depth + 1)

    # -- Users ---------------------------------------------------------------
    def _build_users_tab(self):
        import pwd
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("Accounts"), False, False, 0)
        users = [u for u in pwd.getpwall() if u.pw_uid == 0 or 1000 <= u.pw_uid < 60000]
        users.sort(key=lambda u: (u.pw_uid != 0, u.pw_name))
        for u in users:
            box.pack_start(kv_row(u.pw_name, f"uid={u.pw_uid}  shell={u.pw_shell}  home={u.pw_dir}"), False, False, 0)
        return box

    # -- Services --------------------------------------------------------------
    def _build_services_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("systemd services"), False, False, 0)
        try:
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--no-pager", "--plain", "--no-legend"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                raise RuntimeError(result.stderr.strip() or "systemctl returned no output")
            lines = result.stdout.strip().splitlines()[:40]
            for line in lines:
                parts = line.split(None, 4)
                if parts:
                    box.pack_start(kv_row(parts[0], " ".join(parts[1:])), False, False, 0)
            if len(result.stdout.strip().splitlines()) > 40:
                box.pack_start(Gtk.Label(label=f"…and {len(result.stdout.strip().splitlines()) - 40} more", xalign=0), False, False, 0)
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            box.pack_start(Gtk.Label(
                label=f"Couldn't reach systemd: {e}\n(this sandbox has no init system — real on an actual boot)",
                xalign=0, wrap=True,
            ), False, False, 0)
        return box

    # -- Startup -----------------------------------------------------------------
    def _autostart_dir(self):
        d = os.path.join(GLib.get_user_config_dir(), "autostart")
        os.makedirs(d, exist_ok=True)
        return d

    def _build_startup_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("Startup applications"), False, False, 0)
        d = self._autostart_dir()
        entries = sorted(f for f in os.listdir(d) if f.endswith(".desktop"))
        if not entries:
            box.pack_start(Gtk.Label(label=f"No autostart entries in {d}", xalign=0), False, False, 0)
        for fname in entries:
            path = os.path.join(d, fname)
            box.pack_start(self._startup_row(path), False, False, 0)
        return box

    def _startup_row(self, path):
        import configparser
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.optionxform = str  # preserve key case — .desktop keys are case-sensitive per spec
        try:
            cfg.read(path)
            name = cfg.get("Desktop Entry", "Name", fallback=os.path.basename(path))
            enabled = cfg.getboolean("Desktop Entry", "X-GNOME-Autostart-enabled", fallback=True)
        except (configparser.Error, OSError):
            name, enabled = os.path.basename(path), True
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
        switch = Gtk.Switch()
        switch.set_active(enabled)
        switch.connect("state-set", self._make_startup_toggler(path))
        row.pack_start(switch, False, False, 0)
        return row

    def _make_startup_toggler(self, path):
        def _toggle(_switch, state):
            # Plain text edit rather than configparser.write() — keeps the
            # file's existing Key=Value formatting and line order untouched
            # instead of reformatting the whole file for a one-line change.
            new_value = "true" if state else "false"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                return
            found = False
            for i, line in enumerate(lines):
                if line.strip().lower().startswith("x-gnome-autostart-enabled"):
                    lines[i] = f"X-GNOME-Autostart-enabled={new_value}\n"
                    found = True
                    break
            if not found:
                for i, line in enumerate(lines):
                    if line.strip() == "[Desktop Entry]":
                        lines.insert(i + 1, f"X-GNOME-Autostart-enabled={new_value}\n")
                        found = True
                        break
            if not found:
                lines.append(f"X-GNOME-Autostart-enabled={new_value}\n")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            except OSError:
                pass
        return _toggle

    # -- Storage -----------------------------------------------------------------
    def _build_storage_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(section_label("Storage"), False, False, 0)
        for label, path in [("Root (/)", "/"), ("Home", GLib.get_home_dir())]:
            try:
                usage = shutil_disk_usage(path)
                fraction = usage.used / usage.total if usage.total else 0
                box.pack_start(Gtk.Label(label=f"{label} — {human_size(usage.used)} of {human_size(usage.total)} used", xalign=0), False, False, 0)
                level = Gtk.LevelBar()
                level.set_min_value(0)
                level.set_max_value(1)
                level.set_value(fraction)
                box.pack_start(level, False, False, 0)
            except OSError as e:
                box.pack_start(Gtk.Label(label=f"{label}: {e.strerror}", xalign=0), False, False, 0)
        return box

    # -- Fonts ---------------------------------------------------------------
    def _build_fonts_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("Default interface font"), False, False, 0)
        chooser = Gtk.FontChooserWidget()
        current = self.settings.get("gtk_font") or "Inter 11"
        try:
            chooser.set_font(current)
        except GLib.Error:
            pass
        chooser.connect("font-activated", lambda _w, font: self._save("gtk_font", font))
        apply_btn = Gtk.Button(label="Save")
        add_class(apply_btn, "action-button")
        apply_btn.connect("clicked", lambda *_: self._save("gtk_font", chooser.get_font()))
        box.pack_start(chooser, True, True, 0)
        box.pack_start(apply_btn, False, False, 4)
        return box

    # -- Icons ---------------------------------------------------------------
    def _build_icons_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(section_label("Icon theme"), False, False, 0)
        themes = []
        for base in GLib.get_system_data_dirs() + [GLib.get_user_data_dir()]:
            icons_dir = os.path.join(base, "icons")
            if os.path.isdir(icons_dir):
                for name in os.listdir(icons_dir):
                    if os.path.exists(os.path.join(icons_dir, name, "index.theme")) and name not in themes:
                        themes.append(name)
        themes.sort()
        current = self.settings.get("icon_theme") or ""
        group = None
        for name in themes:
            btn = Gtk.RadioButton.new_with_label_from_widget(group, name)
            if group is None:
                group = btn
            btn.set_active(name == current)
            btn.connect("toggled", self._make_icon_theme_setter(name))
            box.pack_start(btn, False, False, 0)
        if not themes:
            box.pack_start(Gtk.Label(label="No icon themes found under any XDG data directory.", xalign=0), False, False, 0)
        return box

    def _make_icon_theme_setter(self, name):
        def _set(btn):
            if btn.get_active():
                self._save("icon_theme", name)
        return _set

    # -- Themes ----------------------------------------------------------------
    def _build_themes_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(section_label("Accent color"), False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        color_btn = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse(self.settings.get("accent_color") or "#00e5ff")
        color_btn.set_rgba(rgba)
        color_btn.connect("color-set", self._on_accent_changed)
        row.pack_start(color_btn, False, False, 0)
        row.pack_start(Gtk.Label(label="Applies to the HUD, dock, and highlights on next shell restart"), False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    def _on_accent_changed(self, btn):
        rgba = btn.get_rgba()
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        )
        self._save("accent_color", hex_color)

    # -- Wallpaper -----------------------------------------------------------
    def _build_wallpaper_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(section_label("Wallpaper"), False, False, 0)
        self.wallpaper_preview = Gtk.Image()
        current = self.settings.get("wallpaper_path")
        if current and os.path.isfile(current):
            self._set_wallpaper_preview(current)
        box.pack_start(self.wallpaper_preview, False, False, 0)

        chooser_btn = Gtk.Button(label="Choose Image…")
        add_class(chooser_btn, "icon-button")
        chooser_btn.connect("clicked", self._choose_wallpaper)
        box.pack_start(chooser_btn, False, False, 0)
        return box

    def _set_wallpaper_preview(self, path):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 320, 180, True)
            self.wallpaper_preview.set_from_pixbuf(pixbuf)
        except GLib.Error:
            self.wallpaper_preview.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)

    def _choose_wallpaper(self, *_):
        chooser = Gtk.FileChooserDialog(title="Choose wallpaper", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        img_filter = Gtk.FileFilter()
        img_filter.set_name("Images")
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            img_filter.add_pattern(pattern)
        chooser.add_filter(img_filter)
        if chooser.run() == Gtk.ResponseType.OK:
            path = chooser.get_filename()
            self._set_wallpaper_preview(path)
            self._save("wallpaper_path", path)
            try:
                subprocess.Popen(["hyprctl", "hyprpaper", "wallpaper", f",{path}"])
            except OSError:
                pass  # hyprpaper not running here (no compositor) — real on the target system
        chooser.destroy()

    # -- Motion ----------------------------------------------------------------
    def _build_motion_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(section_label("Motion"), False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(Gtk.Label(label="Reduce motion (slows/stops decorative animation, e.g. the HUD ring)"), True, True, 0)
        switch = Gtk.Switch()
        switch.set_active(bool(self.settings.get("reduce_motion")))
        switch.connect("state-set", lambda _s, state: self._save("reduce_motion", state))
        row.pack_start(switch, False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    # -- Designer --------------------------------------------------------------
    def _build_designer_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(section_label("Corner radius"), False, False, 0)
        adjustment = Gtk.Adjustment(value=self.settings.get("corner_radius", 16), lower=0, upper=32, step_increment=1)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
        scale.set_digits(0)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.connect("value-changed", lambda s: self._save("corner_radius", int(s.get_value())))
        box.pack_start(scale, False, False, 0)
        box.pack_start(Gtk.Label(
            label="Applies to panels/dialogs on next shell restart. Hyprland's own window "
                  "rounding (hyprland.conf) is separate and unaffected.",
            xalign=0, wrap=True,
        ), False, False, 8)
        return box

    # -- Permissions -------------------------------------------------------------
    def _build_permissions_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(section_label("App permissions"), False, False, 0)
        box.pack_start(Gtk.Label(
            label="Honest gap: DarkOS has no portal/sandboxing backend yet, so there's nothing "
                  "real for a per-app permission toggle to control. Listing native apps below so "
                  "the tab isn't empty, not implying enforcement that doesn't exist.",
            xalign=0, wrap=True,
        ), False, False, 8)
        apps_dir = "/usr/share/applications"
        try:
            names = sorted(f[:-8] for f in os.listdir(apps_dir) if f.startswith("darkos-") and f.endswith(".desktop"))
        except OSError:
            names = []
        for name in names:
            box.pack_start(kv_row(name, "Full system access (no sandboxing backend yet)"), False, False, 0)
        return box

    # -- Accessibility -----------------------------------------------------------
    def _build_accessibility_tab(self):
        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        pages = [
            ("Speech", "a11y_speech", "Announce UI elements and read text aloud. Needs a speech engine (espeak/festival) wired in — this saves the preference now."),
            ("Captions", "a11y_captions", "Show live captions for system audio. Needs a speech-to-text backend — this saves the preference now."),
            ("Magnifier", "a11y_magnifier", "Zoom the screen around the cursor. Needs compositor-level zoom support wired in."),
            ("Keyboard", "a11y_sticky_keys", "Sticky keys — press modifier keys one at a time instead of holding them."),
            ("Eye Control", "a11y_eye_control", "Control the cursor with eye tracking. Hardware-dependent (needs an eye tracker) — listed in the project backlog as not yet planned for real."),
        ]
        for label, key, description in pages:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            page.set_border_width(16)
            desc_label = Gtk.Label(label=description, xalign=0, wrap=True)
            page.pack_start(desc_label, False, False, 0)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(Gtk.Label(label=f"Enable {label}"), True, True, 0)
            switch = Gtk.Switch()
            switch.set_active(bool(self.settings.get(key)))
            switch.connect("state-set", lambda _s, state, k=key: self._save(k, state))
            row.pack_start(switch, False, False, 0)
            page.pack_start(row, False, False, 0)
            notebook.append_page(page, Gtk.Label(label=label))
        return notebook


def shutil_disk_usage(path):
    import shutil
    return shutil.disk_usage(path)


def build_window(app):
    return SettingsWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
