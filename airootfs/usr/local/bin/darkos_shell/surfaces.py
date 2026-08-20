import math
import threading

import cairo
import gi

gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk, GtkLayerShell

from darkos_shell.canvases import AIOrbCanvas, WaveformCanvas
from darkos_shell.css import CSS_STYLE
from darkos_shell.tokens import (
    CAIRO_ACCENT,
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
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    SPACE_XL,
)
from darkos_shell.system_sampler import SystemSampler


def add_class(widget, class_name):
    widget.get_style_context().add_class(class_name)
    return widget


def make_label(text, class_name=None, align=Gtk.Align.START, wrap=False):
    widget = Gtk.Label(label=text)
    widget.set_halign(align)
    widget.set_xalign(0.0 if align == Gtk.Align.START else 0.5)
    widget.set_line_wrap(wrap)
    if wrap:
        widget.set_line_wrap_mode(Gtk.WrapMode.WORD_CHAR)
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
    """Floating bottom dock with AI Orb enlarged at center."""

    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.orb_cycle_index = 0
        self.set_title("DarkOS Dock")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-dock",
            GtkLayerShell.Layer.TOP,
            (GtkLayerShell.Edge.BOTTOM,),
            {GtkLayerShell.Edge.BOTTOM: 14},
            exclusive_zone=108,
            keyboard=True,
        )

        dock = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_XS)
        add_class(dock, "dock-bar")
        dock.set_halign(Gtk.Align.CENTER)

        left_apps = (
            ("files", "folder-symbolic", "Files", ["/usr/local/bin/the-void.sh", "-e", "ranger"]),
            ("terminal", "utilities-terminal-symbolic", "Terminal", ["/usr/local/bin/the-void.sh"]),
            ("browser", "web-browser-symbolic", "Browser", ["firefox"]),
        )
        right_apps = (
            ("notes", "accessories-text-editor-symbolic", "Notes", ["/usr/local/bin/the-void.sh", "-e", "nvim"]),
            ("store", "system-software-install-symbolic", "Store", ["wofi", "--show", "drun"]),
            ("settings", "preferences-system-symbolic", "Settings", ["wofi", "--show", "drun"]),
        )
        self._dock_icons = {}

        def make_dock_slot(key, icon, name, command):
            slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            slot.set_halign(Gtk.Align.CENTER)
            btn = make_icon_button(
                icon, name,
                lambda _button, selected=command: launch(selected),
                "dock-icon-button", 40,
            )
            self._dock_icons[key] = btn
            slot.pack_start(btn, False, False, 0)
            label = make_label(name, "dock-label")
            label.set_xalign(0.5)
            slot.pack_start(label, False, False, 2)
            return slot

        for key, icon, name, command in left_apps:
            dock.pack_start(make_dock_slot(key, icon, name, command), False, False, 2)

        orb_button = Gtk.Button()
        add_class(orb_button, "orb-button")
        orb_button.set_tooltip_text("Cycle DarkOS AI preview state")
        orb_button.get_accessible().set_name("DarkOS AI preview state")
        self.ai_orb = AIOrbCanvas(size=56)
        orb_button.add(self.ai_orb)
        orb_button.connect("clicked", self.on_orb_click)
        dock.pack_start(orb_button, False, False, SPACE_SM)

        for key, icon, name, command in right_apps:
            dock.pack_start(make_dock_slot(key, icon, name, command), False, False, 2)

        self.add(dock)
        self.show_all()

    def on_orb_click(self, _button):
        states = ("sleeping", "listening", "thinking", "speaking", "error")
        self.orb_cycle_index = (self.orb_cycle_index + 1) % len(states)
        state = states[self.orb_cycle_index]
        self.ai_orb.set_state(state)
        self.application.set_orb_state(state)
        if state == "error":
            from gi.repository import GLib
            GLib.timeout_add(900, self.finish_error_pulse)

    def set_activity_profile(self, highlight: str | None):
        """Update dock icon highlight for the current activity profile."""
        for icon_name, button in getattr(self, "_dock_icons", {}).items():
            ctx = button.get_style_context()
            ctx.remove_class("dock-highlight")
            if highlight and icon_name == highlight:
                ctx.add_class("dock-highlight")

    def finish_error_pulse(self):
        if self.ai_orb.state == "error":
            self.ai_orb.set_state("sleeping")
            self.orb_cycle_index = 0
        return False


