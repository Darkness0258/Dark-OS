#!/usr/bin/env python3
"""DarkOS Calendar — month view (stock Gtk.Calendar) + per-day text events.

Events persist as JSON at ~/.local/share/darkos/calendar-events.json,
keyed by ISO date. Deliberately not a full recurring-event/reminder system —
that's a real follow-up feature, this is a straightforward "what's on this
day" calendar.
"""
import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Calendar"
WM_CLASS = "darkos-calendar"


def data_path():
    base = GLib.get_user_data_dir()  # ~/.local/share
    darkos_dir = os.path.join(base, "darkos")
    os.makedirs(darkos_dir, exist_ok=True)
    return os.path.join(darkos_dir, "calendar-events.json")


def load_events():
    path = data_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_events(events):
    try:
        with open(data_path(), "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2, sort_keys=True)
    except OSError:
        pass


def iso_date(year, month_0indexed, day):
    return f"{year:04d}-{month_0indexed + 1:02d}-{day:02d}"


class CalendarWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Calendar")
        self.set_default_size(760, 480)
        add_class(self, "app-window")

        self.events = load_events()

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(body)

        cal_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cal_box.set_border_width(16)
        self.calendar = Gtk.Calendar()
        self.calendar.connect("day-selected", self._on_day_selected)
        self.calendar.connect("month-changed", self._on_month_changed)
        self.calendar.connect("day-selected-double-click", lambda *_: self._add_event())
        cal_box.pack_start(self.calendar, False, False, 0)

        today_btn = Gtk.Button(label="Today")
        add_class(today_btn, "icon-button")
        today_btn.connect("clicked", self._go_today)
        cal_box.pack_start(today_btn, False, False, 0)
        body.pack_start(cal_box, False, False, 0)

        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        side.set_hexpand(True)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        self.day_label = Gtk.Label(label="", xalign=0)
        self.day_label.set_margin_start(8)
        toolbar.pack_start(self.day_label, True, True, 0)
        toolbar.pack_start(make_icon_button("list-add-symbolic", "Add event", lambda *_: self._add_event()), False, False, 0)
        side.pack_start(toolbar, False, False, 0)

        self.event_list = Gtk.ListBox()
        self.event_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.event_list, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.event_list)
        side.pack_start(scroller, True, True, 0)
        body.pack_start(side, True, True, 0)

        self._mark_current_month()
        self._refresh_day()

    # -- date helpers ------------------------------------------------------
    def _selected_iso(self):
        y, m, d = self.calendar.get_date()
        return iso_date(y, m, d)

    def _go_today(self, *_):
        today = GLib.DateTime.new_now_local()
        self.calendar.select_month(today.get_month() - 1, today.get_year())
        self.calendar.select_day(today.get_day_of_month())
        self._mark_current_month()
        self._refresh_day()

    def _mark_current_month(self):
        self.calendar.clear_marks()
        y, m, _d = self.calendar.get_date()
        prefix = f"{y:04d}-{m + 1:02d}-"
        for key in self.events:
            if key.startswith(prefix) and self.events[key]:
                try:
                    day = int(key.split("-")[2])
                    self.calendar.mark_day(day)
                except (ValueError, IndexError):
                    continue

    def _on_month_changed(self, _cal):
        self._mark_current_month()

    def _on_day_selected(self, _cal):
        self._refresh_day()

    # -- event list ----------------------------------------------------------
    def _refresh_day(self):
        for child in list(self.event_list.get_children()):
            self.event_list.remove(child)
        iso = self._selected_iso()
        y, m, d = self.calendar.get_date()
        weekday = GLib.DateTime.new_local(y, m + 1, d, 0, 0, 0).format("%A, %d %B %Y")
        self.day_label.set_text(weekday)

        for idx, text in enumerate(self.events.get(iso, [])):
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            add_class(hbox, "sidebar-row")
            label = Gtk.Label(label=text, xalign=0)
            label.set_line_wrap(True)
            hbox.pack_start(label, True, True, 0)
            remove_btn = make_icon_button("window-close-symbolic", "Remove", self._make_remover(iso, idx), Gtk.IconSize.MENU)
            hbox.pack_start(remove_btn, False, False, 0)
            row.add(hbox)
            self.event_list.add(row)
        self.event_list.show_all()

    def _make_remover(self, iso, idx):
        def _remove(*_):
            events = self.events.get(iso, [])
            if 0 <= idx < len(events):
                events.pop(idx)
                if not events:
                    self.events.pop(iso, None)
                save_events(self.events)
                self._mark_current_month()
                self._refresh_day()
        return _remove

    def _add_event(self):
        dialog = Gtk.Dialog(title="Add Event", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_activates_default(True)
        entry.set_placeholder_text("What's happening?")
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.pack_start(entry, True, True, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            text = entry.get_text().strip()
            if text:
                iso = self._selected_iso()
                self.events.setdefault(iso, []).append(text)
                save_events(self.events)
                self._mark_current_month()
                self._refresh_day()
        dialog.destroy()


def build_window(app):
    return CalendarWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
