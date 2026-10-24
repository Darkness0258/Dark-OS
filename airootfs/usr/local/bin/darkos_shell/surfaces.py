"""Layer-shell surfaces: the dock and the Command Center.

Calm Dark layout (docs/MASTER-PLAN.md section 5): one dock, one slim status
bar (Waybar), and a single Command Center panel that only exists while it is
open. No rail, no second clock, no placeholder panels, no ring gauges.
"""
import json
import subprocess
import threading

import gi

gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango

from darkos_shell.canvases import ResourceRow
from darkos_shell.system_sampler import SystemSampler
from darkos_shell.tokens import (
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    dock_exclusive_zone,
    dock_layout,
)
from darkos_shell.user_settings import load_settings

# Same launcher Super+E opens (darkos-window-fx.py --search): apps, files,
# settings and actions in one overlay.
LAUNCHER_COMMAND = ["python3", "/usr/local/bin/darkos-window-fx.py", "--search"]

# (key, icon, name, command, wm_class). wm_class matches each app's own
# WM_CLASS (and the hyprland.conf windowrule matchers) so the running dot
# under an icon is driven by real `hyprctl clients -j` data.
DOCK_APPS = (
    ("files", "folder-symbolic", "Files", ["/usr/local/bin/darkos-files.py"], "darkos-files"),
    ("terminal", "utilities-terminal-symbolic", "Terminal", ["/usr/local/bin/the-void.sh"], "darkos-terminal"),
    ("browser", "web-browser-symbolic", "Browser", ["firefox"], "firefox"),
    ("notes", "accessories-text-editor-symbolic", "Notes", ["/usr/local/bin/darkos-notes.py"], "darkos-notes"),
    ("store", "system-software-install-symbolic", "Store", ["/usr/local/bin/darkos-store.py"], "darkos-store"),
    ("settings", "preferences-system-symbolic", "Settings", ["/usr/local/bin/darkos-settings.py"], "darkos-settings"),
)


def _running_window_classes():
    """Best-effort set of lowercased window classes currently open, via
    `hyprctl clients -j`. Used only for the dock's running-app dots --
    never lets a parse/exec failure propagate, since a cosmetic indicator
    is never worth crashing the shell over."""
    try:
        output = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        clients = json.loads(output)
        return {
            (client.get("class") or client.get("initialClass") or "").lower()
            for client in clients
        }
    except Exception:
        return set()


def add_class(widget, class_name):
    widget.get_style_context().add_class(class_name)
    return widget


def reveal(widget):
    """show_all() that works on a widget marked no_show_all. GTK ignores
    show_all() on those on purpose (so a parent's show_all() leaves them
    hidden), which also means they can never be shown by calling it."""
    widget.set_no_show_all(False)
    widget.show_all()
    widget.set_no_show_all(True)


def make_label(text, class_name=None, align=Gtk.Align.START, wrap=False):
    widget = Gtk.Label(label=text)
    widget.set_halign(align)
    widget.set_xalign(0.0 if align == Gtk.Align.START else 0.5)
    widget.set_line_wrap(wrap)
    if wrap:
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if class_name:
        add_class(widget, class_name)
    return widget


def make_icon_button(icon_name, name, callback, class_name="icon-button", size=40):
    button = Gtk.Button()
    image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
    image.set_pixel_size(size // 2)
    button.add(image)
    add_class(button, class_name)
    button.set_tooltip_text(name)
    button.set_size_request(size, size)
    button.get_accessible().set_name(name)
    button.connect("clicked", callback)
    return button


def make_icon_label(icon_name, text, icon_size=16):
    """Build a labelled control face from the active GTK symbolic icon theme."""
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_XS)
    content.set_halign(Gtk.Align.CENTER)
    image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    image.set_pixel_size(icon_size)
    content.pack_start(image, False, False, 0)
    content.pack_start(Gtk.Label(label=text), False, False, 0)
    return content


