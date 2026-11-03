#!/usr/bin/env python3
"""DarkOS Terminal ("The Void") v2 — native GTK3 + VTE terminal.

Real terminal emulation (PTY, ANSI, scrollback) is VTE's job; this file
owns DarkOS chrome — tabs, split panes, glass styling, keybinds — and
wires in the GTK-free logic from the `darkos_void` package: the
engagement workspace, the BlackArch tool catalogue, scrollback link
classification, the command palette and session logging. Every
interactive control is a stock GTK3 widget (no custom Cairo-drawn
buttons) so AT-SPI (screen readers, test tools) can walk it like any
other app.

CLI contract matches the old the-void.sh, so existing callers keep working:
    darkos-terminal.py                  -> interactive shell
    darkos-terminal.py [-e] CMD [ARGS]  -> run CMD instead of the shell
    darkos-terminal.py --cwd DIR [...]  -> start (and -e, if given) in DIR

Keybinds (focused pane/tab unless noted):
    Ctrl+Shift+T       new tab            Ctrl+Shift+E   split right
    Ctrl+Shift+W       close pane/tab     Ctrl+Shift+O   split down
    Ctrl+Shift+C/V     copy/paste         Ctrl+F         find in scrollback
    Ctrl +/-/0         zoom in/out/reset  Ctrl+Shift+P   command palette
    Ctrl+PageUp/Down   prev/next tab
"""
import os
import re
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, Vte  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.css import apply_css  # noqa: E402
from darkos_shell.app_kit import build_titlebar  # noqa: E402
from darkos_shell.palette import ensure_contrast  # noqa: E402
from darkos_shell.tokens import (  # noqa: E402
    ACCENT,
    FONT_MONO_PANGO,
    SURFACE_BASE,
    SURFACE_RAISED,
    TEXT,
    TEXT_MUTED,
)
from darkos_void import catalogue  # noqa: E402
from darkos_void import commands as void_commands  # noqa: E402
from darkos_void import engagement as engagement_mod  # noqa: E402
from darkos_void import linkify, session_log  # noqa: E402

APP_ID = "org.darkos.Terminal"
WM_CLASS = "darkos-terminal"
DEFAULT_TITLE = "Shell"
WINDOW_TITLE = "The Void"

# Background, foreground, cursor and font come from the design tokens, so the
# terminal follows the theme. The ANSI hues are the conventional ones, nudged
# only as far as needed to read on that background: 4.5:1 for the eight
# colours programs print text in, 3:1 for bright black ("dim" text such as
# comments and prompts), checked by ci/test-void.py.
BACKGROUND = SURFACE_BASE
FOREGROUND = TEXT


def _readable(color, minimum=4.5):
    return ensure_contrast(color, BACKGROUND, minimum)


PALETTE = [
    SURFACE_RAISED, _readable("#ff6a65"), _readable("#5edb81"), _readable("#fabb41"),
    _readable("#5b9bff"), _readable("#b57aff"), _readable("#2fd0e0"), TEXT_MUTED,
    _readable("#7c8793", 3.0), _readable("#ff8f8a"), _readable("#86efac"), _readable("#ffd479"),
    _readable("#8dbbff"), _readable("#d0a2ff"), _readable("#67e8f9"), TEXT,
]


def add_class(widget, class_name):
    widget.get_style_context().add_class(class_name)
    return widget


def _rgba(hex_str):
    c = Gdk.RGBA()
    c.parse(hex_str)
    return c


def _default_shell():
    return os.environ.get("SHELL") or "/bin/bash"


def _show_message(parent, text, secondary=None, message_type=Gtk.MessageType.ERROR):
    dialog = Gtk.MessageDialog(
        transient_for=parent, modal=True,
        message_type=message_type, buttons=Gtk.ButtonsType.OK, text=text,
    )
    if secondary:
        dialog.format_secondary_text(secondary)
    dialog.run()
    dialog.destroy()