class DarkOSHUDOverlay(Gtk.Window):
    """Text-only HUD — ring graphic lives in the wallpaper."""

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("DarkOS AI Core")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-hud",
            GtkLayerShell.Layer.TOP,
            (GtkLayerShell.Edge.TOP,),
            {GtkLayerShell.Edge.TOP: 76},
        )

        stage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(stage, "hud-stage")
        stage.set_halign(Gtk.Align.CENTER)
        state = make_label("AI CORE  /  PREVIEW MODE", "eyebrow", Gtk.Align.CENTER)
        state.set_xalign(0.5)
        stage.pack_start(state, False, False, 0)
        self.add(stage)
        self.show_all()


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
            ("system-run-symbolic", "AI", "ai"),
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
    """Left-of-center panels: AI chat, weather, system overview."""

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
        root.pack_start(self.build_chat_panel(), False, False, 0)
        root.pack_start(self.build_weather_panel(), False, False, 0)
        root.pack_start(self.build_system_panel(), False, False, 0)
        self.add(root)
        self.show_all()
        self.refresh_system()
        from gi.repository import GLib
        GLib.timeout_add_seconds(2, self.refresh_system)

    def build_chat_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("AI CHAT", "section-title"), False, False, 0)
        panel.pack_start(
            make_label("Good to see you. What should we explore?", wrap=True),
            False,
            False,
            0,
        )
        self.waveform = WaveformCanvas()
        panel.pack_start(self.waveform, False, False, 0)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        self.entry = Gtk.Entry()
        add_class(self.entry, "ai-entry")
        self.entry.set_placeholder_text("Ask DarkOS AI...")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self.on_submit)
        entry_row.pack_start(self.entry, True, True, 0)
        submit = make_icon_button(
            "mail-send-symbolic", "Submit AI preview request", self.on_submit
        )
        entry_row.pack_start(submit, False, False, 0)
        panel.pack_start(entry_row, False, False, 0)

        self.response = make_label(
            "Preview only: the AI backend is not connected.",
            "stub-text",
            wrap=True,
        )
        panel.pack_start(self.response, False, False, 0)
        return panel

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

    def on_submit(self, _widget):
        request_text = self.entry.get_text().strip()
        if not request_text:
            return
        self.entry.set_text("")
        self.response.set_text(f"Preview request: {request_text}")
        self.response.get_style_context().remove_class("stub-text")
        add_class(self.response, "status-text")
        self.waveform.set_active(True)
        # Send to brain on a background thread so the UI stays responsive.
        import threading as _threading
        thread = _threading.Thread(
            target=self._run_chat, args=(request_text,), daemon=True
        )
        thread.start()

    def _run_chat(self, text):
        """Background thread: brain call, results posted back to UI."""
        from gi.repository import GLib
        GLib.idle_add(self.application._set_orb_state, "thinking")
        reply, action_summary = self.application.brain.process_chat(text)
        if not reply:
            GLib.idle_add(self._show_chat_error, "No response from AI.")
            return
        GLib.idle_add(self.application._set_orb_state, "speaking")
        spoken = self.application.brain.speak(reply)
        result = reply
        if action_summary:
            result += "\n\n" + action_summary
        if not spoken:
            result += "\n\nSpeech playback is unavailable."
        GLib.idle_add(self.show_ai_response, text, result)
        GLib.idle_add(
            self.application._set_orb_state,
            "sleeping" if spoken else "error",
        )

    def _show_chat_error(self, message):
        self.response.set_text(message)
        self.response.get_style_context().remove_class("status-text")
        add_class(self.response, "stub-text")
        self.waveform.set_active(False)
        self.application._set_orb_state("error")

    def show_ai_response(self, user_text, reply):
        self.response.set_text(reply)
        self.response.get_style_context().remove_class("stub-text")
        add_class(self.response, "status-text")
        self.waveform.set_active(False)
        # Update the intro label to show the last user query
        for child in self.get_children():
            if isinstance(child, Gtk.Box):
                for sub in child.get_children():
                    if isinstance(sub, Gtk.Label) and "explore" in (sub.get_text() or ""):
                        sub.set_text(f"DarkOS AI — last query: {user_text[:40]}")

    def show_stub(self, message):
        self.response.set_text(message)
        self.response.get_style_context().remove_class("status-text")
        add_class(self.response, "stub-text")

    def refresh_system(self):
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
