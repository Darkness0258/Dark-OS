"""The Store's curated pages: Browse (cards and detail) and Packs.

Everything is opt-in. Opening a page runs read-only queries (what is installed, sizes, permissions)
and nothing else; an install or removal happens only when the person presses its button, and then
it runs in the visible terminal, never in the background.

Anything that touches the system goes through a `Services` object, so tests give these pages a fake
and no real pacman, flatpak or terminal is involved.
"""
import os
import shutil
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from darkos_shell import store_actions, store_catalog  # noqa: E402
from darkos_shell.app_kit import add_class  # noqa: E402
from darkos_shell.pack_picker import PackPicker  # noqa: E402

CHOICE_CANCEL, CHOICE_KEEP, CHOICE_DELETE = "cancel", "keep", "delete"
NOT_SANDBOXED = "Not sandboxed: runs with your own access"


def _label(text, css_class=None, wrap=True, selectable=False):
    label = Gtk.Label(label=text)
    label.set_xalign(0.0)
    label.set_line_wrap(wrap)
    label.set_selectable(selectable)
    if css_class:
        add_class(label, css_class)
    return label


class Services:
    """The only way these pages touch the system. Tests substitute an object with the same methods."""

    def __init__(self, shield_ready=None, flatpak_ready=None):
        self._shield_ready = shield_ready      # None: look it up when asked
        self._flatpak_ready = flatpak_ready
        self._tokens = {}
        self.closed = False

    # -- what can be done here ------------------------------------------------------------------------------------

    def prerequisite(self, source):
        """(ok, why_not). Fail closed: an install that cannot be gated or fetched is blocked, with the reason."""
        if source == store_catalog.SOURCE_PACMAN:
            if not shutil.which("pacman"):
                return False, "pacman was not found, so Arch apps cannot be installed."
            shield = self._shield_ready if self._shield_ready is not None else bool(shutil.which("clamscan"))
            if not shield or not os.path.exists(store_actions.GATE_BIN):
                return False, "Shield's scanner is not available, so Arch apps cannot be checked and will not be installed."
            return True, ""
        ready = self._flatpak_ready if self._flatpak_ready is not None else bool(shutil.which("flatpak"))
        return (True, "") if ready else (False, "Flatpak is not installed, so Flathub apps cannot be installed.")

    def home(self):
        return Path(os.path.expanduser("~"))

    # -- read-only queries (run in worker threads) ----------------------------------------------------------------

    def installed(self):
        return store_actions.installed_sets()

    def pacman_sizes(self, packages):
        return store_actions.pacman_sizes(list(packages))

    def flatpak_details(self, app_id):
        return store_actions.flatpak_details(app_id)

    def pacman_files(self, packages):
        return store_actions.pacman_files(list(packages))

    def data_dirs(self, entry):
        """[(path, bytes, complete)] of the app's data that exists now."""
        if entry.source == store_catalog.SOURCE_FLATPAK:
            path = self.home() / ".var" / "app" / entry.packages[0]
            if path.is_dir():
                size, complete = store_actions.path_size(path)
                return [(path, size, complete)]
            return []
        return store_actions.data_dirs(entry, self.home())

    # -- things that change the system (only ever called from a button) --------------------------------------------

    def open_terminal(self, argv):
        """Start the visible terminal. Raises OSError when it cannot start."""
        return subprocess.Popen(argv, start_new_session=True)

    def watch(self, handle, callback):
        """Call `callback` once the terminal has closed."""
        def poll():
            if self.closed:
                return False
            if handle is not None and handle.poll() is None:
                return True
            callback()
            return False
        GLib.timeout_add_seconds(1, poll)

    def run_job(self, key, work, apply):
        """Run work() off the main thread; apply(ok, result) runs on it. Only the newest job per key is applied."""
        token = self._tokens[key] = self._tokens.get(key, 0) + 1

        def worker():
            try:
                outcome = (True, work())
            except Exception as error:  # noqa: BLE001 - shown to the person, not swallowed
                outcome = (False, str(error) or type(error).__name__)
            GLib.idle_add(finish, *outcome)

        def finish(ok, result):
            if token == self._tokens.get(key) and not self.closed:
                apply(ok, result)
            return False

        threading.Thread(target=worker, daemon=True).start()

    def confirm_remove(self, parent, entry, folders):
        """Ask what to do with the app's data. Returns CHOICE_CANCEL, CHOICE_KEEP or CHOICE_DELETE."""
        dialog = Gtk.Dialog(title=f"Remove {entry.name}?", transient_for=parent, modal=True)
        dialog.set_default_size(460, -1)
        body = dialog.get_content_area()
        body.set_spacing(10)
        body.set_border_width(16)
        if folders:
            body.pack_start(_label("Its data is in your home folder:", "lead"), False, False, 0)
            for path, size, complete in folders:
                shown = ("at least " if not complete else "") + store_actions.human_size(size)
                body.pack_start(_label(f"{path}  ({shown})", "caption", selectable=True), False, False, 0)
            body.pack_start(_label("Keep it and a reinstall picks up where you left off. "
                                   "Delete it to free the space; that cannot be undone.", "body-muted"), False, False, 0)
        else:
            body.pack_start(_label(f"DarkOS found no {entry.name} data in your home folder.", "body-muted"),
                            False, False, 0)
        cancel = dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        add_class(cancel, "action-button")
        keep = dialog.add_button("Remove, keep my data" if folders else "Remove", Gtk.ResponseType.ACCEPT)
        add_class(keep, "action-button")
        if folders:
            delete = dialog.add_button("Remove and delete data", Gtk.ResponseType.REJECT)
            add_class(delete, "action-button")
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        keep.grab_focus()
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        return {Gtk.ResponseType.ACCEPT: CHOICE_KEEP, Gtk.ResponseType.REJECT: CHOICE_DELETE}.get(response, CHOICE_CANCEL)


