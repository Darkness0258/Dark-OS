#!/usr/bin/env python3
"""DarkOS Welcome: a short first-run tour, and the install entry on the live ISO.

Shown once after the first login (`--first-run` from Hyprland's exec-once) and
any time from the Apps overlay. Nothing here is a gate: every page can be
skipped, and a setting only changes when its button or choice is pressed.

Slow work (reading power profiles, restarting swaybg) runs on worker threads;
results come back through GLib.idle_add. The decisions live in
darkos_shell/welcome.py so they are testable without a display.
"""
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from darkos_shell import user_settings, wallpapers, welcome  # noqa: E402
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.Welcome"
WM_CLASS = "darkos-welcome"

TIPS = (
    ("Super + E", "Search apps and files"),
    ("Super + Q  or  Super + Enter", "Open the Void (terminal)"),
    ("Super + H", "Command center: notifications and quick toggles"),
    ("Super + Tab", "Overview of every window"),
    ("Ctrl + Shift + Esc", "Task Manager"),
)

DOCK_POSITIONS = (("bottom", "Bottom"), ("left", "Left"), ("right", "Right"), ("top", "Top"))
EFFECT_CHOICES = (
    ("auto", "Auto", "Picks Lite on virtual machines and older graphics"),
    ("lite", "Lite", "No blur or shadows: the smoothest option"),
    ("full", "Full", "Blur, shadows and animations"),
)

QUICK_LAUNCH = (
    ("Settings", "/usr/local/bin/darkos-settings.py"),
    ("Store", "/usr/local/bin/darkos-store.py"),
    ("Files", "/usr/local/bin/darkos-files.py"),
    ("Task Manager", "/usr/local/bin/darkos-taskmgr.py"),
)


class Services:
    """Everything the window does outside itself, so tests can substitute it."""

    def __init__(self):
        self.cfg = welcome.config_dir()
        self.live = welcome.is_live()

    def list_profiles(self):
        """Raw `powerprofilesctl list` output. Blocking: call off the main thread."""
        try:
            done = subprocess.run(["powerprofilesctl", "list"], capture_output=True, text=True, timeout=4)
            return done.stdout if done.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def set_profile(self, profile):
        try:
            return subprocess.run(["powerprofilesctl", "set", profile], capture_output=True,
                                  timeout=4).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def apply_wallpaper(self, path):
        return wallpapers.apply(path)

    def spawn(self, argv):
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
        except OSError:
            return False

    def load_settings(self):
        return user_settings.load_settings()

    def save_settings(self, data):
        return user_settings.save_settings(data)


def _label(text, css=None, wrap=True, xalign=0.0):
    label = Gtk.Label(label=text)
    label.set_xalign(xalign)
    label.set_line_wrap(wrap)
    if css:
        add_class(label, css)
    return label


def _page_box():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    box.set_border_width(28)
    return box


