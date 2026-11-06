"""Settings > Display page.

Choosing something never changes the screen by itself: pick, press Apply, and
the change goes live with a "Keep these settings?" banner and a countdown.
Keep saves it (monitors.conf); Revert, the countdown reaching zero, or closing
Settings puts the previous mode back. All hyprctl calls run on worker threads.
"""
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from darkos_shell import display  # noqa: E402
from darkos_shell.app_kit import add_class  # noqa: E402

COUNTDOWN_SECONDS = 15


def _label(text, css=None, wrap=True):
    label = Gtk.Label(label=text)
    label.set_xalign(0.0)
    label.set_line_wrap(wrap)
    if css:
        add_class(label, css)
    return label


class MonitorCard(Gtk.Box):
    """One screen: four dropdowns and Apply/Reset. Knows nothing about hyprctl."""

    def __init__(self, monitor, on_apply):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(self, "card")
        self.set_border_width(14)
        self.monitor = monitor
        self._on_apply = on_apply
        self._loading = False
        self._resolutions = []
        self._rates = []
        self._scales = []

        tag = "  \u00b7  main" if monitor.focused else ""
        self.pack_start(_label(monitor.description, "section-title"), False, False, 0)
        self.pack_start(_label(f"{monitor.name}{tag}", "caption", wrap=False), False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.res_combo = Gtk.ComboBoxText()
        self.rate_combo = Gtk.ComboBoxText()
        self.scale_combo = Gtk.ComboBoxText()
        self.turn_combo = Gtk.ComboBoxText()
        for row, (text, combo) in enumerate((("Resolution", self.res_combo), ("Refresh rate", self.rate_combo),
                                             ("Scale", self.scale_combo), ("Orientation", self.turn_combo))):
            caption = _label(text, "body-muted", wrap=False)
            combo.get_accessible().set_name(f"{monitor.name} {text}")
            grid.attach(caption, 0, row, 1, 1)
            grid.attach(combo, 1, row, 1, 1)
        self.pack_start(grid, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        self.apply_btn = Gtk.Button(label="Apply")
        add_class(self.apply_btn, "action-button")
        add_class(self.apply_btn, "primary")
        self.apply_btn.connect("clicked", lambda *_: self._on_apply(self))
        self.reset_btn = Gtk.Button(label="Reset")
        self.reset_btn.connect("clicked", lambda *_: self.load_current())
        buttons.pack_start(self.apply_btn, False, False, 0)
        buttons.pack_start(self.reset_btn, False, False, 0)
        self.pack_start(buttons, False, False, 4)

        for index, (_value, label) in enumerate(display.TRANSFORMS):
            self.turn_combo.append_text(label)
        self.res_combo.connect("changed", self._on_resolution_changed)
        for combo in (self.rate_combo, self.scale_combo, self.turn_combo):
            combo.connect("changed", lambda *_: self._sync_apply())
        self.load_current()

    # -- model <-> widgets --------------------------------------------------
    def load_current(self):
        """Show what is on screen now; Apply is off until something differs."""
        m = self.monitor
        self._loading = True
        try:
            self._resolutions = display.resolutions(m)
            self.res_combo.remove_all()
            for w, h in self._resolutions:
                self.res_combo.append_text(f"{w} \u00d7 {h}")
            current = (m.width, m.height)
            self.res_combo.set_active(self._resolutions.index(current) if current in self._resolutions else 0)
            self.turn_combo.set_active([v for v, _l in display.TRANSFORMS].index(m.transform)
                                       if m.transform in dict(display.TRANSFORMS) else 0)
            self._fill_rates(prefer=m.refresh)
            self._fill_scales(prefer=m.scale)
        finally:
            self._loading = False
        self._sync_apply()

    def _fill_rates(self, prefer=None):
        w, h = self._resolutions[self.res_combo.get_active()] if self._resolutions else (0, 0)
        self._rates = display.refresh_rates(self.monitor, w, h) or [self.monitor.current_mode()]
        self.rate_combo.remove_all()
        for mode in self._rates:
            self.rate_combo.append_text(mode.refresh_label())
        best = 0
        if prefer is not None:
            best = min(range(len(self._rates)), key=lambda i: abs(self._rates[i].refresh - prefer))
        self.rate_combo.set_active(best)

    def _fill_scales(self, prefer=None):
        w, h = self._resolutions[self.res_combo.get_active()] if self._resolutions else (1, 1)
        self._scales = display.valid_scales(w, h)
        self.scale_combo.remove_all()
        for scale in self._scales:
            self.scale_combo.append_text(display.scale_label(scale))
        pick = 0
        if prefer is not None:
            for i, scale in enumerate(self._scales):
                if abs(scale - prefer) <= display.SCALE_TOLERANCE:
                    pick = i
        self.scale_combo.set_active(pick)

    def _on_resolution_changed(self, _combo):
        if self._loading:
            return
        self._loading = True
        try:
            self._fill_rates(prefer=self.monitor.refresh)
            self._fill_scales(prefer=self.monitor.scale)
        finally:
            self._loading = False
        self._sync_apply()

    def selection(self):
        """(Mode, scale, transform) currently chosen in the dropdowns."""
        mode = self._rates[self.rate_combo.get_active()]
        scale = self._scales[self.scale_combo.get_active()]
        transform = display.TRANSFORMS[self.turn_combo.get_active()][0]
        return mode, scale, transform

    def differs(self):
        try:
            mode, scale, transform = self.selection()
        except IndexError:
            return False
        m = self.monitor
        return not (mode.width == m.width and mode.height == m.height
                    and abs(mode.refresh - m.refresh) <= display.REFRESH_TOLERANCE_HZ
                    and abs(scale - m.scale) <= display.SCALE_TOLERANCE and transform == m.transform)

    def _sync_apply(self):
        if not self._loading:
            changed = self.differs()
            self.apply_btn.set_sensitive(changed)
            self.reset_btn.set_sensitive(changed)

    def set_busy(self, busy):
        for widget in (self.res_combo, self.rate_combo, self.scale_combo, self.turn_combo,
                       self.apply_btn, self.reset_btn):
            widget.set_sensitive(not busy)
        if not busy:
            self._sync_apply()


class DisplayPage(Gtk.Box):
    def __init__(self, run=display.default_run, persist=None, countdown=COUNTDOWN_SECONDS,
                 sleep=time.sleep):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.run = run
        self.persist = persist or display.persist_rule
        self.countdown = countdown
        self.sleep = sleep
        self.cards = {}
        self.pending = None        # the change awaiting Keep/Revert
        self._tick_id = None
        self._generation = 0
        self._closed = False
        self._note = ""           # outcome message that must outlive the re-read
        self.pack_start(_label("Display", "title"), False, False, 0)
        self.status = _label("", "body-muted")
        self.pack_start(self.status, False, False, 0)

        self.banner = Gtk.Box(spacing=10)
        add_class(self.banner, "card")
        self.banner.set_border_width(12)
        self.banner_label = _label("", "lead")
        self.keep_btn = Gtk.Button(label="Keep changes")
        add_class(self.keep_btn, "action-button")
        add_class(self.keep_btn, "primary")
        self.keep_btn.connect("clicked", lambda *_: self.keep())
        self.revert_btn = Gtk.Button(label="Revert")
        self.revert_btn.connect("clicked", lambda *_: self.revert("Reverted."))
        self.banner.pack_start(self.banner_label, True, True, 0)
        self.banner.pack_start(self.revert_btn, False, False, 0)
        self.banner.pack_start(self.keep_btn, False, False, 0)
        self.banner.set_no_show_all(True)
        self.banner.hide()
        self.pack_start(self.banner, False, False, 0)

        self.cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.pack_start(self.cards_box, False, False, 0)
        self.connect("destroy", self._on_destroy)

    # -- loading ------------------------------------------------------------
    def refresh(self, note=""):
        """(Re)read the monitors off the main thread. Safe to call repeatedly.

        `note` (e.g. "Saved." / "Reverted.") stays on screen after the cards are
        rebuilt; without it the re-read would overwrite the outcome the user
        needs to read.
        """
        if self.pending:
            return
        self._note = note
        self._generation += 1
        generation = self._generation
        if not note:
            self.status.set_text("Looking for screens...")

        def work():
            try:
                monitors, error = display.list_monitors(self.run), ""
            except display.DisplayError as exc:
                monitors, error = [], str(exc)
            GLib.idle_add(self._show_monitors, generation, monitors, error)

        threading.Thread(target=work, daemon=True).start()

    def _show_monitors(self, generation, monitors, error):
        if self._closed or generation != self._generation or self.pending:
            return False
        for child in self.cards_box.get_children():
            self.cards_box.remove(child)
        self.cards = {}
        if error:
            self.status.set_text(error)
        elif not monitors:
            self.status.set_text("No screens were reported.")
        else:
            self.status.set_text(self._note or "Changes go live when you press Apply, and you get a chance to undo them.")
            for monitor in monitors:
                card = MonitorCard(monitor, self._on_apply)
                self.cards[monitor.name] = card
                self.cards_box.pack_start(card, False, False, 0)
            self.cards_box.show_all()
        return False

    # -- applying -----------------------------------------------------------
    def _on_apply(self, card):
        if self.pending:
            return
        try:
            mode, scale, transform = card.selection()
            new_rule, old_rule = display.plan_change(card.monitor, mode, scale, transform)
        except (ValueError, IndexError) as exc:
            self.status.set_text(f"Cannot apply that: {exc}")
            return
        self._note = ""
        for each in self.cards.values():
            each.set_busy(True)
        self.status.set_text("Applying...")

        def work():
            ok, message = display.apply_rule(new_rule, self.run, sleep=self.sleep)
            if not ok:
                display.apply_rule(old_rule, self.run, sleep=self.sleep)   # best effort: undo a half-applied change
            GLib.idle_add(self._after_apply, card, ok, message, new_rule, old_rule)

        threading.Thread(target=work, daemon=True).start()

    def _after_apply(self, card, ok, message, new_rule, old_rule):
        if self._closed:
            return False
        if not ok:
            self.status.set_text(f"Not applied: {message}")
            for each in self.cards.values():
                each.set_busy(False)
            return False
        self.pending = {"name": card.monitor.name, "new": new_rule, "old": old_rule,
                        "remaining": self.countdown}
        self._show_banner()
        self._tick_id = GLib.timeout_add(1000, self._tick)
        return False

    def _show_banner(self):
        remaining = self.pending["remaining"]
        self.banner_label.set_text(f"Keep these display settings?  Reverting in {remaining} s")
        # show_all() does nothing on a no_show_all widget, so show the parts by hand.
        for part in (self.banner_label, self.revert_btn, self.keep_btn):
            part.show()
        self.banner.show()
        self.status.set_text("")

    def _tick(self):
        if not self.pending:
            self._tick_id = None
            return False
        self.pending["remaining"] -= 1
        if self.pending["remaining"] <= 0:
            self._tick_id = None
            self.revert("No answer, so the previous display settings were restored.")
            return False
        self._show_banner()
        return True

    def _end_pending(self):
        pending, self.pending = self.pending, None
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        self.banner.hide()
        return pending

    def keep(self):
        pending = self._end_pending()
        if not pending:
            return
        try:
            self.persist(pending["new"])
            note = "Saved. This will be used every time you log in."
        except (OSError, ValueError) as exc:
            note = f"It is applied now, but could not be saved for next login: {exc}"
        self.status.set_text(note)
        self.refresh(note=note)

    def revert(self, message):
        pending = self._end_pending()
        if not pending:
            return
        self.status.set_text("Restoring...")

        def work():
            ok, why = display.apply_rule(pending["old"], self.run, sleep=self.sleep)
            GLib.idle_add(self._after_revert, message if ok else f"Could not restore automatically: {why}")

        threading.Thread(target=work, daemon=True).start()

    def _after_revert(self, message):
        if self._closed:
            return False
        self.status.set_text(message)
        self.refresh(note=message)
        return False

    def _on_destroy(self, *_):
        self._closed = True
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        pending, self.pending = self.pending, None
        if pending:
            # Settings is closing with an unanswered change: put the screen back.
            # Not a daemon thread, so the process waits for it before exiting.
            threading.Thread(target=display.apply_rule, args=(pending["old"], self.run),
                             kwargs={"sleep": self.sleep}, daemon=False).start()