class TerminalPage(Gtk.Box):
    """One VTE terminal, ready to drop into a split-pane tree."""

    def __init__(self, window, command=None, cwd=None, envv_extra=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.tab_root = None  # set by TabRoot right after construction
        self.font_size = 11
        self.child_pid = None
        self._initial_cwd = cwd
        self._match_tags = {}  # Vte match tag -> linkify kind

        self.vte = Vte.Terminal()
        self.vte.set_hexpand(True)
        self.vte.set_vexpand(True)
        self.vte.set_scrollback_lines(10000)
        self.vte.set_mouse_autohide(True)
        self.vte.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
        self.vte.set_can_focus(True)
        self._apply_font()
        self.vte.set_colors(_rgba(FOREGROUND), _rgba(BACKGROUND),
                             [_rgba(c) for c in PALETTE])
        self.vte.set_color_cursor(_rgba(ACCENT))
        self._install_link_matches()

        self.search_bar = self._build_search_bar()
        self.pack_start(self.search_bar, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.vte)
        self.pack_start(scroller, True, True, 0)

        self.vte.connect("child-exited", self._on_child_exited)
        self.vte.connect("window-title-changed", self._on_title_changed)
        self.vte.connect("focus-in-event", self._on_focus_in)
        self.vte.connect("button-press-event", self._on_button_press)

        self.respawn(command, cwd, envv_extra)

    # -- spawning ---------------------------------------------------------
    def respawn(self, command, cwd, envv_extra=None):
        argv = [_default_shell()] if not command else list(command)
        envv = None
        if envv_extra:
            # Passed through to Vte.Terminal.spawn_async's envv, which
            # *adds* these on top of the inherited environment rather than
            # replacing it (PATH/HOME/etc. survive) — verified empirically,
            # not assumed, since a replace instead of an add would have
            # broken every spawned shell's PATH.
            envv = [f"{key}={value}" for key, value in envv_extra.items()]
        self.vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            cwd or GLib.get_home_dir(),
            argv,
            envv,
            GLib.SpawnFlags.SEARCH_PATH,
            None, None,
            -1, None,
            self._on_spawned, None,
        )

    def _apply_font(self):
        self.vte.set_font(Pango.FontDescription(f"{FONT_MONO_PANGO} {self.font_size}"))

    def zoom(self, delta=0, reset=False):
        self.font_size = 11 if reset else max(6, min(32, self.font_size + delta))
        self._apply_font()

    def _on_spawned(self, terminal, pid, error, _data):
        if error:
            terminal.feed(
                f"\r\n[darkos-terminal] failed to start: {error.message}\r\n".encode()
            )
        else:
            self.child_pid = pid

    def current_cwd(self):
        """Best-effort live cwd of the running child, for "split inherits
        cwd"; falls back to the cwd this pane was started with."""
        if self.child_pid:
            try:
                return os.readlink(f"/proc/{self.child_pid}/cwd")
            except OSError:
                pass
        return self._initial_cwd

    def _on_child_exited(self, terminal, status):
        if self.get_parent() is None:
            # Already unparented — e.g. the whole window is being destroyed
            # and GTK's destroy cascade got here before we did. Nothing
            # left to rearrange; let the cascade finish on its own instead
            # of risking container surgery on a half-torn-down tree.
            return
        if self.tab_root is not None:
            result = self.tab_root.close_pane(self)
            if result == "close-tab":
                self.window.close_page(self.tab_root)
        else:
            self.window.close_page(self)

    def _on_title_changed(self, terminal):
        title = terminal.get_window_title() or DEFAULT_TITLE
        if self.tab_root is not None:
            self.window.rename_page(self.tab_root, title)

    def _on_focus_in(self, *_args):
        if self.tab_root is not None:
            self.tab_root.focus_pane(self)
        return False

    # -- clickable scrollback links ---------------------------------------
    def _install_link_matches(self):
        for kind, pattern in linkify.PATTERNS.items():
            regex = Vte.Regex.new_for_match(pattern, -1, linkify.PCRE2_FLAGS[kind])
            tag = self.vte.match_add_regex(regex, 0)
            self.vte.match_set_cursor_name(tag, "pointer")
            self._match_tags[tag] = kind

    def _match_at_event(self, event):
        try:
            result = self.vte.match_check_event(event)
        except (TypeError, GLib.Error):
            return None
        if not result:
            return None
        try:
            text, tag = result
        except (TypeError, ValueError):
            return None
        kind = self._match_tags.get(tag)
        if not text or kind is None:
            return None
        return kind, text

    def _on_button_press(self, _widget, event):
        hit = self._match_at_event(event)
        if hit is None:
            return False
        kind, value = hit
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if event.button == 1 and ctrl and kind == "url":
            Gio.AppInfo.launch_default_for_uri(value, None)
            return True
        if event.button == 3:
            self._show_link_menu(kind, value, event)
            return True
        return False

    def _show_link_menu(self, kind, value, event):
        menu = Gtk.Menu()
        for action_id, label in linkify.actions_for(kind):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, a=action_id: self._run_link_action(a, value))
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _run_link_action(self, action_id, value):
        if action_id == "copy":
            Gtk.Clipboard.get_default(Gdk.Display.get_default()).set_text(value, -1)
        elif action_id == "open":
            Gio.AppInfo.launch_default_for_uri(value, None)
        elif action_id == "set-target":
            self.window.set_target(value)

    # -- scrollback search --------------------------------------------------
    def _build_search_bar(self):
        revealer = Gtk.Revealer()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_class(box, "toolbar")
        box.set_border_width(4)
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("search-changed", lambda *_a: self._apply_search_regex())
        self._search_entry.connect("activate", lambda *_a: self.search_next())
        self._search_entry.connect("stop-search", lambda *_a: self.hide_search())
        prev_btn = Gtk.Button.new_from_icon_name("go-up-symbolic", Gtk.IconSize.MENU)
        next_btn = Gtk.Button.new_from_icon_name("go-down-symbolic", Gtk.IconSize.MENU)
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        for button, handler in ((prev_btn, self.search_previous), (next_btn, self.search_next),
                                 (close_btn, self.hide_search)):
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_focus_on_click(False)
            add_class(button, "icon-button")
            button.connect("clicked", lambda _b, h=handler: h())
        box.pack_start(self._search_entry, True, True, 0)
        box.pack_start(prev_btn, False, False, 0)
        box.pack_start(next_btn, False, False, 0)
        box.pack_start(close_btn, False, False, 0)
        revealer.add(box)
        return revealer

    def show_search(self):
        self.search_bar.set_reveal_child(True)
        self.search_bar.show_all()
        self._search_entry.grab_focus()

    def hide_search(self):
        self.search_bar.set_reveal_child(False)
        self.vte.grab_focus()

    def toggle_search(self):
        if self.search_bar.get_reveal_child():
            self.hide_search()
        else:
            self.show_search()

    def _apply_search_regex(self):
        text = self._search_entry.get_text()
        if not text:
            self.vte.search_set_regex(None, 0)
            return
        try:
            regex = Vte.Regex.new_for_search(
                re.escape(text), -1, linkify.PCRE2_MULTILINE | linkify.PCRE2_CASELESS)
        except GLib.Error:
            return
        self.vte.search_set_regex(regex, 0)
        self.vte.search_set_wrap_around(True)
        self.vte.search_find_next()

    def search_next(self):
        self.vte.search_find_next()

    def search_previous(self):
        self.vte.search_find_previous()

    # -- tool launcher / command palette hand-off --------------------------
    def feed_insert(self, text):
        """Types `text` into this pane's prompt without running it (no
        trailing newline) — verified against a real bash child: the text
        sits on the current input line until the user presses Enter."""
        self.vte.feed_child(text.encode("utf-8"))
        self.vte.grab_focus()

    def feed_run(self, text):
        """Types `text` into this pane and runs it immediately (trailing
        newline) — for direct actions like starting session logging, as
        opposed to an inserted-for-review tool command."""
        if not text.endswith("\n"):
            text += "\n"
        self.vte.feed_child(text.encode("utf-8"))
        self.vte.grab_focus()

    # -- session logging / export -------------------------------------------
    def start_logging(self):
        active = self.window.engagement
        log_path = session_log.log_path_for(
            title=re.sub(r"\s+", "-", (self.window.get_title() or "session")),
            engagement_dir=active.dir if active else None,
        )
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _show_message(self.window, "Could not create the log directory.", str(exc))
            return
        self.feed_run(session_log.exec_command(log_path))
        self._announce(f"Logging this pane to {log_path}")

    def save_scrollback(self):
        dialog = Gtk.FileChooserDialog(
            title="Save Scrollback As", transient_for=self.window,
            action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_current_name("void-scrollback.txt")
        dialog.set_do_overwrite_confirmation(True)
        home = GLib.get_home_dir()
        if home:
            dialog.set_current_folder(home)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not path:
            return
        try:
            gfile = Gio.File.new_for_path(path)
            stream = gfile.replace(None, False, Gio.FileCreateFlags.NONE, None)
            self.vte.write_contents_sync(stream, Vte.WriteFlags.DEFAULT, None)
            stream.close(None)
        except GLib.Error as exc:
            _show_message(self.window, "Could not save the scrollback.", str(exc))
            return
        self._announce(f"Saved scrollback to {path}")

    def _announce(self, text):
        bar = Gtk.InfoBar()
        bar.set_message_type(Gtk.MessageType.INFO)
        bar.set_show_close_button(True)
        bar.connect("response", lambda b, *_a: b.destroy())
        label = Gtk.Label(label=text)
        label.set_line_wrap(True)
        label.set_xalign(0.0)
        bar.get_content_area().pack_start(label, True, True, 0)
        self.pack_start(bar, False, False, 0)
        self.reorder_child(bar, 0)
        bar.show_all()


class TabLabel(Gtk.Box):
    def __init__(self, text, on_close):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.label = Gtk.Label(label=text)
        # width_chars is the *minimum*: an ellipsized label with only a max
        # collapses to "..." in a Gtk.Notebook tab, which is how every tab
        # ended up unreadable.
        self.label.set_width_chars(10)
        self.label.set_max_width_chars(18)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        close_btn = Gtk.Button()
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.add(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU))
        close_btn.set_focus_on_click(False)
        close_btn.connect("clicked", on_close)
        add_class(close_btn, "icon-button")
        self.pack_start(self.label, True, True, 0)
        self.pack_start(close_btn, False, False, 0)
        self.show_all()

    def set_text(self, text):
        self.label.set_text(text)


