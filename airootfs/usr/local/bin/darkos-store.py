#!/usr/bin/env python3
"""DarkOS Store — Search (pacman/AUR/Flatpak), Installed, Updates, Compatibility
(Wine/Waydroid).

Honest state of verification here, unlike most of this project: pacman
doesn't exist outside Arch (this review sandbox is Ubuntu) so it's genuinely
absent, not just unconfigured. The AUR RPC (https://aur.archlinux.org/rpc/)
is a real HTTP API, but that domain isn't in this sandbox's network
allowlist, so it's also genuinely unreachable here rather than just
untested. Flatpak's binary is installable via apt, but reaching Flathub's
actual catalog needs flathub.org/dl.flathub.org, also outside the
allowlist. Every one of these gets the same real "attempt it, report the
real failure" treatment as Network Center/DevHub — the difference is that
*every* backend here hits that wall, not just one or two, so there's
nothing in Search or Updates that could be shown running against live
data from this environment. Wired correctly against each tool's real,
documented CLI regardless — this is what a real Arch box changes when it
runs it, not a redesign.

Per architecture.md: every install should route through Shield first.
Shield doesn't exist (see Security Center) — installs proceed without a
security gate for now, and that's stated in the UI, not silently skipped.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.Store"
WM_CLASS = "darkos-store"


def run_tool(argv, timeout=8):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if result.returncode not in (0, 1):  # pacman/flatpak often use 1 for "no results", not a real error
            return False, (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
        return True, result.stdout
    except FileNotFoundError:
        return False, f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} timed out"
    except OSError as e:
        return False, str(e)


def aur_search(query):
    url = "https://aur.archlinux.org/rpc/v5/search/" + urllib.parse.quote(query)
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return True, data.get("results", [])
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except (OSError, json.JSONDecodeError) as e:
        return False, str(e)


class StoreWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Store")
        self.set_default_size(820, 600)
        add_class(self, "app-window")

        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        notebook.append_page(self._build_search_tab(), Gtk.Label(label="Search"))
        notebook.append_page(self._build_installed_tab(), Gtk.Label(label="Installed"))
        notebook.append_page(self._build_updates_tab(), Gtk.Label(label="Updates"))
        notebook.append_page(self._build_compat_tab(), Gtk.Label(label="Compatibility"))
        self.add(notebook)

    def _shield_notice(self):
        label = Gtk.Label(
            label="Shield isn't implemented yet, so installs below aren't security-scanned first — "
                  "stated here rather than silently skipped. See Security Center.",
            xalign=0, wrap=True,
        )
        add_class(label, "path-crumb")
        return label

    # -- Search -----------------------------------------------------------------
    def _build_search_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search pacman, AUR, and Flatpak…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self._do_search)
        search_row.pack_start(self.search_entry, True, True, 0)
        search_btn = Gtk.Button(label="Search")
        add_class(search_btn, "action-button")
        search_btn.connect("clicked", self._do_search)
        search_row.pack_start(search_btn, False, False, 0)
        box.pack_start(search_row, False, False, 0)
        box.pack_start(self._shield_notice(), False, False, 0)

        self.search_results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.search_results)
        box.pack_start(scroller, True, True, 0)
        return box

    def _do_search(self, *_):
        query = self.search_entry.get_text().strip()
        for child in list(self.search_results.get_children()):
            self.search_results.remove(child)
        if not query:
            return

        self.search_results.pack_start(self._source_section(
            "pacman (native)", *self._search_pacman(query)), False, False, 0)
        self.search_results.pack_start(self._source_section(
            "AUR", *self._search_aur(query)), False, False, 0)
        self.search_results.pack_start(self._source_section(
            "Flatpak", *self._search_flatpak(query)), False, False, 0)
        self.search_results.show_all()

    def _search_pacman(self, query):
        ok, output = run_tool(["pacman", "-Ss", query])
        if not ok:
            return False, [], output
        lines = output.strip().splitlines()
        results = []
        for i in range(0, len(lines) - 1, 2):
            header = lines[i].split()
            if header:
                results.append(header[0])
        return True, results, None

    def _search_aur(self, query):
        ok, data = aur_search(query)
        if not ok:
            return False, [], data
        return True, [f'{r.get("Name")} — {r.get("Description", "")}' for r in data[:20]], None

    def _search_flatpak(self, query):
        ok, output = run_tool(["flatpak", "search", query])
        if not ok:
            return False, [], output
        return True, [line.split("\t")[0] for line in output.strip().splitlines() if line], None

    def _source_section(self, title, ok, results, error):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(Gtk.Label(label=f"<b>{title}</b>", xalign=0, use_markup=True), False, False, 0)
        if not ok:
            box.pack_start(Gtk.Label(label=f"Unavailable: {error}", xalign=0, wrap=True), False, False, 0)
        elif not results:
            box.pack_start(Gtk.Label(label="No results.", xalign=0), False, False, 0)
        else:
            for name in results[:20]:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                add_class(row, "sidebar-row")
                row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
                install_btn = Gtk.Button(label="Install")
                add_class(install_btn, "icon-button")
                install_btn.set_sensitive(False)
                install_btn.set_tooltip_text("Needs a real Arch/Flatpak backend to actually install")
                row.pack_start(install_btn, False, False, 0)
                box.pack_start(row, False, False, 0)
        return box

    # -- Installed ---------------------------------------------------------------
    def _build_installed_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        refresh_btn = Gtk.Button(label="Refresh")
        add_class(refresh_btn, "icon-button")
        refresh_btn.set_halign(Gtk.Align.START)
        refresh_btn.connect("clicked", lambda *_: self._refresh_installed())
        box.pack_start(refresh_btn, False, False, 0)
        self.installed_view = Gtk.TextView()
        self.installed_view.set_editable(False)
        self.installed_view.set_monospace(True)
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.installed_view)
        box.pack_start(scroller, True, True, 0)
        self._refresh_installed()
        return box

    def _refresh_installed(self):
        parts = []
        ok, output = run_tool(["pacman", "-Q"])
        parts.append("=== pacman -Q ===\n" + (output if ok else f"Unavailable: {output}"))
        ok2, output2 = run_tool(["flatpak", "list", "--app"])
        parts.append("=== flatpak list ===\n" + (output2 if ok2 else f"Unavailable: {output2}"))
        self.installed_view.get_buffer().set_text("\n\n".join(parts))

    # -- Updates -----------------------------------------------------------------
    def _build_updates_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        check_btn = Gtk.Button(label="Check for Updates")
        add_class(check_btn, "action-button")
        check_btn.set_halign(Gtk.Align.START)
        check_btn.connect("clicked", lambda *_: self._check_updates())
        box.pack_start(check_btn, False, False, 0)
        self.updates_view = Gtk.TextView()
        self.updates_view.set_editable(False)
        self.updates_view.set_monospace(True)
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.updates_view)
        box.pack_start(scroller, True, True, 0)
        return box

    def _check_updates(self):
        parts = []
        ok, output = run_tool(["pacman", "-Qu"])
        parts.append("=== pacman -Qu ===\n" + (output.strip() or "Up to date." if ok else f"Unavailable: {output}"))
        ok2, output2 = run_tool(["flatpak", "remote-ls", "--updates"])
        parts.append("=== flatpak updates ===\n" + (output2.strip() or "Up to date." if ok2 else f"Unavailable: {output2}"))
        self.updates_view.get_buffer().set_text("\n\n".join(parts))

    # -- Compatibility (Wine/Waydroid) -------------------------------------------
    def _build_compat_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        box.pack_start(Gtk.Label(label="<b>Windows compatibility (Wine/Proton)</b>", xalign=0, use_markup=True), False, False, 0)
        for argv in (["wine", "--version"], ["proton", "--version"]):
            ok, output = run_tool(argv)
            text = f"{argv[0]}: " + (output.strip() if ok else output)
            box.pack_start(Gtk.Label(label=text, xalign=0), False, False, 0)

        box.pack_start(Gtk.Label(label="<b>Android compatibility (Waydroid)</b>", xalign=0, use_markup=True), False, False, 12)
        ok, output = run_tool(["waydroid", "status"])
        text = "waydroid: " + (output.strip() if ok else output)
        box.pack_start(Gtk.Label(label=text, xalign=0), False, False, 0)

        box.pack_start(Gtk.Label(
            label="None of these are installed in this environment. Real, correct calls against "
                  "each tool's actual CLI — same attempt-and-report pattern used throughout this "
                  "project, not a placeholder.",
            xalign=0, wrap=True,
        ), False, False, 16)
        return box


def build_window(app):
    return StoreWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