def state_text(state):
    return {"installed": "Installed", "partial": "Partly installed"}.get(state, "")


class BrowsePage(Gtk.Box):
    """Search, a category row and an even grid of equal cards; a card opens its detail page."""

    def __init__(self, services):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_border_width(16)
        self.services = services
        self.pacman_installed = set()
        self.flatpak_installed = set()
        self.category = ""
        self.query = ""
        self.current = None            # the entry whose detail page is open
        self._card_state = {}          # entry id -> Gtk.Label
        self._category_buttons = {}
        self._detail_widgets = {}

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search the catalogue")
        self.search.connect("search-changed", self._on_search)
        self.search.get_accessible().set_name("Search the catalogue")
        self.search.set_no_show_all(True)         # hidden while a detail page is open
        self.pack_start(self.search, False, False, 0)
        self.category_row = self._build_categories()
        self.category_row.set_no_show_all(True)
        self.pack_start(self.category_row, False, False, 0)
        self.notice = _label("", "flag-text")
        self.notice.set_no_show_all(True)
        self.pack_start(self.notice, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.add_named(self._build_grid_page(), "grid")
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.stack.add_named(self.detail, "detail")
        self.pack_start(self.stack, True, True, 0)
        self._populate()
        self._update_notice()

    # -- grid -----------------------------------------------------------------------------------------------------

    def _build_categories(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for key, text in (("", "All"), *store_catalog.CATEGORIES):
            button = Gtk.ToggleButton(label=text)
            add_class(button, "toggle-button")
            button.set_active(key == "")
            button.connect("toggled", self._on_category, key)
            row.pack_start(button, False, False, 0)
            self._category_buttons[key] = button
        return row

    def _build_grid_page(self):
        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(True)
        self.flow.set_min_children_per_line(2)
        self.flow.set_max_children_per_line(4)
        self.flow.set_row_spacing(10)
        self.flow.set_column_spacing(10)
        self.flow.set_activate_on_single_click(True)
        self.flow.connect("child-activated", lambda _flow, child: self.show_detail(child.entry))
        self.empty = _label("Nothing in the catalogue matches. The Search tab looks through pacman, the AUR and Flathub.",
                            "body-muted")
        self.empty.set_no_show_all(True)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.pack_start(self.empty, False, False, 0)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(self.flow)
        page.pack_start(scrolled, True, True, 0)
        return page

    def _entries(self):
        pool = store_catalog.in_category(self.category) if self.category else None
        return store_catalog.search(self.query, entries=pool)

    def _populate(self):
        for child in self.flow.get_children():
            self.flow.remove(child)
        self._card_state = {}
        entries = self._entries()
        for entry in entries:
            self.flow.add(self._build_card(entry))
        self.empty.set_visible(not entries)
        self.flow.show_all()

    def _build_card(self, entry):
        child = Gtk.FlowBoxChild()
        child.entry = entry
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        add_class(box, "card")
        box.set_size_request(190, 116)
        box.pack_start(_label(entry.name, "section-title", wrap=False), False, False, 0)
        summary = _label(entry.summary, "body-muted")
        summary.set_max_width_chars(28)
        box.pack_start(summary, True, True, 0)
        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        badge = _label(store_catalog.badge(entry.source), "source-badge", wrap=False)
        if entry.source == store_catalog.SOURCE_FLATPAK:
            add_class(badge, "unscanned")
        meta.pack_start(badge, False, False, 0)
        state = _label(state_text(self._state(entry)), "caption", wrap=False)
        meta.pack_end(state, False, False, 0)
        box.pack_start(meta, False, False, 0)
        child.add(box)
        self._card_state[entry.id] = (child, state)
        self._name_card(child, entry)
        return child

    def _name_card(self, child, entry):
        text = f"{entry.name}. {entry.summary} {store_catalog.badge(entry.source)}. {state_text(self._state(entry))}"
        child.get_accessible().set_name(text.strip())

    def _state(self, entry):
        return store_actions.entry_state(entry, self.pacman_installed, self.flatpak_installed)

    def _on_search(self, entry):
        self.query = entry.get_text()
        self._populate()

    def _on_category(self, button, key):
        if not button.get_active():
            if not any(b.get_active() for b in self._category_buttons.values()):
                button.set_active(True)           # one category is always chosen
            return
        self.category = key
        for other_key, other in self._category_buttons.items():
            if other_key != key and other.get_active():
                other.set_active(False)
        self._populate()

    def _update_notice(self):
        reasons = []
        ok, why = self.services.prerequisite(store_catalog.SOURCE_PACMAN)
        if not ok:
            reasons.append(why)
        self.notice.set_text(" ".join(reasons))
        self.notice.set_visible(bool(reasons))

    # -- installed state ------------------------------------------------------------------------------------------

    def refresh(self):
        """Re-read what is installed (read-only) and update the cards and the open detail page."""
        def work():
            return self.services.installed()

        def apply(ok, result):
            if ok:
                self.pacman_installed, self.flatpak_installed = result
            for entry_id, (child, label) in self._card_state.items():
                entry = store_catalog.get(entry_id)
                label.set_text(state_text(self._state(entry)))
                self._name_card(child, entry)
            if self.current is not None:
                self._update_actions()
        self.services.run_job("installed", work, apply)

    # -- detail ---------------------------------------------------------------------------------------------------

    def show_detail(self, entry):
        self.current = entry
        for child in self.detail.get_children():
            self.detail.remove(child)
        widgets = self._detail_widgets = {}

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        back = Gtk.Button(label="Back")
        add_class(back, "action-button")
        back.connect("clicked", lambda _b: self.go_back())
        top.pack_start(back, False, False, 0)
        top.pack_start(_label(entry.name, "title", wrap=False), True, True, 0)
        widgets["back"] = back
        self.detail.pack_start(top, False, False, 0)
        self.detail.pack_start(_label(entry.summary, "lead"), False, False, 0)

        source = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        badge = _label(store_catalog.badge(entry.source), "source-badge", wrap=False)
        if entry.source == store_catalog.SOURCE_FLATPAK:
            add_class(badge, "unscanned")
        source.pack_start(badge, False, False, 0)
        source.pack_start(_label(store_catalog.source_note(entry.source), "body-muted"), True, True, 0)
        self.detail.pack_start(source, False, False, 0)
        self.detail.pack_start(_label("Packages: " + ", ".join(entry.packages), "caption", selectable=True),
                               False, False, 0)

        facts = Gtk.Grid(column_spacing=16, row_spacing=6)
        for row, (key, title, start) in enumerate((("download", "Download", "Checking\u2026"),
                                                   ("disk", "Disk space", "Checking\u2026"),
                                                   ("login", "Starts at login", "Known after install"))):
            facts.attach(_label(title, "caption", wrap=False), 0, row, 1, 1)
            value = _label(start, None)
            facts.attach(value, 1, row, 1, 1)
            widgets[key] = value
        self.detail.pack_start(facts, False, False, 0)

        self.detail.pack_start(_label("Permissions", "section-title", wrap=False), False, False, 0)
        chips = Gtk.FlowBox()
        chips.set_selection_mode(Gtk.SelectionMode.NONE)
        chips.set_max_children_per_line(6)
        chips.set_homogeneous(False)
        chips.set_halign(Gtk.Align.START)       # natural width: no extra space spread between the chips
        chips.set_column_spacing(4)
        chips.set_row_spacing(4)
        widgets["chips"] = chips
        self.detail.pack_start(chips, False, False, 0)
        widgets["flathub_note"] = _label("", "caption")
        widgets["flathub_note"].set_no_show_all(True)
        self.detail.pack_start(widgets["flathub_note"], False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        install = Gtk.Button(label="Install")
        add_class(install, "action-button")
        add_class(install, "primary")
        install.connect("clicked", lambda _b: self.install(entry))
        remove = Gtk.Button(label="Remove\u2026")
        add_class(remove, "action-button")
        remove.connect("clicked", lambda _b: self.remove(entry))
        install.set_no_show_all(True)   # _update_actions() owns their visibility, show_all() must not undo it
        remove.set_no_show_all(True)
        actions.pack_start(install, False, False, 0)
        actions.pack_start(remove, False, False, 0)
        widgets["install"], widgets["remove"] = install, remove
        self.detail.pack_start(actions, False, False, 0)
        widgets["reason"] = _label("", "flag-text")
        widgets["reason"].set_no_show_all(True)
        widgets["status"] = _label("", "status-text")
        widgets["status"].set_no_show_all(True)
        self.detail.pack_start(widgets["reason"], False, False, 0)
        self.detail.pack_start(widgets["status"], False, False, 0)

        self.detail.show_all()
        self.stack.set_visible_child_name("detail")
        self.search.hide()
        self.category_row.hide()
        self._update_actions()          # after show_all(): it decides which of Install / Remove is shown
        self._load_facts(entry)
        (install if install.get_visible() and install.get_sensitive() else back).grab_focus()

    def go_back(self):
        self.current = None
        self.stack.set_visible_child_name("grid")
        self.search.show()
        self.category_row.show()

    def _update_actions(self):
        entry, widgets = self.current, self._detail_widgets
        if entry is None or not widgets:
            return
        state = self._state(entry)
        ok, why = self.services.prerequisite(entry.source)
        widgets["install"].set_visible(state != "installed")
        widgets["install"].set_label("Finish installing" if state == "partial" else "Install")
        widgets["install"].set_sensitive(ok)
        widgets["remove"].set_visible(state != "absent")
        widgets["reason"].set_text("" if ok or state == "installed" else why)
        widgets["reason"].set_visible(bool(widgets["reason"].get_text()))
        if state == "installed":
            self._load_login(entry)

    def _set_status(self, text):
        status = self._detail_widgets.get("status")
        if status is not None:
            status.set_text(text)
            status.set_visible(bool(text))

    def _fill_chips(self, permissions, note=""):
        chips = self._detail_widgets["chips"]
        for child in chips.get_children():
            chips.remove(child)
        if permissions is None:
            chips.add(_label("Unknown", "caption", wrap=False))
        elif not permissions:
            chips.add(_label("None beyond showing a window", "caption", wrap=False))
        for permission in permissions or []:
            chip = _label(permission.text, "perm-chip", wrap=False)
            chip.set_halign(Gtk.Align.START)
            if permission.broad:
                add_class(chip, "broad")
            chips.add(chip)
        chips.show_all()
        flathub_note = self._detail_widgets["flathub_note"]
        flathub_note.set_text(note)
        flathub_note.set_visible(bool(note))

    def _load_facts(self, entry):
        widgets = self._detail_widgets
        if entry.source == store_catalog.SOURCE_PACMAN:
            self._fill_chips([store_actions.Permission(NOT_SANDBOXED)])

            def apply_pacman(ok, result):
                if self.current is not entry or not ok:
                    if self.current is entry:
                        widgets["download"].set_text("Unknown")
                        widgets["disk"].set_text("Unknown")
                    return
                count, download = result["count"], result["download"]
                if download is None:
                    widgets["download"].set_text("Unknown")
                elif count == 0:
                    widgets["download"].set_text("Nothing to download")
                else:
                    widgets["download"].set_text(f"{store_actions.human_size(download)} in {count} package"
                                                 f"{'' if count == 1 else 's'}, dependencies included")
                disk = result["installed"]
                widgets["disk"].set_text("Unknown" if disk is None else
                                         f"{store_actions.human_size(disk)} for the app itself")
            self.services.run_job("detail", lambda: self.services.pacman_sizes(entry.packages), apply_pacman)
            return

        def apply_flatpak(ok, result):
            if self.current is not entry:
                return
            if not ok:
                result = {"download": None, "installed": None, "permissions": None}
            widgets["download"].set_text(store_actions.human_size(result["download"]))
            widgets["disk"].set_text(store_actions.human_size(result["installed"]))
            note = ""
            if result["permissions"] is None:
                note = ("Flathub has not been added to your account yet, so its size and permissions cannot be read. "
                        "Install adds it for your account only.")
            self._fill_chips(result["permissions"], note)
        self.services.run_job("detail", lambda: self.services.flatpak_details(entry.packages[0]), apply_flatpak)

    def _load_login(self, entry):
        widgets = self._detail_widgets

        def work():
            if entry.source == store_catalog.SOURCE_PACMAN:
                return store_actions.autostart_entries(self.services.pacman_files(entry.packages))
            return store_actions.autostart_entries(home=self.services.home(), flatpak_id=entry.packages[0])

        def apply(ok, result):
            if self.current is not entry or not ok:
                return
            widgets["login"].set_text("Yes: it adds an autostart entry" if result else "No autostart entry found")
        self.services.run_job("login", work, apply)

    # -- install and remove (only from their buttons) -------------------------------------------------------------

    def _launch(self, argv, message):
        try:
            handle = self.services.open_terminal(argv)
        except OSError as error:
            self._set_status(f"Could not open the terminal: {error}")
            return False
        self._set_status(message)
        self.services.watch(handle, self._after_terminal)
        return True

    def _after_terminal(self):
        self._set_status("")
        self.refresh()

    def install(self, entry):
        ok, why = self.services.prerequisite(entry.source)
        if not ok:
            self._set_status(why)
            return False
        return self._launch(store_actions.install_argv([entry]),
                            "A terminal opened. Follow it there; this page updates when it closes.")

    def remove(self, entry):
        def work():
            return self.services.data_dirs(entry)

        def apply(ok, folders):
            if self.current is not entry:
                return
            choice = self.services.confirm_remove(self.get_toplevel(), entry, folders if ok else [])
            if choice == CHOICE_CANCEL:
                return
            forget = choice == CHOICE_DELETE
            if entry.source == store_catalog.SOURCE_PACMAN:
                argv = store_actions.remove_argv(entry, self.pacman_installed, forget)
            else:
                argv = store_actions.remove_argv(entry, forget_data=forget)
            self._launch(argv, "A terminal opened. Follow it there; this page updates when it closes.")
        self.services.run_job("remove", work, apply)


class PacksPage(Gtk.Box):
    """The six starter packs. Nothing is ticked; Install selected is the only thing that installs."""

    def __init__(self, services):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_border_width(16)
        self.services = services
        self.pacman_installed = set()
        self.flatpak_installed = set()
        self.pack_start(_label("Packs are suggestions. Nothing is ticked and nothing installs until you press "
                               "Install selected. You can also install one app at a time from Browse.", "body-muted"),
                        False, False, 0)
        self.picker = PackPicker(on_change=self._changed)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(self.picker)
        self.pack_start(scrolled, True, True, 0)
        self.reason = _label("", "flag-text")
        self.reason.set_no_show_all(True)
        self.pack_start(self.reason, False, False, 0)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.count = _label("Nothing selected", "body-muted", wrap=False)
        footer.pack_start(self.count, True, True, 0)
        self.install_btn = Gtk.Button(label="Install selected")
        add_class(self.install_btn, "action-button")
        self.install_btn.set_sensitive(False)
        self.install_btn.connect("clicked", lambda _b: self.install())
        footer.pack_end(self.install_btn, False, False, 0)
        self.pack_start(footer, False, False, 0)
        self.status = _label("", "status-text")
        self.status.set_no_show_all(True)
        self.pack_start(self.status, False, False, 0)

    def _changed(self, count):
        self.count.set_text("Nothing selected" if count == 0 else f"{count} selected")
        reason = ""
        for entry in self.picker.selected_entries():
            ok, why = self.services.prerequisite(entry.source)
            if not ok:
                reason = why
                break
        self.reason.set_text(reason)
        self.reason.set_visible(bool(reason))
        self.install_btn.set_sensitive(count > 0 and not reason)

    def refresh(self):
        def apply(ok, result):
            if ok:
                self.pacman_installed, self.flatpak_installed = result
            done = [e.id for e in store_catalog.ENTRIES
                    if store_actions.entry_state(e, self.pacman_installed, self.flatpak_installed) == "installed"]
            self.picker.set_installed(done)
        self.services.run_job("packs-installed", self.services.installed, apply)

    def install(self):
        entries = self.picker.selected_entries()
        if not entries:
            return False
        for entry in entries:                 # fail closed here too, not only by greying the button
            ok, why = self.services.prerequisite(entry.source)
            if not ok:
                self.status.set_text(why)
                self.status.set_visible(True)
                return False
        try:
            handle = self.services.open_terminal(store_actions.install_argv(entries))
        except OSError as error:
            self.status.set_text(f"Could not open the terminal: {error}")
            self.status.set_visible(True)
            return False
        self.status.set_text("A terminal opened. Follow it there; this page updates when it closes.")
        self.status.set_visible(True)
        self.picker.clear()
        self.services.watch(handle, self._after_terminal)
        return True

    def _after_terminal(self):
        self.status.set_visible(False)
        self.refresh()