class TabRoot(Gtk.Box):
    """One notebook page: a single pane, or a tree of panes split with
    Gtk.Paned. `leaves` tracks every TerminalPage in this tab in creation
    order; `focused` is whichever last had keyboard focus.

    Split: wrap the focused leaf's current slot (this box's one child, or
    one side of a Gtk.Paned) in a new Gtk.Paned holding the old leaf and a
    fresh one. Close: remove the dying leaf and "merge up" — the sibling
    takes the dying leaf's old slot and the now-empty Paned is dropped.
    """

    def __init__(self, window, command=None, cwd=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.leaves = []
        self.focused = None
        self._tab_label = None
        leaf = self._new_leaf(command=command, cwd=cwd)
        self.pack_start(leaf, True, True, 0)
        self._set_focused(leaf)

    def _envv_for(self, cwd):
        engagement = self.window.engagement
        return engagement.env() if engagement is not None else None

    def _new_leaf(self, command=None, cwd=None):
        leaf = TerminalPage(self.window, command=command, cwd=cwd,
                             envv_extra=self._envv_for(cwd))
        leaf.tab_root = self
        self.leaves.append(leaf)
        return leaf

    def _set_focused(self, leaf):
        self.focused = leaf

    def focus_pane(self, leaf):
        if leaf in self.leaves:
            self._set_focused(leaf)

    def split(self, orientation):
        target = self.focused or (self.leaves[0] if self.leaves else None)
        if target is None:
            return None
        parent = target.get_parent()
        new_leaf = self._new_leaf(cwd=target.current_cwd())
        paned = Gtk.Paned(orientation=orientation)
        paned.set_wide_handle(True)
        add_class(paned, "void-split")
        if parent is self:
            self.remove(target)
            paned.pack1(target, True, False)
            paned.pack2(new_leaf, True, False)
            self.pack_start(paned, True, True, 0)
        else:
            in_slot_one = parent.get_child1() is target
            parent.remove(target)
            paned.pack1(target, True, False)
            paned.pack2(new_leaf, True, False)
            if in_slot_one:
                parent.pack1(paned, True, False)
            else:
                parent.pack2(paned, True, False)
        paned.show_all()
        self._set_focused(new_leaf)
        new_leaf.vte.grab_focus()
        return new_leaf

    def close_pane(self, leaf):
        """Returns "close-tab" if that was this tab's last pane (caller
        should close the whole tab), "closed" if a pane was removed and
        the tab lives on, or None if `leaf` wasn't in this tab."""
        if leaf not in self.leaves:
            return None
        parent = leaf.get_parent()
        self.leaves.remove(leaf)
        if parent is None:
            # Defence in depth: see the matching comment in
            # TerminalPage._on_child_exited. Bookkeeping is done; there is
            # no still-live container to rearrange.
            return None
        if parent is self:
            return "close-tab"

        sibling = parent.get_child2() if parent.get_child1() is leaf else parent.get_child1()
        grandparent = parent.get_parent()
        parent.remove(leaf)
        parent.remove(sibling)
        leaf.destroy()
        if grandparent is self:
            self.remove(parent)
            self.pack_start(sibling, True, True, 0)
        else:
            in_slot_one = grandparent.get_child1() is parent
            grandparent.remove(parent)
            if in_slot_one:
                grandparent.pack1(sibling, True, False)
            else:
                grandparent.pack2(sibling, True, False)
        parent.destroy()
        sibling.show_all()
        if self.leaves:
            new_focus = self.leaves[-1]
            self._set_focused(new_focus)
            new_focus.vte.grab_focus()
        return "closed"


class EngagementDialog(Gtk.Dialog):
    """Status + switch + create, all in one place."""

    def __init__(self, window):
        super().__init__(title="Engagement", transient_for=window, modal=True)
        self.main_window = window
        self.set_default_size(420, 420)
        self.add_buttons("Close", Gtk.ResponseType.CLOSE)
        box = self.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)

        self._status = Gtk.Label(xalign=0.0)
        add_class(self._status, "body-muted")
        box.pack_start(self._status, False, False, 0)

        clear_btn = Gtk.Button(label="Clear Active Engagement")
        clear_btn.connect("clicked", self._on_clear)
        box.pack_start(clear_btn, False, False, 0)

        heading = Gtk.Label(label="Existing Engagements", xalign=0.0)
        add_class(heading, "section-title")
        box.pack_start(heading, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self._list = Gtk.ListBox()
        add_class(self._list, "sidebar")
        self._list.connect("row-activated", self._on_row_activated)
        scroller.add(self._list)
        box.pack_start(scroller, True, True, 0)

        new_heading = Gtk.Label(label="New Engagement", xalign=0.0)
        add_class(new_heading, "section-title")
        box.pack_start(new_heading, False, False, 0)

        form = Gtk.Grid(column_spacing=8, row_spacing=6)
        self._name_entry = Gtk.Entry(placeholder_text="Name (e.g. Acme Corp Pentest)")
        self._target_entry = Gtk.Entry(placeholder_text="Target (optional)")
        self._name_entry.set_hexpand(True)
        self._target_entry.set_hexpand(True)
        form.attach(self._name_entry, 0, 0, 1, 1)
        form.attach(self._target_entry, 0, 1, 1, 1)
        create_btn = Gtk.Button(label="Create")
        add_class(create_btn, "suggested-action")
        create_btn.connect("clicked", self._on_create)
        form.attach(create_btn, 0, 2, 1, 1)
        box.pack_start(form, False, False, 0)

        self._refresh()
        self.show_all()

    def _refresh(self):
        active = self.main_window.engagement
        if active:
            self._status.set_text(f"Active: {active.name}"
                                   + (f"  (target: {active.target})" if active.target else ""))
        else:
            self._status.set_text("No active engagement.")
        for child in list(self._list.get_children()):
            self._list.remove(child)
        for eng in engagement_mod.list_engagements():
            row = Gtk.ListBoxRow()
            row.engagement = eng
            label = Gtk.Label(xalign=0.0)
            label.set_markup(f"<b>{GLib.markup_escape_text(eng.name)}</b>  "
                              f"<span alpha='70%'>{GLib.markup_escape_text(eng.target or '—')}</span>")
            row.add(label)
            add_class(row, "sidebar-row")
            self._list.add(row)
        self._list.show_all()

    def _on_row_activated(self, _listbox, row):
        self.main_window.set_engagement(row.engagement)
        self._refresh()

    def _on_clear(self, _button):
        self.main_window.set_engagement(None)
        self._refresh()

    def _on_create(self, _button):
        name = self._name_entry.get_text()
        target = self._target_entry.get_text()
        try:
            eng = engagement_mod.create_engagement(name, target)
        except engagement_mod.EngagementError as exc:
            _show_message(self, "Couldn't create that engagement.", str(exc))
            return
        self.main_window.set_engagement(eng)
        self._name_entry.set_text("")
        self._target_entry.set_text("")
        self._refresh()


class ToolLauncherDialog(Gtk.Dialog):
    """Browse/search the BlackArch catalogue; insert a command (never
    auto-run) into the pane that was focused when this opened, or install
    the whole group via `darkos-tool-groups` in a new tab."""

    def __init__(self, window):
        super().__init__(title="Tool Launcher", transient_for=window, modal=True)
        self.main_window = window
        self.target_pane = window.focused_pane()
        self._selected_group = catalogue.all_groups()[0] if catalogue.all_groups() else None
        self._installed = catalogue.installed_packages()
        self.set_default_size(760, 480)
        self.add_buttons("Close", Gtk.ResponseType.CLOSE,
                          "Install Group", 1, "Insert Command", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        body = self.get_content_area()
        body.set_border_width(0)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        body.pack_start(paned, True, True, 0)

        group_scroller = Gtk.ScrolledWindow()
        group_scroller.set_size_request(180, -1)
        self._group_list = Gtk.ListBox()
        add_class(self._group_list, "sidebar")
        self._group_list.connect("row-selected", self._on_group_selected)
        for group in catalogue.all_groups():
            row = Gtk.ListBoxRow()
            row.group = group
            label = Gtk.Label(label=f"blackarch-{group}", xalign=0.0)
            row.add(label)
            add_class(row, "sidebar-row")
            self._group_list.add(row)
        group_scroller.add(self._group_list)
        paned.pack1(group_scroller, False, False)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right.set_border_width(8)
        self._search = Gtk.SearchEntry(placeholder_text="Search tools…")
        self._search.connect("search-changed", lambda *_a: self._refresh_tools())
        right.pack_start(self._search, False, False, 0)

        tool_scroller = Gtk.ScrolledWindow()
        tool_scroller.set_vexpand(True)
        self._tool_list = Gtk.ListBox()
        add_class(self._tool_list, "sidebar")
        self._tool_list.connect("row-activated", lambda *_a: self.response(Gtk.ResponseType.OK))
        tool_scroller.add(self._tool_list)
        right.pack_start(tool_scroller, True, True, 0)
        paned.pack2(right, True, False)

        self._group_list.select_row(self._group_list.get_row_at_index(0))
        self.connect("response", self._on_response)
        self.show_all()

    def _on_group_selected(self, _listbox, row):
        if row is not None:
            self._selected_group = row.group
            self._search.set_text("")
        self._refresh_tools()

    def _refresh_tools(self):
        for child in list(self._tool_list.get_children()):
            self._tool_list.remove(child)
        query = self._search.get_text().strip()
        tools = catalogue.search(query) if query else catalogue.tools_for_group(self._selected_group)
        for tool in tools:
            row = Gtk.ListBoxRow()
            row.tool = tool
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name = Gtk.Label(label=tool.name, xalign=0.0)
            desc = Gtk.Label(label=tool.description, xalign=0.0)
            add_class(desc, "caption")
            desc.set_line_wrap(True)
            text_box.pack_start(name, False, False, 0)
            text_box.pack_start(desc, False, False, 0)
            inner.pack_start(text_box, True, True, 0)
            installed = catalogue.is_installed(tool, self._installed)
            if installed:
                badge = Gtk.Label(label="Installed")
                add_class(badge, "caption")
                inner.pack_start(badge, False, False, 0)
            row.add(inner)
            add_class(row, "sidebar-row")
            self._tool_list.add(row)
        self._tool_list.show_all()

    def _selected_tool(self):
        row = self._tool_list.get_selected_row()
        return row.tool if row is not None else None

    def _on_response(self, _dialog, response_id):
        if response_id == Gtk.ResponseType.OK:
            tool = self._selected_tool()
            if tool is not None and self.target_pane is not None:
                command = catalogue.expand_command(tool.template, self._target_value())
                self.target_pane.feed_insert(command)
        elif response_id == 1:  # Install Group
            group = self._selected_group
            if group:
                self.main_window.new_tab(command=["sudo", "/usr/local/bin/darkos-tool-groups",
                                              "install", f"blackarch-{group}"])

    def _target_value(self):
        eng = self.main_window.engagement
        return eng.target if eng and eng.target else None


class CommandPaletteDialog(Gtk.Dialog):
    def __init__(self, window):
        super().__init__(title="Command Palette", transient_for=window, modal=True)
        self.main_window = window
        self.set_default_size(440, 360)
        self.set_decorated(True)
        body = self.get_content_area()
        body.set_border_width(8)
        body.set_spacing(6)

        self._entry = Gtk.SearchEntry(placeholder_text="Type a command…")
        self._entry.connect("search-changed", lambda *_a: self._refresh())
        self._entry.connect("activate", self._activate_selected)
        body.pack_start(self._entry, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self._list = Gtk.ListBox()
        add_class(self._list, "sidebar")
        self._list.connect("row-activated", self._activate_selected)
        scroller.add(self._list)
        body.pack_start(scroller, True, True, 0)

        self.connect("key-press-event", self._on_key_press)
        self._refresh()
        self.show_all()
        self._entry.grab_focus()

    def _refresh(self):
        for child in list(self._list.get_children()):
            self._list.remove(child)
        for cmd in void_commands.filter_commands(self._entry.get_text()):
            row = Gtk.ListBoxRow()
            row.command_id = cmd.id
            label = Gtk.Label(label=f"{cmd.title}  \u2014  {cmd.category}", xalign=0.0)
            row.add(label)
            add_class(row, "sidebar-row")
            self._list.add(row)
        self._list.show_all()
        first = self._list.get_row_at_index(0)
        if first is not None:
            self._list.select_row(first)

    def _on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False

    def _activate_selected(self, *_args):
        row = self._list.get_selected_row()
        if row is not None:
            self.main_window.run_palette_command(row.command_id)
        self.destroy()


class TerminalWindow(Gtk.ApplicationWindow):
    def __init__(self, app, command=None, cwd=None):
        super().__init__(application=app, title=WINDOW_TITLE)
        self.set_default_size(920, 560)
        add_class(self, "app-window")
        self.default_cwd = cwd
        self.engagement = None

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        add_class(self.notebook, "terminal-tabs")
        self.notebook.set_action_widget(self._build_action_toolbar(), Gtk.PackType.END)
        self.add(self.notebook)

        self.connect("key-press-event", self._on_key_press)
        self.new_tab(command=command, cwd=cwd)

    def _build_action_toolbar(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        box.set_border_width(2)
        for icon, tooltip, handler in (
            ("security-high-symbolic", "Engagement", self.open_engagement_dialog),
            ("applications-engineering-symbolic", "Tool Launcher", self.open_tool_launcher),
            ("edit-find-symbolic", "Command Palette", self.open_command_palette),
        ):
            btn = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_tooltip_text(tooltip)
            btn.set_focus_on_click(False)
            add_class(btn, "icon-button")
            btn.connect("clicked", lambda _b, h=handler: h())
            box.pack_start(btn, False, False, 0)
        box.show_all()
        return box

    # -- tab/pane management ------------------------------------------------
    def new_tab(self, command=None, cwd=None):
        tab = TabRoot(self, command=command, cwd=cwd or self.default_cwd)
        label = TabLabel(DEFAULT_TITLE, lambda *_a: self.close_page(tab))
        tab._tab_label = label
        idx = self.notebook.append_page(tab, label)
        self.notebook.set_tab_reorderable(tab, True)
        tab.show_all()
        self.notebook.set_current_page(idx)
        tab.focused.vte.grab_focus()
        return tab

    def close_page(self, tab):
        idx = self.notebook.page_num(tab)
        if idx == -1:
            return
        self.notebook.remove_page(idx)
        tab.destroy()
        if self.notebook.get_n_pages() == 0:
            self.destroy()

    def rename_page(self, tab, title):
        if getattr(tab, "_tab_label", None) is not None:
            tab._tab_label.set_text(title)

    def focused_tab(self):
        idx = self.notebook.get_current_page()
        return self.notebook.get_nth_page(idx) if idx != -1 else None

    def focused_pane(self):
        tab = self.focused_tab()
        return tab.focused if tab is not None else None

    def split_focused(self, orientation):
        tab = self.focused_tab()
        if tab is not None:
            tab.split(orientation)

    def close_focused_pane(self):
        tab = self.focused_tab()
        if tab is None or tab.focused is None:
            return
        result = tab.close_pane(tab.focused)
        if result == "close-tab":
            self.close_page(tab)

    # -- engagement workspace -------------------------------------------
    def set_engagement(self, engagement):
        self.engagement = engagement
        self.set_title(f"{WINDOW_TITLE} \u2014 {engagement.name}" if engagement else WINDOW_TITLE)

    def set_target(self, value):
        if self.engagement is not None:
            engagement_mod.update_target(self.engagement, value)
        pane = self.focused_pane()
        if pane is not None:
            pane.feed_run(f"export TARGET={value}")

    # -- dialogs ----------------------------------------------------------
    def open_engagement_dialog(self):
        EngagementDialog(self).run()

    def open_tool_launcher(self):
        dialog = ToolLauncherDialog(self)
        dialog.run()
        dialog.destroy()

    def open_command_palette(self):
        CommandPaletteDialog(self)

    def run_palette_command(self, command_id):
        pane = self.focused_pane()
        if command_id == "new-tab":
            self.new_tab()
        elif command_id == "close-pane":
            self.close_focused_pane()
        elif command_id == "split-right":
            self.split_focused(Gtk.Orientation.HORIZONTAL)
        elif command_id == "split-down":
            self.split_focused(Gtk.Orientation.VERTICAL)
        elif command_id == "find" and pane:
            pane.show_search()
        elif command_id == "new-engagement":
            self.open_engagement_dialog()
        elif command_id == "switch-engagement":
            self.open_engagement_dialog()
        elif command_id == "set-target":
            self._prompt_set_target()
        elif command_id == "start-log" and pane:
            pane.start_logging()
        elif command_id == "tool-launcher":
            self.open_tool_launcher()
        elif command_id == "save-scrollback" and pane:
            pane.save_scrollback()
        elif command_id == "copy" and pane:
            pane.vte.copy_clipboard()
        elif command_id == "paste" and pane:
            pane.vte.paste_clipboard()
        elif command_id == "zoom-in" and pane:
            pane.zoom(1)
        elif command_id == "zoom-out" and pane:
            pane.zoom(-1)
        elif command_id == "zoom-reset" and pane:
            pane.zoom(reset=True)

    def _prompt_set_target(self):
        dialog = Gtk.Dialog(title="Set Target", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Set", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(placeholder_text="203.0.113.10")
        if self.engagement and self.engagement.target:
            entry.set_text(self.engagement.target)
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.pack_start(entry, False, False, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK and entry.get_text().strip():
            self.set_target(entry.get_text().strip())
        dialog.destroy()

    # -- keybinds ---------------------------------------------------------
    def _on_key_press(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        kv = event.keyval
        pane = self.focused_pane()

        if ctrl and shift and kv in (Gdk.KEY_T, Gdk.KEY_t):
            self.new_tab()
            return True
        if ctrl and shift and kv in (Gdk.KEY_W, Gdk.KEY_w):
            self.close_focused_pane()
            return True
        if ctrl and shift and kv in (Gdk.KEY_C, Gdk.KEY_c) and pane:
            pane.vte.copy_clipboard()
            return True
        if ctrl and shift and kv in (Gdk.KEY_V, Gdk.KEY_v) and pane:
            pane.vte.paste_clipboard()
            return True
        if ctrl and shift and kv in (Gdk.KEY_E, Gdk.KEY_e):
            self.split_focused(Gtk.Orientation.HORIZONTAL)
            return True
        if ctrl and shift and kv in (Gdk.KEY_O, Gdk.KEY_o):
            self.split_focused(Gtk.Orientation.VERTICAL)
            return True
        if ctrl and shift and kv in (Gdk.KEY_P, Gdk.KEY_p):
            self.open_command_palette()
            return True
        if ctrl and not shift and kv in (Gdk.KEY_f, Gdk.KEY_F) and pane:
            pane.toggle_search()
            return True
        if ctrl and kv in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add) and pane:
            pane.zoom(1)
            return True
        if ctrl and kv in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract) and pane:
            pane.zoom(-1)
            return True
        if ctrl and kv in (Gdk.KEY_0, Gdk.KEY_KP_0) and pane:
            pane.zoom(reset=True)
            return True
        if ctrl and kv == Gdk.KEY_Page_Down:
            self.notebook.next_page()
            return True
        if ctrl and kv == Gdk.KEY_Page_Up:
            self.notebook.prev_page()
            return True
        return False


def parse_args(argv):
    """--cwd DIR is our own addition (used by darkos-files.py's "Open Terminal
    Here"). -e CMD [ARGS] mirrors the-void.sh's old contract so existing
    callers (darkos-tool-groups, etc.) keep working unchanged."""
    args = argv[1:]
    cwd = None
    if args[:1] == ["--cwd"] and len(args) >= 2:
        cwd = args[1]
        args = args[2:]
    if args[:1] == ["-e"]:
        args = args[1:]
    return cwd, (args or None)


def main():
    GLib.set_prgname(WM_CLASS)
    cwd, command = parse_args(sys.argv)
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(_app):
        apply_css()
        win = TerminalWindow(_app, command=command, cwd=cwd)
        win.set_titlebar(build_titlebar(win, win.get_title()))
        win.show_all()

    app.connect("activate", on_activate)
    # Pass only argv[0] through to GApplication — our own -e/CMD syntax
    # isn't a GTK option and would otherwise trip GLib's option parser.
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
