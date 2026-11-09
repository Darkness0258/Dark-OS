"""Settings > Power & sleep page: when to lock and suspend, on AC and on battery.

Choosing a timing saves it and applies it straight away (a worker thread writes
hypridle's config and restarts it), because the choice is harmless and
reversible. Reading the power source also happens off the GTK thread.
"""
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from darkos_shell import power, user_settings  # noqa: E402
from darkos_shell.app_kit import add_class  # noqa: E402

SECTION_TITLES = {"ac": "On AC power", "battery": "On battery"}


def _label(text, css=None, wrap=True):
    label = Gtk.Label(label=text)
    label.set_xalign(0.0)
    label.set_line_wrap(wrap)
    if css:
        add_class(label, css)
    return label


class _Section(Gtk.Box):
    """The two dropdowns for one power source."""

    def __init__(self, source, on_change):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(self, "card")
        self.set_border_width(14)
        self.source = source
        self._on_change = on_change
        self._loading = False
        self.pack_start(_label(SECTION_TITLES[source], "section-title"), False, False, 0)
        lock_key, suspend_key = power.keys_for(source)
        self.lock_choices = user_settings.CHOICES[lock_key]
        self.suspend_choices = user_settings.CHOICES[suspend_key]
        self.lock_combo = self._combo("Lock the screen after", self.lock_choices)
        self.suspend_combo = self._combo("Suspend after", self.suspend_choices)
        self.note = _label("", "caption")
        self.note.set_no_show_all(True)
        self.pack_start(self.note, False, False, 0)
        for combo in (self.lock_combo, self.suspend_combo):
            combo.connect("changed", lambda *_: self._changed())

    def _combo(self, caption, choices):
        row = Gtk.Box(spacing=12)
        label = _label(caption, "body-muted", wrap=False)
        label.set_size_request(190, -1)
        combo = Gtk.ComboBoxText()
        combo.get_accessible().set_name(f"{SECTION_TITLES[self.source]}: {caption}")
        for minutes in choices:
            combo.append_text(power.minutes_label(minutes))
        row.pack_start(label, False, False, 0)
        row.pack_start(combo, False, False, 0)
        self.pack_start(row, False, False, 0)
        return combo

    def reveal(self, visible):
        """Show or hide the whole card. show_all() skips a no_show_all widget AND everything
        inside it, so showing it takes a deliberate show_all() with the flag lifted."""
        if visible:
            self.set_no_show_all(False)
            self.show_all()
            self.set_no_show_all(True)
            if not self.note.get_text():
                self.note.hide()
        else:
            self.hide()

    def load(self, lock, suspend, note=""):
        self._loading = True
        try:
            self.lock_combo.set_active(self.lock_choices.index(lock))
            self.suspend_combo.set_active(self.suspend_choices.index(suspend))
        finally:
            self._loading = False
        self.show_note(note)

    def values(self):
        return (self.lock_choices[self.lock_combo.get_active()],
                self.suspend_choices[self.suspend_combo.get_active()])

    def show_note(self, text):
        self.note.set_text(text)
        if text:
            self.note.show()
        else:
            self.note.hide()

    def _changed(self):
        if not self._loading:
            self._on_change(self)


class PowerPage(Gtk.Box):
    def __init__(self, load=None, save=None, detect=None, apply=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.load_settings = load or user_settings.load_settings
        self.save_settings = save or user_settings.save_settings
        self.detect = detect or power.detect
        self.apply = apply or power.apply_idle_config
        self._closed = False
        self._generation = 0
        self.state = None
        self.pack_start(_label("Power & sleep", "title"), False, False, 0)
        self.current = _label("", "lead")
        self.pack_start(self.current, False, False, 0)
        self.status = _label("", "body-muted")
        self.pack_start(self.status, False, False, 0)
        self.sections = {source: _Section(source, self._on_section_changed) for source in power.SOURCES}
        for section in self.sections.values():
            section.set_no_show_all(True)
            self.pack_start(section, False, False, 0)
        self.pack_start(_label(
            "DarkOS always locks the screen before it sleeps. It does not turn the display off "
            "by itself while locked, because that has left some systems on a black screen.",
            "caption"), False, False, 0)
        self.connect("destroy", lambda *_: setattr(self, "_closed", True))
        self._fill()

    # -- loading ------------------------------------------------------------
    def _fill(self):
        """Show the saved values immediately; the detected source arrives from a thread."""
        settings = self.load_settings()
        for source, section in self.sections.items():
            lock, suspend, notes = power.normalize(*power.timings_for(settings, source))
            section.load(lock, suspend, notes[0] if notes else "")
            section.reveal(True)
        self.sections["battery"].reveal(False)   # until we know this computer has one

    def refresh(self):
        self._generation += 1
        generation = self._generation
        self.current.set_text("Checking the power source...")

        def work():
            state = self.detect()
            GLib.idle_add(self._show_state, generation, state)

        threading.Thread(target=work, daemon=True).start()

    def _show_state(self, generation, state):
        if self._closed or generation != self._generation:
            return False
        self.state = state
        self._fill()
        if state.has_battery:
            self.sections["battery"].reveal(True)
            self.current.set_text("Right now: on AC power." if state.source == "ac"
                                  else "Right now: running on battery.")
        else:
            self.sections["battery"].reveal(False)
            self.current.set_text("This computer has no battery, so only the AC timings apply.")
        return False

    # -- changing -----------------------------------------------------------
    def _on_section_changed(self, section):
        lock, suspend = section.values()
        lock, suspend, notes = power.normalize(lock, suspend)
        section.load(lock, suspend, notes[0] if notes else "")   # shows the correction, if any
        lock_key, suspend_key = power.keys_for(section.source)
        settings = self.load_settings()
        settings[lock_key] = lock
        settings[suspend_key] = suspend
        if not self.save_settings(settings):
            self.status.set_text("Could not save this setting.")
            return
        self.status.set_text("Saved.")
        threading.Thread(target=self._apply_worker, args=(settings, section.source), daemon=True).start()

    def _apply_worker(self, settings, changed_source):
        try:
            result = self.apply(settings)          # applies the source that is in use right now
            message = ("Saved and applied." if result.source == changed_source
                       else f"Saved. It applies when the computer is {'on battery' if changed_source == 'battery' else 'plugged in'}.")
        except OSError as exc:
            message = f"Saved, but could not update the idle settings: {exc}"
        GLib.idle_add(self._set_status, message)

    def _set_status(self, message):
        if not self._closed:
            self.status.set_text(message)
        return False
