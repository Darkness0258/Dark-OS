"""The starter-pack picker: six packs, every app unticked. It installs nothing itself.

Shared by the Store (Packs tab) and Welcome ("Pick your extras"). The caller reads
selected_entries() and decides what to do with them; nothing in here runs a command, so
opening the picker can never change the system.

An app that is in more than one pack (LibreOffice is in three) is one choice: ticking it in
one pack ticks it everywhere, so what the footer counts is what will be installed.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from darkos_shell import store_catalog  # noqa: E402
from darkos_shell.app_kit import add_class  # noqa: E402


def _label(text, css_class, wrap=True):
    label = Gtk.Label(label=text)
    label.set_xalign(0.0)
    label.set_line_wrap(wrap)
    add_class(label, css_class)
    return label


class PackPicker(Gtk.Box):
    """Six pack sections of checkboxes. `on_change(count)` runs after every tick or untick."""

    def __init__(self, on_change=None, installed=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.on_change = on_change
        self._syncing = False
        self._checks = {}          # entry id -> [Gtk.CheckButton, ...] (one per pack the entry is in)
        self._installed_labels = {}  # entry id -> [Gtk.Label, ...] shown only for installed apps
        self._names = {}           # Gtk.CheckButton -> its accessible name without the state
        self._pack_buttons = []    # (pack, Gtk.Button)
        self._installed = set(installed or ())
        for pack in store_catalog.recommend():
            self.pack_start(self._build_pack(pack), False, False, 0)

    # -- building -------------------------------------------------------------------------------------------------

    def _build_pack(self, pack):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(card, "card")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.pack_start(_label(pack.name, "section-title", wrap=False), False, False, 0)
        titles.pack_start(_label(pack.tagline, "body-muted"), False, False, 0)
        header.pack_start(titles, True, True, 0)
        toggle = Gtk.Button(label="Select all")
        add_class(toggle, "action-button")
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.connect("clicked", lambda _b, p=pack: self._toggle_pack(p))
        toggle.get_accessible().set_name(f"Select all apps in the {pack.name} pack")
        header.pack_end(toggle, False, False, 0)
        self._pack_buttons.append((pack, toggle))
        card.pack_start(header, False, False, 0)
        for entry in store_catalog.pack_entries(pack.id):
            card.pack_start(self._build_row(entry), False, False, 0)
        return card

    def _build_row(self, entry):
        check = Gtk.CheckButton()
        check.set_active(False)                       # opt-in: nothing is ever pre-ticked
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.pack_start(_label(entry.name, "lead", wrap=False), False, False, 0)
        text.pack_start(_label(entry.summary, "caption"), False, False, 0)
        row.pack_start(text, True, True, 0)
        installed = _label("Installed", "caption", wrap=False)
        installed.set_no_show_all(True)
        installed.set_visible(entry.id in self._installed)
        self._installed_labels.setdefault(entry.id, []).append(installed)
        row.pack_end(installed, False, False, 0)
        badge = _label(store_catalog.badge(entry.source), "source-badge", wrap=False)
        if entry.source == store_catalog.SOURCE_FLATPAK:
            add_class(badge, "unscanned")
        badge.set_valign(Gtk.Align.CENTER)
        row.pack_end(badge, False, False, 0)
        check.add(row)
        self._names[check] = f"{entry.name}: {entry.summary} {store_catalog.badge(entry.source)}"
        check.get_accessible().set_name(self._names[check])
        check.connect("toggled", lambda button, e=entry: self._on_toggled(e, button))
        self._checks.setdefault(entry.id, []).append(check)
        return check

    # -- state ----------------------------------------------------------------------------------------------------

    def _on_toggled(self, entry, button):
        if self._syncing:
            return
        self._syncing = True
        try:
            for other in self._checks[entry.id]:
                if other is not button:
                    other.set_active(button.get_active())
        finally:
            self._syncing = False
        self._refresh_pack_buttons()
        if self.on_change:
            self.on_change(self.selected_count())

    def _toggle_pack(self, pack):
        ids = [i for i in pack.entries if i not in self._installed]
        wanted = not all(self._checks[i][0].get_active() for i in ids)
        self._syncing = True
        try:
            for entry_id in ids:
                for check in self._checks[entry_id]:
                    check.set_active(wanted)
        finally:
            self._syncing = False
        self._refresh_pack_buttons()
        if self.on_change:
            self.on_change(self.selected_count())

    def _refresh_pack_buttons(self):
        for pack, button in self._pack_buttons:
            ids = [i for i in pack.entries if i not in self._installed]
            all_ticked = bool(ids) and all(self._checks[i][0].get_active() for i in ids)
            button.set_label("Clear" if all_ticked else "Select all")
            button.set_sensitive(bool(ids))

    # -- what the caller reads ------------------------------------------------------------------------------------

    def selected_entries(self):
        """Ticked apps, each once, in catalogue order."""
        return [entry for entry in store_catalog.ENTRIES
                if entry.id in self._checks and self._checks[entry.id][0].get_active()]

    def selected_count(self):
        return len(self.selected_entries())

    def clear(self):
        self._syncing = True
        try:
            for checks in self._checks.values():
                for check in checks:
                    check.set_active(False)
        finally:
            self._syncing = False
        self._refresh_pack_buttons()
        if self.on_change:
            self.on_change(0)

    def set_installed(self, installed_ids):
        """Tell the picker which apps are already installed: they cannot be ticked, so they never get reinstalled."""
        self._installed = set(installed_ids)
        for entry_id, checks in self._checks.items():
            done = entry_id in self._installed
            for label in self._installed_labels.get(entry_id, ()):
                label.set_visible(done)
            for check in checks:
                if done:
                    check.set_active(False)
                check.set_sensitive(not done)
                check.get_accessible().set_name(self._names[check] + (". Already installed" if done else ""))
        self._refresh_pack_buttons()
        if self.on_change:
            self.on_change(self.selected_count())
