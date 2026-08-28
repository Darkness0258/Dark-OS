#!/usr/bin/env python3
"""DarkOS Clock — local time + world clocks, alarms, timer, stopwatch.

One ticking GLib timeout drives all four tabs. Alarms and world-clock
timezones persist as JSON under ~/.local/share/darkos/; timer and
stopwatch are session-only (resetting them on app close is standard
behavior for these, not a gap).
"""
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Clock"
WM_CLASS = "darkos-clock"


def data_file(name):
    darkos_dir = os.path.join(GLib.get_user_data_dir(), "darkos")
    os.makedirs(darkos_dir, exist_ok=True)
    return os.path.join(darkos_dir, name)


def load_json(name, default):
    path = data_file(name)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(name, data):
    try:
        with open(data_file(name), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def format_hms(total_seconds):
    total_seconds = max(0, int(total_seconds))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class ClockWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Clock")
        self.set_default_size(480, 520)
        add_class(self, "app-window")
        self.app = app

        self.world_clocks = load_json("clock-worldclocks.json", [])
        self.alarms = load_json("clock-alarms.json", [])
        self._fired_today = set()

        self.timer_total = 0
        self.timer_remaining = 0
        self.timer_running = False

        self.stopwatch_elapsed = 0.0
        self.stopwatch_running = False
        self.stopwatch_started_at = None
        self.laps = []

        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        notebook.append_page(self._build_clock_tab(), Gtk.Label(label="Clock"))
        notebook.append_page(self._build_alarms_tab(), Gtk.Label(label="Alarms"))
        notebook.append_page(self._build_timer_tab(), Gtk.Label(label="Timer"))
        notebook.append_page(self._build_stopwatch_tab(), Gtk.Label(label="Stopwatch"))
        self.add(notebook)

        GLib.timeout_add(1000, self._tick)
        self._tick()

    # -- Clock tab -----------------------------------------------------------
    def _build_clock_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(24)

        self.time_label = Gtk.Label(label="")
        self.time_label.get_style_context().add_class("path-crumb-current")
        self.time_label.set_markup("<span size='48000'>--:--:--</span>")
        self.date_label = Gtk.Label(label="")
        box.pack_start(self.time_label, False, False, 12)
        box.pack_start(self.date_label, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 8)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.pack_start(Gtk.Label(label="World Clocks", xalign=0), True, True, 0)
        self.tz_entry = Gtk.Entry()
        self.tz_entry.set_placeholder_text("e.g. Asia/Karachi")
        self.tz_entry.set_width_chars(18)
        self.tz_entry.connect("activate", self._add_world_clock)
        header.pack_start(self.tz_entry, False, False, 4)
        header.pack_start(make_icon_button("list-add-symbolic", "Add", self._add_world_clock), False, False, 0)
        box.pack_start(header, False, False, 0)

        self.world_list = Gtk.ListBox()
        self.world_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.world_list, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.world_list)
        box.pack_start(scroller, True, True, 0)
        return box

    def _add_world_clock(self, *_):
        name = self.tz_entry.get_text().strip()
        if not name:
            return
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            self._toast(f'Unknown timezone "{name}" — use IANA names like "Europe/London"')
            return
        if name not in self.world_clocks:
            self.world_clocks.append(name)
            save_json("clock-worldclocks.json", self.world_clocks)
            self._rebuild_world_list()
        self.tz_entry.set_text("")

    def _remove_world_clock(self, name):
        def _remove(*_):
            if name in self.world_clocks:
                self.world_clocks.remove(name)
                save_json("clock-worldclocks.json", self.world_clocks)
                self._rebuild_world_list()
        return _remove

    def _rebuild_world_list(self):
        for child in list(self.world_list.get_children()):
            self.world_list.remove(child)
        for name in self.world_clocks:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            add_class(hbox, "sidebar-row")
            hbox.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            time_lbl = Gtk.Label(label="--:--")
            hbox.pack_start(time_lbl, False, False, 0)
            hbox.pack_start(make_icon_button("window-close-symbolic", "Remove", self._remove_world_clock(name), Gtk.IconSize.MENU), False, False, 0)
            row.add(hbox)
            row.time_label = time_lbl
            row.tz_name = name
            self.world_list.add(row)
        self.world_list.show_all()

    # -- Alarms tab ------------------------------------------------------------
    def _build_alarms_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        toolbar.pack_start(Gtk.Label(label="Alarms", xalign=0), True, True, 8)
        toolbar.pack_start(make_icon_button("list-add-symbolic", "Add alarm", self._add_alarm), False, False, 0)
        box.pack_start(toolbar, False, False, 0)

        self.alarm_list = Gtk.ListBox()
        self.alarm_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.alarm_list, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.alarm_list)
        box.pack_start(scroller, True, True, 0)
        self._rebuild_alarm_list()
        return box

    def _add_alarm(self, *_):
        dialog = Gtk.Dialog(title="Add Alarm", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_border_width(12)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hour_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        minute_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
        now = datetime.now()
        hour_spin.set_value(now.hour)
        minute_spin.set_value(now.minute)
        row.pack_start(hour_spin, False, False, 0)
        row.pack_start(Gtk.Label(label=":"), False, False, 0)
        row.pack_start(minute_spin, False, False, 0)
        label_entry = Gtk.Entry()
        label_entry.set_placeholder_text("Label (optional)")
        box.pack_start(row, False, False, 4)
        box.pack_start(label_entry, False, False, 4)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            self.alarms.append({
                "hour": int(hour_spin.get_value()),
                "minute": int(minute_spin.get_value()),
                "label": label_entry.get_text().strip() or "Alarm",
                "enabled": True,
            })
            save_json("clock-alarms.json", self.alarms)
            self._rebuild_alarm_list()
        dialog.destroy()

    def _toggle_alarm(self, idx):
        def _toggle(switch, state):
            self.alarms[idx]["enabled"] = state
            save_json("clock-alarms.json", self.alarms)
        return _toggle

    def _remove_alarm(self, idx):
        def _remove(*_):
            if 0 <= idx < len(self.alarms):
                self.alarms.pop(idx)
                save_json("clock-alarms.json", self.alarms)
                self._rebuild_alarm_list()
        return _remove

    def _rebuild_alarm_list(self):
        for child in list(self.alarm_list.get_children()):
            self.alarm_list.remove(child)
        for idx, alarm in enumerate(self.alarms):
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            add_class(hbox, "sidebar-row")
            text = f'{alarm["hour"]:02d}:{alarm["minute"]:02d} — {alarm["label"]}'
            hbox.pack_start(Gtk.Label(label=text, xalign=0), True, True, 0)
            switch = Gtk.Switch()
            switch.set_active(alarm.get("enabled", True))
            switch.connect("state-set", self._toggle_alarm(idx))
            hbox.pack_start(switch, False, False, 0)
            hbox.pack_start(make_icon_button("window-close-symbolic", "Remove", self._remove_alarm(idx), Gtk.IconSize.MENU), False, False, 0)
            row.add(hbox)
            self.alarm_list.add(row)
        self.alarm_list.show_all()

    # -- Timer tab -------------------------------------------------------------
    def _build_timer_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(24)
        self.timer_label = Gtk.Label(label="00:00")
        self.timer_label.set_markup("<span size='36000'>00:00</span>")
        box.pack_start(self.timer_label, False, False, 12)

        setup = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        self.timer_min = Gtk.SpinButton.new_with_range(0, 180, 1)
        self.timer_min.set_value(5)
        self.timer_sec = Gtk.SpinButton.new_with_range(0, 59, 1)
        setup.pack_start(self.timer_min, False, False, 0)
        setup.pack_start(Gtk.Label(label="min"), False, False, 0)
        setup.pack_start(self.timer_sec, False, False, 0)
        setup.pack_start(Gtk.Label(label="sec"), False, False, 0)
        box.pack_start(setup, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        self.timer_start_btn = make_icon_button("media-playback-start-symbolic", "Start", self._timer_toggle)
        controls.pack_start(self.timer_start_btn, False, False, 0)
        controls.pack_start(make_icon_button("view-refresh-symbolic", "Reset", self._timer_reset), False, False, 0)
        box.pack_start(controls, False, False, 0)
        return box

    def _timer_toggle(self, *_):
        if not self.timer_running:
            if self.timer_remaining <= 0:
                self.timer_remaining = int(self.timer_min.get_value()) * 60 + int(self.timer_sec.get_value())
            if self.timer_remaining <= 0:
                return
            self.timer_running = True
            self.timer_start_btn.set_tooltip_text("Pause")
        else:
            self.timer_running = False
            self.timer_start_btn.set_tooltip_text("Start")

    def _timer_reset(self, *_):
        self.timer_running = False
        self.timer_remaining = 0
        self.timer_label.set_markup("<span size='36000'>00:00</span>")

    # -- Stopwatch tab ---------------------------------------------------------
    def _build_stopwatch_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(24)
        self.stopwatch_label = Gtk.Label(label="00:00")
        self.stopwatch_label.set_markup("<span size='36000'>00:00</span>")
        box.pack_start(self.stopwatch_label, False, False, 12)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        self.sw_start_btn = make_icon_button("media-playback-start-symbolic", "Start", self._sw_toggle)
        controls.pack_start(self.sw_start_btn, False, False, 0)
        controls.pack_start(make_icon_button("media-record-symbolic", "Lap", self._sw_lap), False, False, 0)
        controls.pack_start(make_icon_button("view-refresh-symbolic", "Reset", self._sw_reset), False, False, 0)
        box.pack_start(controls, False, False, 0)

        self.lap_list = Gtk.ListBox()
        self.lap_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.lap_list, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.lap_list)
        box.pack_start(scroller, True, True, 0)
        return box

    def _sw_toggle(self, *_):
        if not self.stopwatch_running:
            self.stopwatch_started_at = time.monotonic() - self.stopwatch_elapsed
            self.stopwatch_running = True
            self.sw_start_btn.set_tooltip_text("Pause")
        else:
            self.stopwatch_elapsed = time.monotonic() - self.stopwatch_started_at
            self.stopwatch_running = False
            self.sw_start_btn.set_tooltip_text("Start")

    def _sw_lap(self, *_):
        if not self.stopwatch_running:
            return
        elapsed = time.monotonic() - self.stopwatch_started_at
        self.laps.insert(0, elapsed)
        row = Gtk.ListBoxRow()
        label = Gtk.Label(label=f"Lap {len(self.laps)} — {format_hms(elapsed)}", xalign=0)
        add_class(label, "sidebar-row")
        row.add(label)
        self.lap_list.prepend(row)
        row.show_all()

    def _sw_reset(self, *_):
        self.stopwatch_running = False
        self.stopwatch_elapsed = 0.0
        self.laps = []
        self.stopwatch_label.set_markup("<span size='36000'>00:00</span>")
        for child in list(self.lap_list.get_children()):
            self.lap_list.remove(child)

    # -- ticking ---------------------------------------------------------------
    def _toast(self, text):
        notif = Gio.Notification.new("DarkOS Clock")
        notif.set_body(text)
        self.app.send_notification(None, notif)

    def _tick(self):
        now = datetime.now()
        self.time_label.set_markup(f"<span size='48000'>{now.strftime('%H:%M:%S')}</span>")
        self.date_label.set_text(now.strftime("%A, %d %B %Y"))

        for row in self.world_list.get_children():
            if hasattr(row, "tz_name"):
                try:
                    tz_now = datetime.now(ZoneInfo(row.tz_name))
                    row.time_label.set_text(tz_now.strftime("%H:%M"))
                except ZoneInfoNotFoundError:
                    row.time_label.set_text("?")

        today_key = now.strftime("%Y-%m-%d")
        for alarm in self.alarms:
            if not alarm.get("enabled"):
                continue
            fire_id = f'{today_key}-{alarm["hour"]}-{alarm["minute"]}'
            if now.hour == alarm["hour"] and now.minute == alarm["minute"] and fire_id not in self._fired_today:
                self._fired_today.add(fire_id)
                self._toast(alarm["label"])

        if self.timer_running:
            self.timer_remaining -= 1
            if self.timer_remaining <= 0:
                self.timer_remaining = 0
                self.timer_running = False
                self._toast("Timer finished")
            self.timer_label.set_markup(f"<span size='36000'>{format_hms(self.timer_remaining)}</span>")

        if self.stopwatch_running:
            elapsed = time.monotonic() - self.stopwatch_started_at
            self.stopwatch_label.set_markup(f"<span size='36000'>{format_hms(elapsed)}</span>")

        return True


def build_window(app):
    return ClockWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