def configure_layer_window(
    window,
    namespace,
    layer,
    anchors,
    margins=None,
    exclusive_zone=0,
    keyboard=False,
):
    if not GtkLayerShell:
        return
    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_namespace(window, namespace)
    GtkLayerShell.set_layer(window, layer)
    for edge in anchors:
        GtkLayerShell.set_anchor(window, edge, True)
    for edge, value in (margins or {}).items():
        GtkLayerShell.set_margin(window, edge, value)
    if exclusive_zone:
        GtkLayerShell.set_exclusive_zone(window, exclusive_zone)
    if keyboard and hasattr(GtkLayerShell, "KeyboardMode"):
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.ON_DEMAND)


def launch(command):
    """Start a fixed command without invoking a shell."""
    import subprocess
    import sys

    try:
        subprocess.Popen(command, start_new_session=True)
        return True
    except OSError as error:
        print(f"DarkOS: could not launch {command[0]}: {error}", file=sys.stderr)
        return False


def command_output(command, timeout=1.5):
    import subprocess

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


class DarkOSDockWindow(Gtk.Window):
    """Floating dock on any screen edge, in one of three sizes (the
    dock_position / dock_size settings; apply_layout() re-lays it out live).
    A launcher button, a divider, then the pinned apps. The clock lives in
    the status bar, not here."""

    _EDGES = {
        "bottom": GtkLayerShell.Edge.BOTTOM,
        "top": GtkLayerShell.Edge.TOP,
        "left": GtkLayerShell.Edge.LEFT,
        "right": GtkLayerShell.Edge.RIGHT,
    }

    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.set_title("DarkOS Dock")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        settings = load_settings()
        self._layout = None
        self._exclusive_zone = None
        # Only creates the layer surface; anchors, margin and exclusive zone
        # come from apply_layout() at the end of __init__.
        configure_layer_window(
            self, "darkos-dock", GtkLayerShell.Layer.TOP, (), {}, keyboard=True,
        )

        dock = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_XS)
        add_class(dock, "dock-bar")
        dock.set_halign(Gtk.Align.CENTER)
        self._dock_box = dock

        self._dock_icons = {}
        self._dock_images = {}
        self._dock_labels = {}
        self._dock_dots = {}
        self._dock_wm_classes = {}

        def make_dock_slot(key, icon, name, command, wm_class):
            slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            slot.set_halign(Gtk.Align.CENTER)
            btn = make_icon_button(
                icon, name,
                lambda _button, selected=command: launch(selected),
                "dock-icon-button", 40,
            )
            self._dock_icons[key] = btn
            self._dock_images[key] = btn.get_child()
            self._dock_wm_classes[key] = wm_class
            slot.pack_start(btn, False, False, 0)
            dot = Gtk.Box()
            add_class(dot, "dock-running-dot")
            dot.set_halign(Gtk.Align.CENTER)
            self._dock_dots[key] = dot
            slot.pack_start(dot, False, False, 1)
            label = make_label(name, "dock-label")
            label.set_xalign(0.5)
            self._dock_labels[key] = label
            slot.pack_start(label, False, False, 2)
            return slot

        dock.pack_start(
            make_dock_slot("launcher", "view-app-grid-symbolic", "Apps", LAUNCHER_COMMAND, ""),
            False, False, 2,
        )
        separator = Gtk.Box()
        add_class(separator, "dock-separator")
        self._dock_separator = separator
        dock.pack_start(separator, False, False, 2)
        for key, icon, name, command, wm_class in DOCK_APPS:
            dock.pack_start(make_dock_slot(key, icon, name, command, wm_class), False, False, 2)

        self.add(dock)
        self.connect(
            "size-allocate",
            lambda _widget, allocation: self._update_exclusive_zone(allocation),
        )
        self.show_all()
        self.apply_layout(settings["dock_position"], settings["dock_size"])
        self._running_lock = threading.Lock()
        self._refresh_running_indicators()
        GLib.timeout_add_seconds(3, self._refresh_running_indicators)

    def apply_layout(self, position, size):
        """Move/resize the dock live. Returns True if anything changed.

        Unknown values fall back to the defaults (tokens.dock_layout), so a
        bad settings file can't strand the dock off-screen. Re-anchors the
        layer surface, flips the box orientation, resizes the icons and
        shows/hides the text labels.
        """
        layout = dock_layout(position, size)
        if layout == self._layout:
            return False
        self._layout = layout

        edge = self._EDGES[layout.position]
        for candidate in self._EDGES.values():
            GtkLayerShell.set_anchor(self, candidate, candidate == edge)
            GtkLayerShell.set_margin(
                self, candidate, layout.edge_margin if candidate == edge else 0
            )

        self._dock_box.set_orientation(
            Gtk.Orientation.VERTICAL if layout.vertical else Gtk.Orientation.HORIZONTAL
        )
        context = self._dock_box.get_style_context()
        for name, active in (("vertical", layout.vertical), ("compact", layout.size == "compact")):
            if active:
                context.add_class(name)
            else:
                context.remove_class(name)
        for key, button in self._dock_icons.items():
            button.set_size_request(layout.button_px, layout.button_px)
            self._dock_images[key].set_pixel_size(layout.button_px // 2)
            self._dock_labels[key].set_visible(layout.show_labels)

        # A toplevel only grows by itself; resize(1, 1) lets it shrink back
        # to its natural size when the dock gets smaller or changes axis.
        self.resize(1, 1)
        self._exclusive_zone = None
        self._update_exclusive_zone()
        return True

    def _update_exclusive_zone(self, allocation=None):
        """Reserve screen space equal to the dock's measured thickness."""
        layout = self._layout
        if layout is None:
            return
        allocation = allocation or self.get_allocation()
        thickness = allocation.width if layout.vertical else allocation.height
        if thickness <= 1:  # not allocated yet; size-allocate will call again
            return
        zone = dock_exclusive_zone(layout, thickness)
        if zone != self._exclusive_zone:
            self._exclusive_zone = zone
            GtkLayerShell.set_exclusive_zone(self, zone)

    def _refresh_running_indicators(self):
        """Timer tick (main thread). `hyprctl` runs on a worker thread: it used
        to run right here, so a slow compositor froze the whole shell UI."""
        if not self.get_visible():
            return True
        if not self._running_lock.acquire(blocking=False):
            return True  # previous poll still running
        threading.Thread(target=self._poll_running, daemon=True).start()
        return True

    def _poll_running(self):
        try:
            running = _running_window_classes()
        finally:
            self._running_lock.release()
        GLib.idle_add(self._apply_running, running)

    def _apply_running(self, running):
        for key, dot in self._dock_dots.items():
            wm_class = self._dock_wm_classes.get(key, "")
            ctx = dot.get_style_context()
            if wm_class and any(wm_class in cls or cls in wm_class for cls in running if cls):
                ctx.add_class("running")
            else:
                ctx.remove_class("running")
        return False


def _format_rate(bytes_per_second):
    if bytes_per_second is None:
        return "--"
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.1f} MiB/s"
    return f"{bytes_per_second / 1024:.0f} KiB/s"


