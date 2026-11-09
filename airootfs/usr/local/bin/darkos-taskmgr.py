#!/usr/bin/env python3
"""DarkOS Task Manager: what is running, what is using it, and an End Task that works.

Opens with Ctrl+Shift+Esc. The process list is read from /proc on a worker
thread (never `ps`, never the GTK thread), and only while the window is on
screen and updates are not paused; a minimized Task Manager costs nothing.
The reading and the rules (who may end what) live in darkos_shell/procinfo.py.
"""
import os
import sys
import threading
import traceback

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from darkos_shell import procinfo  # noqa: E402
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.TaskManager"
WM_CLASS = "darkos-taskmgr"
INTERVAL_MS = 2000
FIRST_REFRESH_MS = 600   # the first sample has no baseline, so take a second one quickly

(COL_PID, COL_NAME, COL_CPU, COL_RSS, COL_USER, COL_THREADS, COL_STATE, COL_CMD,
 COL_CPU_TEXT, COL_MEM_TEXT) = range(10)

STATES = {"R": "Running", "S": "Sleeping", "D": "Waiting", "T": "Stopped", "t": "Stopped",
          "Z": "Zombie", "I": "Idle", "X": "Dead"}


def _label(text, css=None, xalign=0.0):
    label = Gtk.Label(label=text)
    label.set_xalign(xalign)
    if css:
        add_class(label, css)
    return label


class TaskManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, app, sampler=None, killer=None, my_uid=None, interval_ms=INTERVAL_MS):
        super().__init__(application=app, title="Task Manager")
        add_class(self, "app-window")
        self.sampler = sampler or procinfo.Sampler()
        self.killer = killer or procinfo.end_task
        self.my_uid = os.getuid() if my_uid is None else my_uid
        self.interval_ms = interval_ms
        self.procs = {}       # pid -> procinfo.Proc (the source of truth for rules)
        self.iters = {}       # pid -> Gtk.TreeIter in the base store (iters persist)
        self.snapshot = None
        self.timer_id = None
        self._quick_id = None   # the one-shot second sample after opening
        self.paused = False
        self.show_all_users = False
        self._busy = False
        self._destroyed = False
        self.set_default_size(880, 620)
        self.set_position(Gtk.WindowPosition.CENTER)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(14)
        self.add(root)
        root.pack_start(self._build_summary(), False, False, 0)
        root.pack_start(self._build_toolbar(), False, False, 0)
        root.pack_start(self._build_table(), True, True, 0)
        self.status = _label("", "caption")
        root.pack_start(self.status, False, False, 0)

        self.connect("map", lambda *_: self._start_timer())
        self.connect("unmap", lambda *_: self._stop_timer())
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_key)

    # -- building -----------------------------------------------------------
    def _build_summary(self):
        row = Gtk.Box(spacing=18)
        self.cpu_label = _label("CPU", "section-title")
        self.cpu_bar = Gtk.ProgressBar()
        self.mem_label = _label("Memory", "section-title")
        self.mem_bar = Gtk.ProgressBar()
        self.count_label = _label("", "body-muted", xalign=1.0)
        for text, label, bar in (("CPU", self.cpu_label, self.cpu_bar),
                                 ("Memory", self.mem_label, self.mem_bar)):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.pack_start(label, False, False, 0)
            card.pack_start(bar, False, False, 0)
            bar.get_accessible().set_name(text)
            row.pack_start(card, True, True, 0)
        row.pack_start(self.count_label, False, False, 0)
        return row

    def _build_toolbar(self):
        bar = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search by name, PID or user  (Ctrl+F)")
        self.search.get_accessible().set_name("Search processes")
        self.search.connect("search-changed", lambda *_: self.filter.refilter())
        self.all_users_check = Gtk.CheckButton(label="All users")
        self.all_users_check.connect("toggled", self._on_all_users)
        self.pause_btn = Gtk.ToggleButton(label="Pause")
        add_class(self.pause_btn, "toggle-button")
        self.pause_btn.set_tooltip_text("Stop updating so you can read the list")
        self.pause_btn.connect("toggled", self._on_pause)
        self.force_btn = Gtk.Button(label="Force quit")
        add_class(self.force_btn, "action-button")
        add_class(self.force_btn, "destructive")
        self.force_btn.set_tooltip_text("Stops it immediately. Unsaved work in it is lost.")
        self.force_btn.connect("clicked", lambda *_: self.end_selected(force=True))
        self.end_btn = Gtk.Button(label="End task")
        add_class(self.end_btn, "action-button")
        self.end_btn.set_tooltip_text("Asks it to quit, like closing its window  (Delete)")
        self.end_btn.connect("clicked", lambda *_: self.end_selected(force=False))
        bar.pack_start(self.search, True, True, 0)
        for widget in (self.all_users_check, self.pause_btn, self.force_btn, self.end_btn):
            bar.pack_start(widget, False, False, 0)
        self.force_btn.set_sensitive(False)
        self.end_btn.set_sensitive(False)
        return bar

    def _build_table(self):
        self.store = Gtk.ListStore(int, str, float, int, str, int, str, str, str, str)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.sorted = Gtk.TreeModelSort(model=self.filter)
        self.tree = Gtk.TreeView(model=self.sorted)
        self.tree.get_accessible().set_name("Processes")
        add_class(self.tree, "darkos-list")  # the design system's table look (Files uses it too);
        # without it GTK draws a white grid with near-white text on Calm Dark
        self.tree.set_enable_search(False)   # we have a real search box
        self.tree.set_tooltip_column(COL_CMD)
        self.tree.set_headers_clickable(True)
        columns = (
            ("Name", COL_NAME, COL_NAME, True, 0.0),
            ("PID", COL_PID, COL_PID, False, 1.0),
            ("CPU", COL_CPU_TEXT, COL_CPU, False, 1.0),
            ("Memory", COL_MEM_TEXT, COL_RSS, False, 1.0),
            ("User", COL_USER, COL_USER, False, 0.0),
            ("Threads", COL_THREADS, COL_THREADS, False, 1.0),
            ("State", COL_STATE, COL_STATE, False, 0.0),
        )
        for title, text_col, sort_col, expand, xalign in columns:
            renderer = Gtk.CellRendererText()
            renderer.set_property("xalign", xalign)
            if expand:
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn(title, renderer, text=text_col)
            column.set_sort_column_id(sort_col)
            column.set_resizable(True)
            column.set_expand(expand)
            self.tree.append_column(column)
        self.sorted.set_sort_column_id(COL_CPU, Gtk.SortType.DESCENDING)
        selection = self.tree.get_selection()
        selection.set_mode(Gtk.SelectionMode.SINGLE)
        selection.connect("changed", lambda *_: self._sync_buttons())
        self.tree.connect("button-press-event", self._on_press)
        scroller = Gtk.ScrolledWindow()
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.tree)
        return scroller

    # -- filtering ----------------------------------------------------------
    def _visible(self, model, it, _data):
        proc = self.procs.get(model[it][COL_PID])
        if proc is None:
            return False
        if not self.show_all_users and proc.uid != self.my_uid:
            return False
        return procinfo.matches(proc, self.search.get_text())

    def _on_all_users(self, button):
        self.show_all_users = button.get_active()
        self.filter.refilter()
        self._sync_buttons()

    # -- sampling (worker thread; the timer only runs while on screen) -------
    def _start_timer(self):
        if self.timer_id is None and not self.paused and not self._destroyed:
            self.timer_id = GLib.timeout_add(self.interval_ms, self._on_timer)
            self.request_sample()
            self._quick_id = GLib.timeout_add(FIRST_REFRESH_MS, self._quick_refresh)

    def _stop_timer(self):
        # Everything that can start a sample is cancelled together, so a hidden
        # or paused window never takes a stray one.
        if self.timer_id is not None:
            GLib.source_remove(self.timer_id)
            self.timer_id = None
        if self._quick_id is not None:
            GLib.source_remove(self._quick_id)
            self._quick_id = None

    def _quick_refresh(self):
        self._quick_id = None
        self.request_sample()
        return False

    def _refresh_if_live(self):
        if self.timer_id is not None:   # not hidden, not paused
            self.request_sample()
        return False

    def _on_timer(self):
        self.request_sample()
        return True

    def request_sample(self):
        """Start one background sample unless one is already running."""
        if not self._busy and not self._destroyed:
            self._busy = True
            threading.Thread(target=self._sample_worker, daemon=True).start()
        return False   # also usable as a one-shot GLib timeout

    def _sample_worker(self):
        try:
            snapshot = self.sampler.sample()
        except Exception:  # a reader bug must not freeze the window silently
            traceback.print_exc()
            snapshot = None
        GLib.idle_add(self._sample_done, snapshot)

    def _sample_done(self, snapshot):
        self._busy = False
        if snapshot is None:
            if not self._destroyed:
                self.status.set_text("Could not read the process list.")
        elif not self._destroyed:
            self.apply_snapshot(snapshot)
        return False

    def _row(self, p):
        return [p.pid, p.name, p.cpu, p.rss, p.user, p.threads,
                STATES.get(p.state, p.state), p.cmdline,
                f"{p.cpu:.1f}%", procinfo.human_bytes(p.rss)]

    def apply_snapshot(self, snap):
        """Update rows in place (no clear/refill), so selection and scroll survive.

        Only rows whose text changed are touched, so the sort model re-sorts a
        handful of rows per tick, not the table. (Do not "freeze" it with
        UNSORTED_SORT_COLUMN_ID while inserting: GTK 3.24 segfaults in
        fill_sort_data.)
        """
        self.snapshot = snap
        present = set()
        for p in snap.procs:
            present.add(p.pid)
            self.procs[p.pid] = p
            row = self._row(p)
            it = self.iters.get(p.pid)
            if it is None:
                self.iters[p.pid] = self.store.append(row)
            elif list(self.store[it]) != row:
                self.store.set(it, list(range(len(row))), row)
        for pid in [pid for pid in self.iters if pid not in present]:
            self.store.remove(self.iters.pop(pid))
            self.procs.pop(pid, None)
        self._update_summary(snap)
        self._sync_buttons()

    def _update_summary(self, snap):
        self.cpu_label.set_text(f"CPU  {snap.cpu_percent:.0f}%")
        self.cpu_bar.set_fraction(max(0.0, min(1.0, snap.cpu_percent / 100.0)))
        if snap.mem_total:
            self.mem_label.set_text(
                f"Memory  {procinfo.human_bytes(snap.mem_used)} of {procinfo.human_bytes(snap.mem_total)}")
            self.mem_bar.set_fraction(max(0.0, min(1.0, snap.mem_used / snap.mem_total)))
        self.count_label.set_text(f"{len(snap.procs)} processes")

    # -- ending tasks -------------------------------------------------------
    def selected_proc(self):
        model, it = self.tree.get_selection().get_selected()
        if it is None:
            return None
        return self.procs.get(model[it][COL_PID])

    def _sync_buttons(self):
        proc = self.selected_proc()
        allowed, why = (False, "") if proc is None else procinfo.can_signal(proc, self.my_uid)
        self.end_btn.set_sensitive(allowed)
        self.force_btn.set_sensitive(allowed)
        if proc is not None and not allowed:
            self.status.set_text(why)

    def _confirm(self, title, text, ok_label):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text=title)
        dialog.format_secondary_text(text)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button(ok_label, Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)  # Enter must not destroy anything
        try:
            return dialog.run() == Gtk.ResponseType.OK
        finally:
            dialog.destroy()

    def end_selected(self, force):
        proc = self.selected_proc()
        if proc is None:
            return
        allowed, why = procinfo.can_signal(proc, self.my_uid)
        if not allowed:
            self.status.set_text(why)
            return
        warning = procinfo.warning_for(proc)
        if force or warning:
            text = warning or "It stops immediately and anything unsaved in it is lost."
            title = f"Force quit {proc.name}?" if force else f"End {proc.name}?"
            if not self._confirm(title, text, "Force quit" if force else "End task"):
                return
        ok, message = self.killer(proc.pid, force=force)
        self.status.set_text(f"{proc.name} ({proc.pid}): {message}")
        if ok:
            GLib.timeout_add(700, self._refresh_if_live)  # so the row disappears promptly

    # -- input --------------------------------------------------------------
    def _on_key(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus()
            return True
        if event.keyval == Gdk.KEY_Escape and self.search.get_text():
            self.search.set_text("")
            return True
        if event.keyval == Gdk.KEY_Delete and not self.search.has_focus():
            self.end_selected(force=False)
            return True
        return False

    def _on_press(self, tree, event):
        if event.button != 3:
            return False
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        if hit is None:
            return False
        tree.get_selection().select_path(hit[0])
        menu = Gtk.Menu()
        for label, force in (("End task", False), ("Force quit", True)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, f=force: self.end_selected(force=f))
            item.set_sensitive(self.end_btn.get_sensitive())
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def _on_pause(self, button):
        self.paused = button.get_active()
        if self.paused:
            self._stop_timer()
            self.status.set_text("Updates paused.")
        else:
            self.status.set_text("")
            self._start_timer()

    def _on_destroy(self, *_):
        self._destroyed = True
        self._stop_timer()


def build_window(app):
    return TaskManagerWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
