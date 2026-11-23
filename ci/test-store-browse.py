#!/usr/bin/env python3
"""Store Browse and Packs pages and the shared pack picker, on a real GTK window with a fake Services.

    xvfb-run -a dbus-run-session -- python ci/test-store-browse.py

Nothing real is touched: the fake Services records every terminal the pages ask for and runs "worker" jobs
synchronously. What is checked is the contract the person relies on: nothing is ticked, nothing installs until a
button is pressed, sources are labelled honestly, sizes and permissions are read or shown as Unknown, and a removal
never deletes data without being asked.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

GTK = Gtk.init_check()[0]

from darkos_shell import store_actions, store_browse, store_catalog  # noqa: E402
from darkos_shell.pack_picker import PackPicker  # noqa: E402

BANNED = ("best", "popular", "featured", "trending", "recommended", "sponsored", "advert", "sale")


class FakeServices(store_browse.Services):
    def __init__(self):
        super().__init__(shield_ready=True, flatpak_ready=True)
        self.terminals = []
        self.watched = []
        self.choice = store_browse.CHOICE_KEEP
        self.asked = []
        self.pacman_set, self.flatpak_set = set(), set()
        self.blocked = {}                     # source -> reason
        self.folders = []
        self.pacman_files_output = ""
        self.flatpak_result = {"download": 107800000, "installed": 360600000,
                               "permissions": [store_actions.Permission("Uses the network"),
                                               store_actions.Permission("Every file on this computer", True)]}
        self.terminal_error = None
        self.read_only_calls = []

    def prerequisite(self, source):
        why = self.blocked.get(source)
        return (False, why) if why else (True, "")

    def installed(self):
        self.read_only_calls.append("installed")
        return set(self.pacman_set), set(self.flatpak_set)

    def pacman_sizes(self, packages):
        self.read_only_calls.append(("sizes", tuple(packages)))
        return {"download": 123456789, "count": 4, "installed": 345678901}

    def flatpak_details(self, app_id):
        self.read_only_calls.append(("flatpak", app_id))
        return self.flatpak_result

    def pacman_files(self, packages):
        return self.pacman_files_output

    def data_dirs(self, entry):
        return list(self.folders)

    def run_job(self, key, work, apply):
        try:
            result = (True, work())
        except Exception as error:  # noqa: BLE001
            result = (False, str(error))
        apply(*result)

    def open_terminal(self, argv):
        if self.terminal_error:
            raise OSError(self.terminal_error)
        self.terminals.append(list(argv))
        return object()

    def watch(self, handle, callback):
        self.watched.append(callback)

    def confirm_remove(self, parent, entry, folders):
        self.asked.append((entry.id, list(folders)))
        return self.choice


def walk(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from walk(child)


def texts(widget):
    return [w.get_text() for w in walk(widget) if isinstance(w, Gtk.Label)]


def pump():
    for _ in range(20):
        GLib.MainContext.default().iteration(False)


@unittest.skipUnless(GTK, "no display (run under xvfb-run)")
class BrowseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gapp = Gtk.Application(application_id="org.darkos.StoreBrowseTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.gapp.register(None)

    def setUp(self):
        self.svc = FakeServices()
        self.page = store_browse.BrowsePage(self.svc)
        self.win = Gtk.ApplicationWindow(application=self.gapp)
        self.win.add(self.page)
        self.win.show_all()
        self.addCleanup(self.win.destroy)

    def card_ids(self):
        return [child.entry.id for child in self.page.flow.get_children()]

    def detail(self, entry_id):
        self.page.show_detail(store_catalog.get(entry_id))
        pump()
        return self.page._detail_widgets

    # -- the grid ----------------------------------------------------------------------------------------------------

    def test_opening_the_store_installs_nothing_and_only_reads(self):
        self.page.refresh()
        pump()
        self.assertEqual(self.svc.terminals, [])
        self.assertEqual(self.svc.read_only_calls, ["installed"])
        self.assertEqual(len(self.card_ids()), len(store_catalog.ENTRIES))

    def test_every_card_is_the_same_size_and_nothing_is_promoted(self):
        sizes = {(child.get_child().get_size_request()) for child in self.page.flow.get_children()}
        self.assertEqual(len(sizes), 1, "an even grid: no hero card, no bigger tiles")
        everything = " ".join(texts(self.page)).lower()
        for word in BANNED:
            self.assertNotIn(word, everything)

    def test_flathub_cards_say_unscanned_and_arch_cards_do_not(self):
        for child in self.page.flow.get_children():
            labels = [w for w in walk(child) if isinstance(w, Gtk.Label) and w.get_style_context().has_class("source-badge")]
            self.assertEqual(len(labels), 1)
            flat = child.entry.source == store_catalog.SOURCE_FLATPAK
            self.assertEqual("Unscanned" in labels[0].get_text(), flat, child.entry.id)
            self.assertEqual(labels[0].get_style_context().has_class("unscanned"), flat)

    def test_category_buttons_filter_and_exactly_one_is_always_chosen(self):
        self.page._category_buttons["games"].set_active(True)
        self.assertEqual(set(self.card_ids()), {e.id for e in store_catalog.in_category("games")})
        active = [k for k, b in self.page._category_buttons.items() if b.get_active()]
        self.assertEqual(active, ["games"])
        self.page._category_buttons["games"].set_active(False)           # cannot leave none chosen
        self.assertTrue(self.page._category_buttons["games"].get_active())
        self.page._category_buttons[""].set_active(True)
        self.assertEqual(len(self.card_ids()), len(store_catalog.ENTRIES))

    def test_search_filters_cards_and_says_when_nothing_matches(self):
        self.page.search.set_text("photo")
        self.page._on_search(self.page.search)
        self.assertEqual(set(self.card_ids()), {"gimp", "darktable", "simple-scan"})
        self.assertFalse(self.page.empty.get_visible())
        self.page.search.set_text("zzzz nothing")
        self.page._on_search(self.page.search)
        self.assertEqual(self.card_ids(), [])
        self.assertTrue(self.page.empty.get_visible())
        self.assertIn("Search tab", self.page.empty.get_text())

    def test_cards_show_installed_state_from_what_is_really_installed(self):
        self.svc.pacman_set = {"steam", "wine"}           # wine is only one of its four packages
        self.svc.flatpak_set = {"net.ankiweb.Anki"}
        self.page.refresh()
        pump()
        state = {entry_id: label.get_text() for entry_id, (_c, label) in self.page._card_state.items()}
        self.assertEqual(state["steam"], "Installed")
        self.assertEqual(state["wine"], "Partly installed")
        self.assertEqual(state["anki"], "Installed")
        self.assertEqual(state["gimp"], "")

    def test_blocked_shield_is_stated_on_the_page(self):
        svc = FakeServices()
        svc.blocked["pacman"] = "Shield's scanner is not available, so Arch apps cannot be checked."
        page = store_browse.BrowsePage(svc)
        self.assertTrue(page.notice.get_visible())
        self.assertIn("Shield", page.notice.get_text())
        self.assertFalse(self.page.notice.get_visible())

    # -- the detail page ---------------------------------------------------------------------------------------------

    def test_an_arch_app_shows_real_sizes_and_says_it_is_not_sandboxed(self):
        widgets = self.detail("gimp")
        self.assertEqual(widgets["download"].get_text(), "117.7 MiB in 4 packages, dependencies included")
        self.assertEqual(widgets["disk"].get_text(), "329.7 MiB for the app itself")
        chips = [c.get_child().get_text() for c in widgets["chips"].get_children()]
        self.assertEqual(chips, [store_browse.NOT_SANDBOXED])
        self.assertEqual(widgets["login"].get_text(), "Known after install", "not guessed before install")
        self.assertIn(("sizes", ("gimp",)), self.svc.read_only_calls)

    def test_sizes_that_cannot_be_read_say_unknown(self):
        self.svc.pacman_sizes = lambda packages: {"download": None, "count": None, "installed": None}
        widgets = self.detail("gimp")
        self.assertEqual((widgets["download"].get_text(), widgets["disk"].get_text()), ("Unknown", "Unknown"))

    def test_a_flatpak_app_shows_its_real_permissions_and_flags_broad_ones(self):
        widgets = self.detail("anki")
        self.assertEqual(widgets["download"].get_text(), "102.8 MiB")
        chips = {c.get_child().get_text(): c.get_child().get_style_context().has_class("broad")
                 for c in widgets["chips"].get_children()}
        self.assertEqual(chips, {"Uses the network": False, "Every file on this computer": True})
        self.assertFalse(widgets["flathub_note"].get_visible())
        self.assertIn("Unscanned", " ".join(texts(self.page.detail)))

    def test_without_flathub_a_flatpak_app_says_unknown_and_why(self):
        self.svc.flatpak_result = {"download": None, "installed": None, "permissions": None}
        widgets = self.detail("anki")
        self.assertEqual((widgets["download"].get_text(), widgets["disk"].get_text()), ("Unknown", "Unknown"))
        self.assertEqual([c.get_child().get_text() for c in widgets["chips"].get_children()], ["Unknown"])
        self.assertTrue(widgets["flathub_note"].get_visible())
        self.assertIn("Install adds it for your account only", widgets["flathub_note"].get_text())

    def test_starts_at_login_is_read_from_the_installed_package(self):
        self.svc.pacman_set = {"gimp"}
        self.svc.pacman_files_output = "gimp /etc/xdg/autostart/gimp-helper.desktop\ngimp /usr/bin/gimp\n"
        self.page.refresh()
        widgets = self.detail("gimp")
        self.assertEqual(widgets["login"].get_text(), "Yes: it adds an autostart entry")
        self.svc.pacman_files_output = "gimp /usr/bin/gimp\n"
        widgets = self.detail("gimp")
        self.assertEqual(widgets["login"].get_text(), "No autostart entry found")

    def test_install_and_remove_buttons_follow_the_real_state(self):
        widgets = self.detail("gimp")
        self.assertTrue(widgets["install"].get_visible())
        self.assertFalse(widgets["remove"].get_visible(), "nothing to remove yet")
        self.svc.pacman_set = {"wine"}                    # a partial install offers both
        self.page.refresh()
        widgets = self.detail("wine")
        self.assertEqual(widgets["install"].get_label(), "Finish installing")
        self.assertTrue(widgets["install"].get_visible() and widgets["remove"].get_visible())
        self.svc.pacman_set = set(store_catalog.get("wine").packages)
        self.page.refresh()
        widgets = self.detail("wine")
        self.assertFalse(widgets["install"].get_visible())
        self.assertTrue(widgets["remove"].get_visible())

    def test_install_opens_the_visible_terminal_once_with_exactly_this_app(self):
        gimp = store_catalog.get("gimp")
        self.detail("gimp")
        self.assertEqual(self.svc.terminals, [], "showing the page installs nothing")
        self.assertTrue(self.page.install(gimp))
        self.assertEqual(self.svc.terminals, [store_actions.install_argv([gimp])])
        self.assertIn("terminal opened", self.page._detail_widgets["status"].get_text())
        self.assertEqual(len(self.svc.watched), 1)
        self.svc.watched[0]()                                         # the terminal closed
        self.assertEqual(self.page._detail_widgets["status"].get_text(), "")
        self.assertEqual(self.svc.read_only_calls.count("installed"), 1, "the page re-reads what is installed")

    def test_a_blocked_source_disables_install_and_says_why(self):
        self.svc.blocked["pacman"] = "Shield's scanner is not available."
        widgets = self.detail("gimp")
        self.assertFalse(widgets["install"].get_sensitive())
        self.assertIn("Shield", widgets["reason"].get_text())
        self.assertTrue(widgets["reason"].get_visible())
        self.assertFalse(self.page.install(store_catalog.get("gimp")), "even called directly, it fails closed")
        self.assertEqual(self.svc.terminals, [])

    def test_a_terminal_that_cannot_start_is_reported(self):
        self.svc.terminal_error = "no such file"
        self.detail("gimp")
        self.assertFalse(self.page.install(store_catalog.get("gimp")))
        self.assertIn("Could not open the terminal", self.page._detail_widgets["status"].get_text())

    # -- remove and the data prompt ----------------------------------------------------------------------------------

    def remove_with(self, entry_id, choice, folders=()):
        entry = store_catalog.get(entry_id)
        self.svc.pacman_set = set(entry.packages) if entry.source == "pacman" else set()
        self.svc.flatpak_set = set(entry.packages) if entry.source == "flatpak" else set()
        self.svc.folders = list(folders)
        self.svc.choice = choice
        self.page.refresh()
        self.detail(entry_id)
        self.svc.terminals.clear()
        self.page.remove(entry)
        return self.svc.terminals

    def test_remove_asks_what_to_do_with_the_data_and_cancel_does_nothing(self):
        folders = [(Path("/home/u/.local/share/Steam"), 5 * 1024 ** 3, True)]
        terminals = self.remove_with("steam", store_browse.CHOICE_CANCEL, folders)
        self.assertEqual(self.svc.asked, [("steam", folders)])
        self.assertEqual(terminals, [])

    def test_remove_keeping_data_never_asks_pacman_to_delete_any(self):
        steam = store_catalog.get("steam")
        terminals = self.remove_with("steam", store_browse.CHOICE_KEEP,
                                     [(Path("/home/u/.steam"), 10, True)])
        self.assertEqual(terminals, [store_actions.remove_argv(steam, {"steam"}, forget_data=False)])
        self.assertEqual(terminals[0][6], "0")

    def test_remove_and_delete_data_is_a_separate_explicit_choice(self):
        steam = store_catalog.get("steam")
        terminals = self.remove_with("steam", store_browse.CHOICE_DELETE, [(Path("/home/u/.steam"), 10, True)])
        self.assertEqual(terminals, [store_actions.remove_argv(steam, {"steam"}, forget_data=True)])
        self.assertEqual(terminals[0][6], "1")

    def test_removing_a_flatpak_asks_flatpak_to_delete_its_data_only_when_chosen(self):
        anki = store_catalog.get("anki")
        terminals = self.remove_with("anki", store_browse.CHOICE_DELETE)
        self.assertEqual(terminals, [store_actions.remove_argv(anki, forget_data=True)])
        terminals = self.remove_with("anki", store_browse.CHOICE_KEEP)
        self.assertEqual(terminals, [store_actions.remove_argv(anki, forget_data=False)])


@unittest.skipUnless(GTK, "no display (run under xvfb-run)")
class PacksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gapp = Gtk.Application(application_id="org.darkos.StorePacksTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.gapp.register(None)

    def setUp(self):
        self.svc = FakeServices()
        self.page = store_browse.PacksPage(self.svc)
        self.win = Gtk.ApplicationWindow(application=self.gapp)
        self.win.add(self.page)
        self.win.show_all()
        self.addCleanup(self.win.destroy)

    def tick(self, entry_id, pack_index=0, state=True):
        self.page.picker._checks[entry_id][pack_index].set_active(state)

    def test_opens_with_nothing_ticked_and_nothing_to_press(self):
        self.assertEqual(self.page.picker.selected_count(), 0)
        self.assertFalse(self.page.install_btn.get_sensitive())
        self.assertEqual(self.page.count.get_text(), "Nothing selected")
        self.assertEqual(self.svc.terminals, [])
        self.assertTrue(all(not c.get_active() for checks in self.page.picker._checks.values() for c in checks))

    def test_six_packs_are_shown_in_order(self):
        headings = [t for t in texts(self.page.picker) if t in {p.name for p in store_catalog.PACKS}]
        self.assertEqual(headings, [p.name for p in store_catalog.PACKS])

    def test_an_app_in_several_packs_is_one_choice(self):
        checks = self.page.picker._checks["libreoffice"]
        self.assertEqual(len(checks), 3, "Everyday, Student and Office")
        checks[0].set_active(True)
        self.assertTrue(all(c.get_active() for c in checks))
        self.assertEqual(self.page.picker.selected_count(), 1)
        checks[2].set_active(False)
        self.assertFalse(any(c.get_active() for c in checks))

    def test_select_all_and_clear_per_pack(self):
        picker = self.page.picker
        pack = store_catalog.pack("developer")
        button = [b for p, b in picker._pack_buttons if p.id == "developer"][0]
        self.assertEqual(button.get_label(), "Select all")
        button.clicked()
        self.assertEqual({e.id for e in picker.selected_entries()}, set(pack.entries))
        self.assertEqual(button.get_label(), "Clear")
        self.assertEqual(self.page.count.get_text(), f"{len(pack.entries)} selected")
        button.clicked()
        self.assertEqual(picker.selected_count(), 0)

    def test_install_selected_opens_one_terminal_with_exactly_the_ticked_apps(self):
        self.tick("gimp")
        self.tick("anki")
        self.assertTrue(self.page.install_btn.get_sensitive())
        self.assertEqual(self.page.count.get_text(), "2 selected")
        self.page.install_btn.clicked()
        wanted = [store_catalog.get("gimp"), store_catalog.get("anki")]
        self.assertEqual(self.svc.terminals, [store_actions.install_argv(wanted)])
        self.assertEqual(self.page.picker.selected_count(), 0, "cleared, so a second click cannot repeat it")
        self.assertEqual(len(self.svc.watched), 1)

    def test_a_blocked_source_blocks_the_install_and_says_why(self):
        self.svc.blocked["pacman"] = "Shield's scanner is not available."
        self.tick("anki")                                   # Flathub is fine
        self.assertTrue(self.page.install_btn.get_sensitive())
        self.tick("gimp")                                   # an Arch app needs the gate
        self.assertFalse(self.page.install_btn.get_sensitive())
        self.assertIn("Shield", self.page.reason.get_text())
        self.assertFalse(self.page.install(), "even called directly, nothing is installed past the block")
        self.assertEqual(self.svc.terminals, [])
        self.tick("gimp", state=False)
        self.assertTrue(self.page.install_btn.get_sensitive())
        self.assertEqual(self.page.reason.get_text(), "")

    def test_installed_apps_cannot_be_ticked_again(self):
        self.svc.pacman_set = {"gimp"}
        self.page.refresh()
        pump()
        check = self.page.picker._checks["gimp"][0]
        self.assertFalse(check.get_sensitive())
        self.assertFalse(check.get_active())
        button = [b for p, b in self.page.picker._pack_buttons if p.id == "creator"][0]
        button.clicked()
        self.assertNotIn("gimp", {e.id for e in self.page.picker.selected_entries()})
        self.assertEqual(self.page.picker.selected_count(), len(store_catalog.pack("creator").entries) - 1)

    def test_a_terminal_that_cannot_start_keeps_the_picks(self):
        self.svc.terminal_error = "no such file"
        self.tick("gimp")
        self.assertFalse(self.page.install())
        self.assertIn("Could not open the terminal", self.page.status.get_text())
        self.assertEqual(self.page.picker.selected_count(), 1)


@unittest.skipUnless(GTK, "no display (run under xvfb-run)")
class PickerStandalone(unittest.TestCase):
    def test_the_picker_alone_runs_nothing_and_reports_changes(self):
        seen = []
        picker = PackPicker(on_change=seen.append)
        self.assertEqual(picker.selected_entries(), [])
        picker._checks["go"][0].set_active(True)
        picker._checks["rust"][0].set_active(True)
        self.assertEqual(seen, [1, 2])
        self.assertEqual([e.id for e in picker.selected_entries()], ["go", "rust"], "catalogue order, once each")
        picker.clear()
        self.assertEqual(seen[-1], 0)
        self.assertEqual(picker.selected_entries(), [])

    def test_accessible_names_say_what_each_choice_is(self):
        picker = PackPicker()
        name = picker._checks["steam"][0].get_accessible().get_name()
        self.assertIn("Steam", name)
        self.assertIn("Arch repositories", name)
        name = picker._checks["anki"][0].get_accessible().get_name()
        self.assertIn("Unscanned", name)


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