def parse_mako_notifications(text):
    """Turn `makoctl list` / `makoctl history` output into plain dicts.

    mako prints a D-Bus value as JSON: {"type": "aa{sv}", "data": [[ {...} ]]}
    with every field wrapped as {"type": ..., "data": ...}. Anything that
    doesn't match that shape yields an empty list, never an exception: a
    notification list is not worth crashing the shell for.
    """
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data[0] if isinstance(data, list) and data and isinstance(data[0], list) else []

    def field(item, name):
        value = item.get(name)
        return value.get("data") if isinstance(value, dict) else value

    notifications = []
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = field(item, "id")
        notifications.append({
            "id": identifier if isinstance(identifier, int) else 0,
            "app": str(field(item, "app-name") or ""),
            "summary": str(field(item, "summary") or ""),
            "body": str(field(item, "body") or ""),
        })
    return notifications


def parse_percent(text):
    """'62' -> 62 for `pamixer --get-volume`; None if it isn't a number."""
    try:
        return max(0, min(100, int(str(text).strip())))
    except (TypeError, ValueError):
        return None


def parse_brightness(text):
    """`brightnessctl -m` -> percent, e.g. 'intel_backlight,backlight,3000,62%,4800' -> 62."""
    if not text:
        return None
    for part in str(text).strip().splitlines()[0].split(","):
        part = part.strip()
        if part.endswith("%") and part[:-1].isdigit():
            return max(0, min(100, int(part[:-1])))
    return None