class WelcomeWindow(Gtk.ApplicationWindow):
    def __init__(self, app, services=None):
        super().__init__(application=app, title="Welcome to DarkOS")
        add_class(self, "app-window")
        self.svc = services or Services()
        self.live = self.svc.live
        self.pages = self._visible_pages()
        self.index = 0
        self._closing = False
        self.set_default_size(780, 580)
        self.set_position(Gtk.WindowPosition.CENTER)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)  # no animation to budget
        root.pack_start(self.stack, True, True, 0)

        builders = {
            "welcome": self._page_welcome, "look": self._page_look, "power": self._page_power,
            "tools": self._page_tools, "finish": self._page_finish,
        }
        for name in self.pages:
            self.stack.add_named(builders[name](), name)

        footer = Gtk.Box(spacing=8)
        footer.set_border_width(14)
        add_class(footer, "toolbar")
        self.footer = footer
        if len(self.pages) > 1:          # the live page is one page: no empty navigation bar
            root.pack_end(footer, False, False, 0)
        self.progress = _label("", "caption", wrap=False)
        footer.pack_start(self.progress, False, False, 0)
        self.skip_btn = Gtk.Button(label="Skip tour")
        add_class(self.skip_btn, "action-button")
        self.skip_btn.connect("clicked", lambda *_: self.finish())
        self.next_btn = Gtk.Button(label="Next")
        add_class(self.next_btn, "action-button")
        add_class(self.next_btn, "primary")
        self.next_btn.connect("clicked", lambda *_: self.go(1))
        self.back_btn = Gtk.Button(label="Back")
        add_class(self.back_btn, "action-button")
        self.back_btn.connect("clicked", lambda *_: self.go(-1))
        for button in (self.next_btn, self.back_btn, self.skip_btn):
            # run_app() calls show_all() after build_window(); without this it would
            # re-show the buttons _sync() hides (the live page has no navigation).
            button.set_no_show_all(True)
            footer.pack_end(button, False, False, 0)
        self.next_btn.set_can_default(True)
        self.set_default(self.next_btn)
        self.connect("destroy", self._on_destroy)
        # Focus the button Enter/Space should press. Without this the first
        # focusable widget wins, and that is "Skip tour".
        self.connect("map", lambda *_: self._focus_primary())
        self._sync()

    # -- navigation ---------------------------------------------------------
    def _visible_pages(self):
        pages = list(welcome.pages_for(self.live))
        if not self.live:
            # Someone who already answered the old first-boot prompts is not asked twice.
            if not welcome.performance_pending(self.svc.cfg):
                pages.remove("power")
            if not welcome.tools_pending(self.svc.cfg):
                pages.remove("tools")
        return pages

    def _focus_primary(self):
        target = getattr(self, "install_btn", None) if self.live else self.next_btn
        if target is not None:
            target.grab_focus()

    def current(self):
        return self.pages[self.index]

    def go(self, delta):
        if delta > 0 and self.index == len(self.pages) - 1:
            self.finish()
            return
        self.index = max(0, min(len(self.pages) - 1, self.index + delta))
        self._sync()

    def _sync(self):
        self.stack.set_visible_child_name(self.current())
        last = self.index == len(self.pages) - 1
        single = len(self.pages) == 1
        self.back_btn.set_sensitive(self.index > 0)
        self.back_btn.set_visible(not single)
        self.skip_btn.set_visible(not last and not single)
        self.next_btn.set_visible(not self.live or not single)
        self.next_btn.set_label("Done" if last else "Next")
        self.progress.set_text("" if single else f"{self.index + 1} of {len(self.pages)}")

    def finish(self):
        """Close the tour; it will not open by itself again (live: it always will)."""
        if not self.live:
            welcome.write_marker(welcome.DONE_NAME, self.svc.cfg)
        self._closing = True
        self.destroy()

    def _on_destroy(self, *_):
        # Dismissing the window (X, Esc from the shell) also counts: a tour
        # that comes back every login is a nag, and it stays in the Apps overlay.
        if not self._closing and not self.live:
            welcome.write_marker(welcome.DONE_NAME, self.svc.cfg)

    # -- pages --------------------------------------------------------------
    def _page_welcome(self):
        box = _page_box()
        box.pack_start(_label("Welcome to DarkOS", "title"), False, False, 0)
        build = welcome.build_id()
        if self.live:
            box.pack_start(_label(
                "You are running DarkOS from the live USB. Nothing you do here is saved, "
                "so you can look around freely.", "lead"), False, False, 0)
            row = Gtk.Box(spacing=10)
            install = Gtk.Button(label="Install DarkOS")
            add_class(install, "action-button")
            add_class(install, "primary")
            install.connect("clicked", self._on_install)
            keep = Gtk.Button(label="Keep trying it")
            add_class(keep, "action-button")
            keep.connect("clicked", lambda *_: self.finish())
            row.pack_start(install, False, False, 0)
            row.pack_start(keep, False, False, 0)
            box.pack_start(row, False, False, 6)
            self.install_btn = install
        else:
            box.pack_start(_label(
                "A quick tour: pick a look, choose how it uses power, and decide about the "
                "optional security tools. Everything is optional, and you can reopen this "
                "any time from the Apps overlay.", "lead"), False, False, 0)
        box.pack_start(_label("Handy shortcuts", "section-title"), False, False, 8)
        grid = Gtk.Grid(column_spacing=18, row_spacing=6)
        for row, (keys, what) in enumerate(TIPS):
            grid.attach(_label(keys, "eyebrow", wrap=False), 0, row, 1, 1)
            grid.attach(_label(what, "body-muted"), 1, row, 1, 1)
        box.pack_start(grid, False, False, 0)
        if build:
            box.pack_end(_label(f"Build {build}", "caption"), False, False, 0)
        return box

    def _page_look(self):
        box = _page_box()
        box.pack_start(_label("Make it yours", "title"), False, False, 0)
        settings = self.svc.load_settings()

        box.pack_start(_label("Wallpaper", "section-title"), False, False, 0)
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(5)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.wallpaper_buttons = {}
        group = None
        for entry in wallpapers.catalog():
            button = Gtk.RadioButton.new_from_widget(group) if group else Gtk.RadioButton()
            group = group or button
            button.set_mode(False)  # looks like a tile, behaves like a radio
            add_class(button, "toggle-button")
            button.set_tooltip_text(entry["name"])
            button.get_accessible().set_name(entry["name"])
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(entry["thumb"], 118, 66, True)
                button.add(Gtk.Image.new_from_pixbuf(pixbuf))
            except GLib.Error:
                button.add(_label(entry["name"], wrap=False))
            button.connect("toggled", self._on_wallpaper, entry["path"])
            flow.add(button)
            self.wallpaper_buttons[entry["path"]] = button
        chosen = wallpapers.resolve(settings.get("wallpaper_path", "")) or wallpapers.default_path()
        if chosen in self.wallpaper_buttons:
            self.wallpaper_buttons[chosen].set_active(True)
        self._wallpaper_ready = True
        box.pack_start(flow, False, False, 0)

        box.pack_start(_label("Effects", "section-title"), False, False, 6)
        self.effect_buttons = self._radio_row(
            box, [(value, label, hint) for value, label, hint in EFFECT_CHOICES],
            settings.get("effects", "auto"), "effects")
        box.pack_start(_label("Effects apply the next time you log in.", "caption"), False, False, 0)

        box.pack_start(_label("Dock position", "section-title"), False, False, 6)
        self.dock_buttons = self._radio_row(
            box, [(value, label, "") for value, label in DOCK_POSITIONS],
            settings.get("dock_position", "bottom"), "dock_position")
        return box

    def _radio_row(self, box, choices, current, key):
        row = Gtk.Box(spacing=14)
        buttons = {}
        group = None
        for value, label, hint in choices:
            button = Gtk.RadioButton.new_with_label_from_widget(group, label) if group \
                else Gtk.RadioButton.new_with_label(None, label)
            group = group or button
            if hint:
                button.set_tooltip_text(hint)
            button.set_active(value == current)
            button.connect("toggled", self._on_setting_choice, key, value)
            row.pack_start(button, False, False, 0)
            buttons[value] = button
        box.pack_start(row, False, False, 0)
        return buttons

    def _on_setting_choice(self, button, key, value):
        if not button.get_active():
            return
        data = self.svc.load_settings()
        if data.get(key) == value:
            return
        data[key] = value
        self.svc.save_settings(data)

    def _on_wallpaper(self, button, path):
        if not button.get_active() or not getattr(self, "_wallpaper_ready", False):
            return
        data = self.svc.load_settings()
        data["wallpaper_path"] = path
        self.svc.save_settings(data)
        threading.Thread(target=self.svc.apply_wallpaper, args=(path,), daemon=True).start()

    def _page_power(self):
        box = _page_box()
        box.pack_start(_label("Power", "title"), False, False, 0)
        box.pack_start(_label(
            "Pick a profile. You can change it later in Settings, and lock and sleep "
            "timings are there too.", "lead"), False, False, 0)
        self.profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.profile_status = _label("Checking what this computer offers...", "body-muted")
        box.pack_start(self.profile_status, False, False, 0)
        box.pack_start(self.profile_box, False, False, 0)
        self.profile_buttons = {}
        threading.Thread(target=self._load_profiles, daemon=True).start()
        return box

    def _load_profiles(self):
        output = self.svc.list_profiles()
        GLib.idle_add(self._show_profiles, output)

    def _show_profiles(self, output):
        offered = welcome.parse_profiles(output)
        if not offered:
            self.profile_status.set_text(
                "This computer does not offer power profiles, so there is nothing to choose.")
            return False
        self.profile_status.set_text("Choose a profile:")
        active = welcome.active_profile(output)
        group = None
        for pid, label in offered:
            button = Gtk.RadioButton.new_with_label_from_widget(group, label) if group \
                else Gtk.RadioButton.new_with_label(None, label)
            group = group or button
            button.set_active(pid == active)
            button.connect("toggled", self._on_profile, pid)
            self.profile_box.pack_start(button, False, False, 0)
            self.profile_buttons[pid] = button
        self.profile_box.show_all()
        self._profiles_ready = True
        return False

    def _on_profile(self, button, pid):
        if not button.get_active() or not getattr(self, "_profiles_ready", False):
            return

        def work():
            ok = self.svc.set_profile(pid)
            if ok:
                welcome.write_marker(welcome.PERFORMANCE_DONE, self.svc.cfg)
            GLib.idle_add(self.profile_status.set_text,
                          "Profile set." if ok else "Could not change the profile.")

        threading.Thread(target=work, daemon=True).start()

    def _page_tools(self):
        box = _page_box()
        box.pack_start(_label("Security tools", "title"), False, False, 0)
        box.pack_start(_label(
            "DarkOS does not install penetration-testing tools by default. If you want some, "
            "BlackArch tools come in groups you pick, and each group asks for your password "
            "once before it installs. You can also add them later from the Store.", "lead"),
            False, False, 0)
        row = Gtk.Box(spacing=10)
        choose = Gtk.Button(label="Choose tool groups...")
        add_class(choose, "action-button")
        choose.connect("clicked", self._on_choose_tools)
        decline = Gtk.Button(label="Don't ask again")
        add_class(decline, "action-button")
        decline.connect("clicked", self._on_decline_tools)
        row.pack_start(choose, False, False, 0)
        row.pack_start(decline, False, False, 0)
        box.pack_start(row, False, False, 6)
        self.tools_status = _label("Choosing nothing here changes nothing: use Next to carry on.",
                                   "body-muted")
        box.pack_start(self.tools_status, False, False, 0)
        self.choose_tools_btn = choose
        self.decline_tools_btn = decline
        return box

    def _on_choose_tools(self, _button):
        ok = self.svc.spawn(welcome.tools_argv(cfg=self.svc.cfg))
        self.tools_status.set_text(
            "The picker is open in the Void. Come back here when it finishes." if ok
            else "Could not open the picker. You can try again from the Store.")

    def _on_decline_tools(self, _button):
        welcome.write_marker(welcome.TOOLS_DECLINED, self.svc.cfg)
        self.tools_status.set_text("Okay, DarkOS will not ask about this again.")

    def _page_finish(self):
        box = _page_box()
        box.pack_start(_label("You're set", "title"), False, False, 0)
        box.pack_start(_label(
            "That is everything. These are one click away if you want a look around.", "lead"),
            False, False, 0)
        row = Gtk.Box(spacing=10)
        self.launch_buttons = {}
        for name, path in QUICK_LAUNCH:
            button = Gtk.Button(label=name)
            add_class(button, "action-button")
            button.connect("clicked", lambda _b, p=path: self.svc.spawn(["python", p]))
            row.pack_start(button, False, False, 0)
            self.launch_buttons[name] = button
        box.pack_start(row, False, False, 6)
        return box

    def _on_install(self, _button):
        if self.svc.spawn([welcome.INSTALLER_BIN]):
            self.finish()


def build_window(app):
    return WelcomeWindow(app)


def main(argv):
    first_run = "--first-run" in argv
    if not welcome.should_show(first_run, welcome.is_live(), welcome.is_done()):
        return 0
    run_app(APP_ID, WM_CLASS, build_window)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
