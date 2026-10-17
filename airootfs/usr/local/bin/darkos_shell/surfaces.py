import math
import threading

import cairo
import gi

gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk, GtkLayerShell, Pango

from darkos_shell.canvases import (
    GLOW_STROKES_OUTSIDE_IN,
    stroke_glow,
)
from darkos_shell.css import CSS_STYLE
from darkos_shell.tokens import (
    CAIRO_ACCENT,
    CAIRO_DANGER,
    CAIRO_MUTED,
    CAIRO_PRIMARY,
    CAIRO_SECONDARY,
    CAIRO_TEXT,
    COLOR_ACCENT,
    COLOR_BG_ALT,
    COLOR_PRIMARY,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    RADIUS_CONTROL,
    RADIUS_PANEL,
    RADIUS_DIALOG,
    REDUCE_MOTION,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    SPACE_XL,
    dock_exclusive_zone,
    dock_layout,
)
from darkos_shell.system_sampler import SystemSampler
from darkos_shell.user_settings import load_settings
import datetime
import json
import subprocess


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
    Center slot is a live clock."""

    _EDGES = {
        "bottom": GtkLayerShell.Edge.BOTTOM,
        "top": GtkLayerShell.Edge.TOP,
        "left": GtkLayerShell.Edge.LEFT,
        "right": GtkLayerShell.Edge.RIGHT,
    }

    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.orb_cycle_index = 0
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

        # wm_class here matches each app's own WM_CLASS constant (and the
        # hyprland.conf windowrule matchers) so the running-dot below each
        # icon can be driven by real `hyprctl clients -j` data.
        left_apps = (
            ("files", "folder-symbolic", "Files", ["/usr/local/bin/darkos-files.py"], "darkos-files"),
            ("terminal", "utilities-terminal-symbolic", "Terminal", ["/usr/local/bin/the-void.sh"], "darkos-terminal"),
            ("browser", "web-browser-symbolic", "Browser", ["firefox"], "firefox"),
        )
        right_apps = (
            ("notes", "accessories-text-editor-symbolic", "Notes", ["/usr/local/bin/darkos-notes.py"], "darkos-notes"),
            ("store", "system-software-install-symbolic", "Store", ["/usr/local/bin/darkos-store.py"], "darkos-store"),
            ("settings", "preferences-system-symbolic", "Settings", ["/usr/local/bin/darkos-settings.py"], "darkos-settings"),
        )
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

        for key, icon, name, command, wm_class in left_apps:
            dock.pack_start(make_dock_slot(key, icon, name, command, wm_class), False, False, 2)

        self.clock_label = make_label("--:--", "dock-clock")
        self.clock_label.set_justify(Gtk.Justification.CENTER)
        dock.pack_start(self.clock_label, False, False, SPACE_MD)
        self._tick_clock()
        # Minute resolution is all the label shows; a 1s timer woke the
        # shell (and re-laid-out the dock) 60x more often than needed.
        GLib.timeout_add_seconds(20, self._tick_clock)

        for key, icon, name, command, wm_class in right_apps:
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
        self._tick_clock()
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

    def _tick_clock(self):
        # A vertical dock stacks hours over minutes so it stays slim.
        stacked = bool(self._layout and self._layout.vertical)
        fmt = "%H\n%M" if stacked else "%H:%M"
        self.clock_label.set_text(datetime.datetime.now().strftime(fmt))
        return True

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


class DarkOSIconRail(Gtk.Window):
    """Left-side vertical icon rail — 10 app shortcuts."""

    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.set_title("DarkOS App Rail")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-rail",
            GtkLayerShell.Layer.TOP,
            (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT),
            {
                GtkLayerShell.Edge.TOP: 58,
                GtkLayerShell.Edge.BOTTOM: 96,
                GtkLayerShell.Edge.LEFT: 12,
            },
            exclusive_zone=68,
            keyboard=True,
        )

        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_XS)
        add_class(rail, "rail")
        rail.set_valign(Gtk.Align.CENTER)
        actions = (
            ("system-search-symbolic", "Search", "search"),
            ("folder-symbolic", "Files", "files"),
            ("utilities-terminal-symbolic", "Terminal", "terminal"),
            ("preferences-system-symbolic", "Settings", "settings"),
            ("web-browser-symbolic", "Browser", "browser"),
            ("image-x-generic-symbolic", "Gallery", "gallery"),
            ("system-software-install-symbolic", "Store", "store"),
            ("accessories-text-editor-symbolic", "Notes", "notes"),
            ("audio-x-generic-symbolic", "Music", "music"),
            ("applications-games-symbolic", "Gaming", "gaming"),
        )
        for icon, name, action in actions:
            rail.pack_start(
                make_icon_button(
                    icon,
                    name,
                    lambda _button, selected=action: self.application.handle_rail_action(
                        selected
                    ),
                ),
                False,
                False,
                0,
            )
        self.add(rail)
        self.show_all()


class DarkOSLeftPanels(Gtk.Window):
    """Left-of-center panels: weather and system overview."""

    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.sampler = SystemSampler()
        self.set_title("DarkOS Left Panels")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-left",
            GtkLayerShell.Layer.TOP,
            (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.BOTTOM),
            {
                GtkLayerShell.Edge.TOP: 16,
                GtkLayerShell.Edge.LEFT: 16,
                GtkLayerShell.Edge.BOTTOM: 96,
            },
            keyboard=True,
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        root.set_size_request(330, -1)
        root.pack_start(self.build_weather_panel(), False, False, 0)
        root.pack_start(self.build_system_panel(), False, False, 0)
        self.add(root)
        self.show_all()
        self.refresh_system()
        from gi.repository import GLib
        GLib.timeout_add_seconds(2, self.refresh_system)

    @staticmethod
    def build_weather_panel():
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_XS)
        add_class(panel, "glass-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        header.pack_start(make_label("WEATHER", "section-title"), True, True, 0)
        weather_status = make_icon_label("weather-clear-symbolic", "--")
        add_class(weather_status, "status-text")
        header.pack_end(weather_status, False, False, 0)
        panel.pack_start(header, False, False, 0)
        panel.pack_start(
            make_label(
                "Forecast unavailable: no weather service is connected.",
                "stub-text",
                wrap=True,
            ),
            False,
            False,
            0,
        )
        return panel

    def build_system_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("SYSTEM OVERVIEW", "section-title"), False, False, 0)
        grid = Gtk.Grid()
        grid.set_row_spacing(SPACE_XS)
        grid.set_column_spacing(SPACE_XS)
        grid.set_column_homogeneous(True)
        from darkos_shell.canvases import RingGauge
        self.gauges = {
            "CPU": RingGauge("CPU", CAIRO_PRIMARY),
            "GPU": RingGauge("GPU", CAIRO_SECONDARY),
            "RAM": RingGauge("RAM", CAIRO_ACCENT),
            "DISK": RingGauge("DISK", CAIRO_PRIMARY),
        }
        for index, gauge in enumerate(self.gauges.values()):
            grid.attach(gauge, index % 2, index // 2, 1, 1)
        panel.pack_start(grid, False, False, 0)
        self.network_label = make_label("↓ 0 KiB/s    ↑ 0 KiB/s", "body-muted")
        panel.pack_start(self.network_label, False, False, 0)
        return panel

    def refresh_system(self):
        if not self.get_visible():
            return True  # hidden panel: skip sampling /proc and /sys
        self.gauges["CPU"].set_value(self.sampler.cpu_percent())
        self.gauges["GPU"].set_value(self.sampler.gpu_percent())
        self.gauges["RAM"].set_value(self.sampler.memory_percent())
        self.gauges["DISK"].set_value(self.sampler.storage_percent())
        down, up = self.sampler.network_rates()
        self.network_label.set_text(f"↓ {_format_rate(down)}    ↑ {_format_rate(up)}")
        return True


def _format_rate(bytes_per_second):
    if bytes_per_second is None:
        return "--"
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.1f} MiB/s"
    return f"{bytes_per_second / 1024:.0f} KiB/s"


class DarkOSRightPanels(Gtk.Window):
    """Right-of-center panels: notifications, connectivity, media, calendar."""

    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.syncing_toggles = False
        self.media_active = False
        self.set_title("DarkOS Right Panels")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-right",
            GtkLayerShell.Layer.TOP,
            (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.BOTTOM),
            {
                GtkLayerShell.Edge.TOP: 16,
                GtkLayerShell.Edge.RIGHT: 14,
                GtkLayerShell.Edge.BOTTOM: 108,
            },
            keyboard=True,
        )

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        outer.set_size_request(360, -1)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_overlay_scrolling(True)
        scroller.set_propagate_natural_height(True)
        scroller.set_min_content_height(480)
        scroller.set_max_content_height(600)

        scroll_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        scroll_root.pack_start(self.build_notifications(), False, False, 0)
        scroll_root.pack_start(self.build_media(), False, False, 0)
        scroll_root.pack_start(self.build_connectivity(), False, False, 0)
        scroller.add(scroll_root)

        outer.pack_start(scroller, True, True, 0)
        outer.pack_start(self.build_calendar(), False, False, 0)

        self.add(outer)
        self.application.register_state_listener(self)
        self.sync_from_application()
        self.show_all()
        self._media_fetch_lock = threading.Lock()
        self._position_fetch_lock = threading.Lock()
        # 5s interval so overlapping playerctl calls can't stack
        # if a slow player hangs near the 1.5s command_output timeout.
        GLib.timeout_add(5000, self.refresh_media)
        GLib.timeout_add_seconds(2, self.refresh_media_position)

    def build_notifications(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        header.pack_start(make_label("NOTIFICATIONS", "section-title"), True, True, 0)
        clear_button = Gtk.Button()
        clear_button.add(make_icon_label("edit-clear-all-symbolic", "Clear All"))
        add_class(clear_button, "action-button")
        clear_button.set_tooltip_text("Dismiss visible Mako notifications")
        clear_button.connect("clicked", self.clear_notifications)
        header.pack_end(clear_button, False, False, 0)
        panel.pack_start(header, False, False, 0)
        panel.pack_start(make_label("SYSTEM", "eyebrow"), False, False, 0)
        panel.pack_start(
            make_label("No system notification feed is connected.", "stub-text", wrap=True),
            False,
            False,
            0,
        )
        panel.pack_start(Gtk.Separator(), False, False, 0)
        panel.pack_start(make_label("RECENT", "eyebrow"), False, False, 0)
        self.notification_status = make_label(
            "Mako popups remain live; history integration is not connected.",
            "stub-text",
            wrap=True,
        )
        panel.pack_start(self.notification_status, False, False, 0)
        return panel

    def build_connectivity(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("CONNECTIVITY", "section-title"), False, False, 0)
        grid = Gtk.Grid()
        grid.set_column_spacing(SPACE_SM)
        grid.set_row_spacing(SPACE_SM)
        grid.set_column_homogeneous(True)
        toggle_specs = (
            ("wifi", "network-wireless-signal-excellent-symbolic", "Wi-Fi"),
            ("bluetooth", "bluetooth-active-symbolic", "Bluetooth"),
            ("dark_mode", "weather-clear-night-symbolic", "Dark Mode"),
            ("night_light", "display-brightness-symbolic", "Night Light"),
            ("focus", "notifications-disabled-symbolic", "Focus"),
            ("airplane", "airplane-mode-symbolic", "Airplane"),
        )
        self.toggle_buttons = {}
        for index, (name, icon_name, label) in enumerate(toggle_specs):
            button = Gtk.ToggleButton()
            button.add(make_icon_label(icon_name, label))
            add_class(button, "toggle-button")
            button.connect("toggled", self.on_toggle, name)
            button.get_accessible().set_name(label)
            grid.attach(button, index % 2, index // 2, 1, 1)
            self.toggle_buttons[name] = button
        self.toggle_buttons["dark_mode"].set_sensitive(False)
        self.toggle_buttons["dark_mode"].set_tooltip_text(
            "Dark mode is the only shell theme in Phase 2"
        )
        panel.pack_start(grid, False, False, 0)

        self.volume_scale = self.add_scale(panel, "Audio volume", 0, 100, 5, 75)
        self.volume_scale.connect("value-changed", self.on_volume_changed)
        self.brightness_scale = self.add_scale(
            panel, "Display brightness", 10, 100, 5, 80
        )
        self.brightness_scale.connect("value-changed", self.on_brightness_changed)
        self.control_status = make_label(
            "Dark Mode, Night Light, and Focus are preview controls only.",
            "stub-text",
            wrap=True,
        )
        panel.pack_start(self.control_status, False, False, 0)
        return panel

    @staticmethod
    def add_scale(panel, title, minimum, maximum, step, initial):
        label = make_label(title, "body-muted")
        panel.pack_start(label, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum, maximum, step)
        scale.set_draw_value(False)
        scale.set_value(initial)
        panel.pack_start(scale, False, False, 0)
        return scale

    def build_media(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("NOW PLAYING", "section-title"), False, False, 0)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        self.media_art = Gtk.DrawingArea()
        self.media_art.set_size_request(56, 56)
        self.media_art.connect("draw", self.on_media_art_draw)
        add_class(self.media_art, "media-art")
        self.media_art.queue_draw()
        top_row.pack_start(self.media_art, False, False, 0)

        text_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_XS)
        text_col.set_valign(Gtk.Align.CENTER)
        self.media_title = make_label("No active media", "media-title", wrap=True)
        self.media_title.set_max_width_chars(22)
        self.media_artist = make_label(
            "Start a player to populate this widget.", "body-muted", wrap=True
        )
        self.media_artist.set_max_width_chars(22)
        text_col.pack_start(self.media_title, False, False, 0)
        text_col.pack_start(self.media_artist, False, False, 0)
        top_row.pack_start(text_col, True, True, 0)
        panel.pack_start(top_row, False, False, 0)

        progress_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.media_progress = Gtk.ProgressBar()
        self.media_progress.set_show_text(False)
        add_class(self.media_progress, "media-progress")
        self.media_progress.set_fraction(0.0)
        progress_row.pack_start(self.media_progress, True, True, 0)
        self.media_time = make_label("--:-- / --:--", "body-muted")
        self.media_time.set_size_request(70, -1)
        self.media_time.set_xalign(1.0)
        progress_row.pack_start(self.media_time, False, False, SPACE_XS)
        panel.pack_start(progress_row, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_MD)
        controls.set_halign(Gtk.Align.CENTER)
        self.media_buttons = (
            make_icon_button(
                "media-skip-backward-symbolic",
                "Previous track",
                lambda _button: launch(["playerctl", "previous"]),
            ),
            make_icon_button(
                "media-playback-pause-symbolic",
                "Play or pause",
                lambda _button: launch(["playerctl", "play-pause"]),
            ),
            make_icon_button(
                "media-skip-forward-symbolic",
                "Next track",
                lambda _button: launch(["playerctl", "next"]),
            ),
        )
        for button in self.media_buttons:
            button.set_sensitive(False)
            controls.pack_start(button, False, False, 0)
        panel.pack_start(controls, False, False, 0)
        return panel

    @staticmethod
    def build_calendar():
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("CALENDAR", "section-title"), False, False, 0)
        calendar_widget = Gtk.Calendar()
        add_class(calendar_widget, "calendar")
        calendar_widget.set_hexpand(True)
        calendar_widget.set_size_request(-1, 180)
        panel.pack_start(calendar_widget, False, False, 0)
        return panel

    @staticmethod
    def on_media_art_draw(widget, cr):
        """Draw a placeholder album-art tile: radial gradient with a music note glyph."""
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cx, cy = width / 2.0, height / 2.0

        gradient = cairo.RadialGradient(cx, cy, 2.0, cx, cy, min(cx, cy))
        gradient.add_color_stop_rgba(0.0, 0.0, 0.898, 1.0, 0.18)
        gradient.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.06)
        cr.arc(cx, cy, min(cx, cy), 0, 2 * math.pi)
        cr.set_source(gradient)
        cr.fill()

        cr.arc(cx, cy, min(cx, cy) - 3, 0, 2 * math.pi)
        from darkos_shell.canvases import stroke_glow
        stroke_glow(cr, CAIRO_PRIMARY, 0.35)

        cr.set_line_width(2.0)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(*CAIRO_TEXT, 0.50)
        cr.save()
        cr.translate(cx - 6.0, cy + 8.0)
        cr.scale(1.0, 0.75)
        cr.arc(0.0, 0.0, 7.0, 0.0, 2 * math.pi)
        cr.set_source_rgba(*CAIRO_TEXT, 0.50)
        cr.fill_preserve()
        cr.set_source_rgba(*CAIRO_TEXT, 0.70)
        cr.stroke()
        cr.restore()
        cr.move_to(cx + 1.0, cy + 7.0)
        cr.line_to(cx + 10.0, cy - 12.0)
        cr.stroke()
        cr.move_to(cx + 10.0, cy - 12.0)
        cr.curve_to(cx + 16.0, cy - 6.0, cx + 14.0, cy + 2.0, cx + 10.0, cy + 2.0)
        cr.stroke()
        return False

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
        self.control_status.set_text(message)
        context = self.control_status.get_style_context()
        context.remove_class("status-text")
        context.remove_class("stub-text")
        add_class(self.control_status, "stub-text" if is_stub else "status-text")

    def on_volume_changed(self, scale):
        value = str(int(scale.get_value()))
        if not launch(["pamixer", "--set-volume", value]):
            self.set_control_status("Volume change failed: pamixer is unavailable.", True)

    def on_brightness_changed(self, scale):
        value = f"{int(scale.get_value())}%"
        if not launch(["brightnessctl", "set", value]):
            self.set_control_status(
                "Brightness change failed: no compatible backlight was found.", True
            )

    def clear_notifications(self, _button):
        if launch(["makoctl", "dismiss", "--all"]):
            self.notification_status.set_text("Visible Mako notifications dismissed.")
            self.notification_status.get_style_context().remove_class("stub-text")
            add_class(self.notification_status, "status-text")
        else:
            self.notification_status.set_text("Could not reach Mako notification control.")

    def refresh_media(self):
        """Timer tick (main thread) — kick off a background fetch, don't block."""
        if not self.get_visible():
            return True
        if not self._media_fetch_lock.acquire(blocking=False):
            return True  # previous fetch still running (slow player) — skip this tick
        threading.Thread(target=self._fetch_media, daemon=True).start()
        return True

    def _fetch_media(self):
        """Background thread — the only place that actually blocks."""
        try:
            metadata = command_output(
                ["playerctl", "metadata", "--format", "{{title}}\t{{artist}}"]
            )
            status = command_output(["playerctl", "status"])
        finally:
            self._media_fetch_lock.release()
        GLib.idle_add(self._apply_media, metadata, status)

    def _apply_media(self, metadata, status):
        """Runs on the main thread via idle_add — safe to touch widgets here."""
        active = metadata is not None and status is not None
        if active:
            title, separator, artist = metadata.partition("\t")
            self.media_title.set_text(title or "Untitled media")
            self.media_artist.set_text(artist if separator and artist else status)
        else:
            self.media_title.set_text("No active media")
            self.media_artist.set_text("Start a player to populate this widget.")
        if active != self.media_active:
            self.media_active = active
            for button in self.media_buttons:
                button.set_sensitive(active)
        if active and hasattr(self, "media_progress"):
            self.refresh_media_position()
        return False  # one-shot idle callback, don't repeat

    def refresh_media_position(self):
        """Poll play position and update the progress bar + time display."""
        if not self.get_visible():
            return True
        if not hasattr(self, "media_progress") or not self.media_active:
            return True  # must return truthy — this is also a repeating GLib timer
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
            fraction = max(0.0, min(1.0, pos / total))
            self.media_progress.set_fraction(fraction)
            self.media_time.set_text(
                f"{int(pos // 60)}:{int(pos % 60):02d} / {int(total // 60)}:{int(total % 60):02d}"
            )
        return False  # one-shot idle callback, don't repeat