class DarkOSCommandCenter(Gtk.Window):
    """One solid panel, opened from the status bar or Super+H: quick settings,
    volume and brightness, notifications, media (only while a player is
    running), resources and the calendar.

    Nothing runs while it is hidden: the timers start when it is shown and
    stop when it is hidden (docs/MASTER-PLAN.md section 5).
    """

    WIDTH = 360
    MAX_NOTIFICATIONS = 5

    TOGGLES = (
        ("wifi", "network-wireless-signal-excellent-symbolic", "Wi-Fi"),
        ("bluetooth", "bluetooth-active-symbolic", "Bluetooth"),
        ("night_light", "display-brightness-symbolic", "Night Light"),
        ("focus", "notifications-disabled-symbolic", "Focus"),
        ("airplane", "airplane-mode-symbolic", "Airplane"),
    )

    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.sampler = SystemSampler()
        self.syncing_toggles = False
        self.syncing_levels = False
        self.media_active = False
        self._pending_levels = {}
        self._level_timer = 0
        self._status_timer = 0
        self._clear_before_id = 0
        self._timers = []
        self._fit_id = 0
        self._destroyed = False
        self._notification_lock = threading.Lock()
        self._media_fetch_lock = threading.Lock()
        self._position_fetch_lock = threading.Lock()
        self.set_title("DarkOS Command Center")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        # The margin around the panel is where its shadow is drawn; a layer
        # surface can't paint outside its own bounds.
        configure_layer_window(
            self,
            "darkos-center",
            GtkLayerShell.Layer.TOP,
            (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.RIGHT),
            {GtkLayerShell.Edge.TOP: 0, GtkLayerShell.Edge.RIGHT: 0},
            keyboard=True,
        )

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_margin_top(SPACE_SM)
        outer.set_margin_bottom(SPACE_MD + SPACE_SM)
        outer.set_margin_start(SPACE_MD + SPACE_SM)
        outer.set_margin_end(SPACE_MD + SPACE_SM)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.set_size_request(self.WIDTH, -1)
        add_class(panel, "command-center")
        outer.pack_start(panel, False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_overlay_scrolling(True)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.set_max_content_height(self._max_panel_height())
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content = content
        content.pack_start(self.build_quick_settings(), False, False, 0)
        content.pack_start(self.make_divider(), False, False, 0)
        content.pack_start(self.build_notifications(), False, False, 0)
        self.media_section = self.build_media()
        content.pack_start(self.media_section, False, False, 0)
        content.pack_start(self.make_divider(), False, False, 0)
        content.pack_start(self.build_system(), False, False, 0)
        content.pack_start(self.make_divider(), False, False, 0)
        content.pack_start(self.build_calendar(), False, False, 0)
        self.scroller.add(content)
        panel.pack_start(self.scroller, True, True, 0)

        self.add(outer)
        self.connect("key-press-event", self._on_key)
        self.connect("destroy", self._on_destroy)
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.application.register_state_listener(self)
        self.sync_from_application()
        self.show_all()

    # ── Layout helpers ─────────────────────────────────────────────────

    @staticmethod
    def _max_panel_height():
        """Tallest the panel may grow: the screen minus the status bar, the
        dock and some air. Taller than that and it scrolls."""
        height = 800
        display = Gdk.Display.get_default()
        if display is not None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
            if monitor is not None:
                height = monitor.get_geometry().height
        return max(320, height - 220)

    @staticmethod
    def make_divider():
        divider = Gtk.Box()
        add_class(divider, "cc-divider")
        return divider

    @staticmethod
    def make_section():
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(section, "cc-section")
        return section

    # ── Quick settings ─────────────────────────────────────────────────

    def build_quick_settings(self):
        section = self.make_section()
        grid = Gtk.Grid()
        grid.set_column_spacing(SPACE_SM)
        grid.set_row_spacing(SPACE_SM)
        grid.set_column_homogeneous(True)
        self.toggle_buttons = {}
        for index, (name, icon_name, label) in enumerate(self.TOGGLES):
            button = Gtk.ToggleButton()
            button.add(make_icon_label(icon_name, label))
            add_class(button, "toggle-button")
            button.connect("toggled", self.on_toggle, name)
            button.get_accessible().set_name(label)
            last_alone = index == len(self.TOGGLES) - 1 and len(self.TOGGLES) % 2 == 1
            grid.attach(button, index % 2, index // 2, 2 if last_alone else 1, 1)
            self.toggle_buttons[name] = button
        section.pack_start(grid, False, False, 0)

        self.volume_row, self.volume_scale = self.build_level_row(
            "audio-volume-high-symbolic", "Audio volume", 0, 100
        )
        self.volume_scale.connect("value-changed", self.on_level_changed, "volume")
        self.brightness_row, self.brightness_scale = self.build_level_row(
            "display-brightness-symbolic", "Display brightness", 5, 100
        )
        self.brightness_scale.connect("value-changed", self.on_level_changed, "brightness")
        section.pack_start(self.volume_row, False, False, 0)
        section.pack_start(self.brightness_row, False, False, 0)

        self.control_status = make_label("", "caption", wrap=True)
        self.control_status.set_no_show_all(True)
        section.pack_start(self.control_status, False, False, 0)
        return section

    @staticmethod
    def build_level_row(icon_name, name, minimum, maximum):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        image.set_pixel_size(16)
        row.pack_start(image, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum, maximum, 5)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.get_accessible().set_name(name)
        scale.set_tooltip_text(name)
        row.pack_start(scale, True, True, 0)
        # Hidden until a real backend answers: a slider with no backend
        # behind it is a lie.
        row.set_no_show_all(True)
        return row, scale

    def sync_from_application(self):
        self.syncing_toggles = True
        airplane_active = bool(self.application.toggle_state.get("airplane", False))
        for name, button in self.toggle_buttons.items():
            button.set_active(bool(self.application.toggle_state.get(name, False)))
            if name in ("wifi", "bluetooth"):
                button.set_sensitive(not airplane_active)
        self.syncing_toggles = False

    def on_toggle(self, button, name):
        if self.syncing_toggles:
            return
        self.application.set_toggle(name, button.get_active())

    def set_control_status(self, message, is_stub=False):
        """One short line under the controls; clears itself after a few
        seconds. Failures are amber, confirmations stay muted."""
        self.control_status.set_text(message)
        context = self.control_status.get_style_context()
        context.remove_class("flag-text")
        context.remove_class("caption")
        add_class(self.control_status, "flag-text" if is_stub else "caption")
        self.control_status.show()
        if self._status_timer:
            GLib.source_remove(self._status_timer)
        self._status_timer = GLib.timeout_add_seconds(6, self._clear_control_status)

    def _clear_control_status(self):
        self._status_timer = 0
        self.control_status.hide()
        return False

    # Volume and brightness: read the real value on open, apply the final
    # value 150 ms after the slider stops (not once per pixel dragged).

    def on_level_changed(self, scale, kind):
        if self.syncing_levels:
            return
        self._pending_levels[kind] = int(scale.get_value())
        if not self._level_timer:
            self._level_timer = GLib.timeout_add(150, self._flush_levels)

    def _flush_levels(self):
        self._level_timer = 0
        pending, self._pending_levels = self._pending_levels, {}
        if "volume" in pending and not launch(["pamixer", "--set-volume", str(pending["volume"])]):
            self.set_control_status("Volume change failed: pamixer is unavailable.", True)
        if "brightness" in pending and not launch(["brightnessctl", "set", f"{pending['brightness']}%"]):
            self.set_control_status("Brightness change failed: no backlight was found.", True)
        return False

    def refresh_levels(self):
        threading.Thread(target=self._fetch_levels, daemon=True).start()

    def _fetch_levels(self):
        volume = command_output(["pamixer", "--get-volume"])
        brightness = command_output(["brightnessctl", "-m"])
        GLib.idle_add(self._apply_levels, volume, brightness)

    def _apply_levels(self, volume, brightness):
        self.syncing_levels = True
        for row, scale, value in (
            (self.volume_row, self.volume_scale, parse_percent(volume)),
            (self.brightness_row, self.brightness_scale, parse_brightness(brightness)),
        ):
            if value is None:
                row.hide()
            else:
                scale.set_value(value)
                reveal(row)
        self.syncing_levels = False
        self._queue_fit()
        return False

    # ── Notifications ──────────────────────────────────────────────────

    def build_notifications(self):
        section = self.make_section()
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        header.pack_start(make_label("Notifications", "section-title"), True, True, 0)
        clear_button = Gtk.Button()
        clear_button.add(make_label("Clear all", ""))
        add_class(clear_button, "action-button")
        clear_button.set_tooltip_text("Dismiss notifications")
        clear_button.connect("clicked", self.clear_notifications)
        header.pack_end(clear_button, False, False, 0)
        section.pack_start(header, False, False, 0)
        self.notification_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_XS)
        section.pack_start(self.notification_list, False, False, 0)
        self.notification_empty = make_label("You're all caught up.", "cc-empty")
        section.pack_start(self.notification_empty, False, False, 0)
        return section

    def clear_notifications(self, _button):
        """Dismiss what is on screen, and hide everything up to now: mako has
        no 'clear history' command, so the panel remembers the newest id."""
        launch(["makoctl", "dismiss", "--all"])
        newest = max((n["id"] for n in self._notifications), default=0)
        self._clear_before_id = max(self._clear_before_id, newest)
        self._apply_notifications(self._notifications, True)

    _notifications = ()

    def refresh_notifications(self):
        if not self._notification_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._fetch_notifications, daemon=True).start()

    def _fetch_notifications(self):
        try:
            active = command_output(["makoctl", "list"])
            history = command_output(["makoctl", "history"])
        finally:
            self._notification_lock.release()
        entries = []
        seen = set()
        # Active ones first, newest first; then history (oldest first from
        # mako, so reversed), skipping anything already listed.
        for batch in (
            sorted(parse_mako_notifications(active), key=lambda n: -n["id"]),
            sorted(parse_mako_notifications(history), key=lambda n: -n["id"]),
        ):
            for entry in batch:
                if entry["id"] not in seen:
                    seen.add(entry["id"])
                    entries.append(entry)
        GLib.idle_add(self._apply_notifications, entries, active is not None)

    def _apply_notifications(self, entries, available):
        self._notifications = list(entries)
        for child in self.notification_list.get_children():
            self.notification_list.remove(child)
        visible = [n for n in self._notifications if n["id"] > self._clear_before_id]
        for entry in visible[: self.MAX_NOTIFICATIONS]:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            add_class(card, "cc-notification")
            if entry["app"]:
                card.pack_start(make_label(entry["app"], "caption"), False, False, 0)
            title = make_label(entry["summary"] or "(no title)", "media-title", wrap=True)
            card.pack_start(title, False, False, 0)
            if entry["body"]:
                body = make_label(entry["body"], "body-muted", wrap=True)
                body.set_lines(2)
                body.set_ellipsize(Pango.EllipsizeMode.END)
                card.pack_start(body, False, False, 0)
            self.notification_list.pack_start(card, False, False, 0)
        self.notification_list.show_all()
        if not available:
            self.notification_empty.set_text("Notifications aren't available (mako isn't running).")
        else:
            self.notification_empty.set_text("You're all caught up.")
        self.notification_empty.set_visible(not visible)
        self._queue_fit()
        return False

    # ── Media ──────────────────────────────────────────────────────────

    def build_media(self):
        section = self.make_section()
        section.pack_start(self.make_divider(), False, False, 0)
        section.pack_start(make_label("Now playing", "section-title"), False, False, 0)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        art = Gtk.Box()
        art.set_size_request(56, 56)
        add_class(art, "media-art")
        art_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic", Gtk.IconSize.DIALOG)
        art_icon.set_pixel_size(28)
        art_icon.set_hexpand(True)
        art.pack_start(art_icon, True, True, 0)
        top_row.pack_start(art, False, False, 0)

        text_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_XS)
        text_col.set_valign(Gtk.Align.CENTER)
        self.media_title = make_label("", "media-title", wrap=True)
        self.media_title.set_max_width_chars(24)
        self.media_artist = make_label("", "body-muted", wrap=True)
        self.media_artist.set_max_width_chars(24)
        text_col.pack_start(self.media_title, False, False, 0)
        text_col.pack_start(self.media_artist, False, False, 0)
        top_row.pack_start(text_col, True, True, 0)
        section.pack_start(top_row, False, False, 0)

        progress_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        self.media_progress = Gtk.ProgressBar()
        self.media_progress.set_show_text(False)
        self.media_progress.set_valign(Gtk.Align.CENTER)
        add_class(self.media_progress, "media-progress")
        progress_row.pack_start(self.media_progress, True, True, 0)
        self.media_time = make_label("--:-- / --:--", "caption")
        self.media_time.set_xalign(1.0)
        progress_row.pack_start(self.media_time, False, False, 0)
        section.pack_start(progress_row, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_MD)
        controls.set_halign(Gtk.Align.CENTER)
        for icon, name, command in (
            ("media-skip-backward-symbolic", "Previous track", ["playerctl", "previous"]),
            ("media-playback-start-symbolic", "Play or pause", ["playerctl", "play-pause"]),
            ("media-skip-forward-symbolic", "Next track", ["playerctl", "next"]),
        ):
            controls.pack_start(
                make_icon_button(icon, name, lambda _b, c=command: launch(c)), False, False, 0
            )
        section.pack_start(controls, False, False, 0)
        # Only exists while a player does.
        section.set_no_show_all(True)
        section.hide()
        return section

    def refresh_media(self):
        """Timer tick (main thread): start a background fetch, never block."""
        if not self.get_visible():
            return True
        if not self._media_fetch_lock.acquire(blocking=False):
            return True  # previous fetch still running (slow player)
        threading.Thread(target=self._fetch_media, daemon=True).start()
        return True

    def _fetch_media(self):
        try:
            metadata = command_output(
                ["playerctl", "metadata", "--format", "{{title}}\t{{artist}}"]
            )
            status = command_output(["playerctl", "status"])
        finally:
            self._media_fetch_lock.release()
        GLib.idle_add(self._apply_media, metadata, status)

    def _apply_media(self, metadata, status):
        active = metadata is not None and status is not None
        if active:
            title, separator, artist = metadata.partition("\t")
            self.media_title.set_text(title or "Untitled media")
            self.media_artist.set_text(artist if separator and artist else status)
        self.media_active = active
        if active:
            reveal(self.media_section)
            self.refresh_media_position()
        else:
            self.media_section.hide()
        self._queue_fit()
        return False

    def refresh_media_position(self):
        """Poll play position and update the progress bar and time."""
        if not self.get_visible() or not self.media_active:
            return True  # truthy: this is also a repeating GLib timer
        if not self._position_fetch_lock.acquire(blocking=False):
            return True
        threading.Thread(target=self._fetch_media_position, daemon=True).start()
        return True

    def _fetch_media_position(self):
        try:
            length_raw = command_output(["playerctl", "metadata", "mpris:length"])
            position_raw = command_output(["playerctl", "position"])
        finally:
            self._position_fetch_lock.release()
        GLib.idle_add(self._apply_media_position, length_raw, position_raw)

    def _apply_media_position(self, length_raw, position_raw):
        total = int(length_raw) / 1_000_000 if length_raw and length_raw.isdigit() else 0
        pos = int(position_raw) / 1_000_000 if position_raw and position_raw.replace(".", "").isdigit() else 0
        if total > 0:
            self.media_progress.set_fraction(max(0.0, min(1.0, pos / total)))
            self.media_time.set_text(
                f"{int(pos // 60)}:{int(pos % 60):02d} / {int(total // 60)}:{int(total % 60):02d}"
            )
        return False

    # ── System ─────────────────────────────────────────────────────────

    def build_system(self):
        section = self.make_section()
        section.pack_start(make_label("System", "section-title"), False, False, 0)
        self.resource_rows = {
            "cpu": ResourceRow("CPU"),
            "memory": ResourceRow("Memory"),
            "disk": ResourceRow("Disk"),
            "gpu": ResourceRow("GPU"),
        }
        for row in self.resource_rows.values():
            section.pack_start(row, False, False, 0)
        self.network_label = make_label("↓ --    ↑ --", "caption")
        section.pack_start(self.network_label, False, False, 0)
        return section

    def refresh_system(self):
        if not self.get_visible():
            return True  # hidden: don't sample /proc and /sys
        self.resource_rows["cpu"].set_percent(self.sampler.cpu_percent())
        self.resource_rows["memory"].set_percent(self.sampler.memory_percent())
        self.resource_rows["disk"].set_percent(self.sampler.storage_percent())
        self.resource_rows["gpu"].set_percent(self.sampler.gpu_percent())
        down, up = self.sampler.network_rates()
        self.network_label.set_text(f"↓ {_format_rate(down)}    ↑ {_format_rate(up)}")
        self._queue_fit()
        return True

    # ── Calendar ───────────────────────────────────────────────────────

    @staticmethod
    def build_calendar():
        section = DarkOSCommandCenter.make_section()
        calendar_widget = Gtk.Calendar()
        add_class(calendar_widget, "calendar")
        calendar_widget.set_hexpand(True)
        section.pack_start(calendar_widget, False, False, 0)
        return section

    # ── Sizing ─────────────────────────────────────────────────────────

    def _queue_fit(self):
        """Ask for one height re-fit on the next idle (coalesces bursts)."""
        if not self._fit_id and not self._destroyed:
            self._fit_id = GLib.idle_add(self._fit_height)

    def _fit_height(self):
        """A layer-shell window is sized to its *minimum* request, and a
        ScrolledWindow's minimum is tiny, so the panel collapsed to a sliver.
        Pin the scroller's minimum to the content's natural height (capped at
        the screen) whenever the content changes."""
        self._fit_id = 0
        if self._destroyed:
            return False
        _minimum, natural = self._content.get_preferred_height_for_width(self.WIDTH)
        target = min(natural, self._max_panel_height())
        if target != self.scroller.get_min_content_height():
            self.scroller.set_min_content_height(target)
            self.resize(1, 1)
        return False

    # ── Open / close ───────────────────────────────────────────────────

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def _on_map(self, _widget):
        """Shown: read fresh data now, then keep it fresh while visible."""
        self.sync_from_application()
        self.refresh_levels()
        self.refresh_notifications()
        self.refresh_media()
        self.refresh_system()
        self._queue_fit()
        self._timers = [
            GLib.timeout_add_seconds(2, self.refresh_system),
            GLib.timeout_add_seconds(2, self.refresh_media_position),
            GLib.timeout_add_seconds(5, self.refresh_media),
        ]

    def _on_destroy(self, _widget):
        self._destroyed = True
        self._on_unmap(None)

    def _on_unmap(self, _widget):
        """Hidden: stop every timer. Nothing runs while the panel is closed."""
        for source in self._timers:
            GLib.source_remove(source)
        self._timers = []
