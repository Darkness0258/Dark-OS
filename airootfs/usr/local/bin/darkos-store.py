#!/usr/bin/env python3
"""Read-only package search, installed packages, updates, and compatibility.

Backend failures remain visible and all slow work runs outside GTK. Install
actions stay disabled until the complete Shield installation gate is available.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.Store"
WM_CLASS = "darkos-store"
AUR_RESPONSE_LIMIT = 2 * 1024 * 1024
AUR_REQUEST_TIMEOUT = 12


def run_tool(argv, timeout=8, *, empty_exit_one=False):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
        # pacman search/upgradable queries can return 1 for no matches. Treat
        # this as empty only at those call sites and only without diagnostics.
        empty_match = empty_exit_one and result.returncode == 1 and not (
            result.stdout.strip() or result.stderr.strip()
        )
        if result.returncode != 0 and not empty_match:
            detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
            return False, f"exit code {result.returncode}" + (f": {detail}" if detail else "")
        return True, result.stdout
    except FileNotFoundError:
        return False, f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} timed out"
    except OSError as e:
        return False, str(e)


def aur_search(query):
    url = "https://aur.archlinux.org/rpc/v5/search/" + urllib.parse.quote(query, safe="")
    deadline = time.monotonic() + AUR_REQUEST_TIMEOUT
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            payload = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("AUR response exceeded the request time limit.")
                # read1 performs at most one underlying read, so a trickling
                # response cannot keep a single read(size) alive indefinitely.
                chunk = resp.read1(min(65536, AUR_RESPONSE_LIMIT + 1 - len(payload)))
                if time.monotonic() >= deadline:
                    raise TimeoutError("AUR response exceeded the request time limit.")
                if not chunk:
                    break
                if len(payload) + len(chunk) > AUR_RESPONSE_LIMIT:
                    raise ValueError("AUR response exceeded the 2 MiB size limit. Narrow the search.")
                payload.extend(chunk)
            data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            return False, "AUR returned an invalid response."
        if data.get("type") == "error" or data.get("error"):
            return False, str(data.get("error") or "AUR rejected this search.")
        results = data.get("results")
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            return False, "AUR returned an invalid results list."
        return True, results
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except (OSError, ValueError) as e:
        return False, str(e)


class StoreWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Store")
        self.set_default_size(820, 600)
        add_class(self, "app-window")
        self._closed = False
        self._job_tokens = {}
        self._queued_jobs = {}
        self._running_jobs = set()
        # Fail closed like Shield itself: no engine, no install button.
        self._shield_ready = shutil.which("clamscan") is not None
        self._aur_ready = self._shield_ready and shutil.which("git") is not None
        self.connect("destroy", self._on_destroy)

        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        notebook.append_page(self._build_search_tab(), Gtk.Label(label="Search"))
        notebook.append_page(self._build_installed_tab(), Gtk.Label(label="Installed"))
        notebook.append_page(self._build_updates_tab(), Gtk.Label(label="Updates"))
        notebook.append_page(self._build_compat_tab(), Gtk.Label(label="Compatibility"))
        self.add(notebook)

    def _shield_notice(self):
        if self._shield_ready:
            text = (
                "Installing a pacman package downloads it, scans it with Shield, and "
                "installs only if it comes back clean — one sudo prompt in a terminal "
                "you can watch. AUR and Flatpak installs are not gated yet and stay disabled."
            )
        else:
            text = (
                "Installing packages is disabled until the complete Shield installation "
                "gate is available. Search and package status remain available."
            )
        label = Gtk.Label(label=text, xalign=0, wrap=True)
        add_class(label, "path-crumb")
        return label

    def _on_destroy(self, *_):
        self._closed = True
        self._queued_jobs.clear()

    def _submit_job(self, key, work, apply_result):
        """Keep one running and at most one queued request per tab."""
        if self._closed:
            return
        token = self._job_tokens.get(key, 0) + 1
        self._job_tokens[key] = token
        self._queued_jobs[key] = (token, work, apply_result)
        self._start_queued_job(key)

    def _start_queued_job(self, key):
        if self._closed or key in self._running_jobs or key not in self._queued_jobs:
            return
        token, work, apply_result = self._queued_jobs.pop(key)
        self._running_jobs.add(key)
        threading.Thread(
            target=self._job_worker, args=(key, token, work, apply_result),
            name=f"darkos-store-{key}", daemon=True,
        ).start()

    def _job_worker(self, key, token, work, apply_result):
        try:
            success, result = True, work()
        except Exception as error:
            success, result = False, str(error) or type(error).__name__
        GLib.idle_add(self._finish_job, key, token, apply_result, success, result)

    def _finish_job(self, key, token, apply_result, success, result):
        if self._closed:
            return False
        self._running_jobs.discard(key)
        if token == self._job_tokens.get(key):
            apply_result(success, result)
        self._start_queued_job(key)
        return False

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
            self._job_tokens["search"] = self._job_tokens.get("search", 0) + 1
            self._queued_jobs.pop("search", None)
            return
        self.search_results.pack_start(Gtk.Label(label=f"Searching for {query}…", xalign=0), False, False, 0)
        self.search_results.show_all()
        self._submit_job("search", lambda: self._collect_search(query), self._apply_search)

    def _collect_search(self, query):
        return [
            ("pacman (native)", "pacman", self._search_pacman(query)),
            ("AUR", "aur", self._search_aur(query)),
            ("Flatpak", "flatpak", self._search_flatpak(query)),
        ]

    def _apply_search(self, success, result):
        for child in list(self.search_results.get_children()):
            self.search_results.remove(child)
        sections = result if success else [("Search", "search", (False, [], result))]
        for title, backend, values in sections:
            self.search_results.pack_start(self._source_section(title, backend, *values), False, False, 0)
        self.search_results.show_all()

    def _search_pacman(self, query):
        ok, output = run_tool(["pacman", "-Ss", "--color", "never", "--", query], empty_exit_one=True)
        if not ok:
            return False, [], output
        results = []
        for line in output.splitlines():
            header = line.split()
            if header and not line[0].isspace():
                results.append((header[0], header[0]))
        return True, results, None

    def _search_aur(self, query):
        ok, data = aur_search(query)
        if not ok:
            return False, [], data
        return True, [
            (r.get("Name"), f'{r.get("Name")} — {r.get("Description", "")}') for r in data[:20]
        ], None

    def _search_flatpak(self, query):
        ok, output = run_tool(["flatpak", "search", "--columns=application,name,description", "--", query])
        if not ok:
            return False, [], output
        results = []
        for line in output.strip().splitlines():
            if not line:
                continue
            columns = line.split("\t")
            results.append((columns[0], " — ".join(columns)))
        return True, results, None

    def _source_section(self, title, backend, ok, results, error):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(Gtk.Label(label=f"<b>{title}</b>", xalign=0, use_markup=True), False, False, 0)
        if not ok:
            box.pack_start(Gtk.Label(label=f"Unavailable: {error}", xalign=0, wrap=True), False, False, 0)
        elif not results:
            box.pack_start(Gtk.Label(label="No results.", xalign=0), False, False, 0)
        else:
            for pkg_id, display in results[:20]:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                add_class(row, "sidebar-row")
                row.pack_start(Gtk.Label(label=display, xalign=0), True, True, 0)
                install_btn = Gtk.Button(label="Install")
                add_class(install_btn, "icon-button")
                if backend == "pacman" and self._shield_ready:
                    install_btn.connect("clicked", lambda _b, pkg=pkg_id: self._confirm_install(pkg))
                    install_btn.set_tooltip_text("Download, scan with Shield, then install")
                elif backend == "aur" and self._aur_ready:
                    install_btn.connect("clicked", lambda _b, pkg=pkg_id: self._confirm_aur_install(pkg))
                    install_btn.set_tooltip_text("Clone, review the PKGBUILD, build, scan, then install")
                else:
                    install_btn.set_sensitive(False)
                    if backend == "pacman":
                        tip = "Disabled until the complete Shield installation gate is available"
                    elif backend == "aur":
                        tip = "Disabled until git and Shield are both available"
                    else:
                        tip = "Flatpak installs are outside this gate's current scope"
                    install_btn.set_tooltip_text(tip)
                row.pack_start(install_btn, False, False, 0)
                box.pack_start(row, False, False, 0)
        return box

    def _confirm_install(self, pkg):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text=f"Install {pkg}?",
            secondary_text=(
                "DarkOS will download it, scan it with Shield, and install it only if "
                "the scan comes back clean. This opens a terminal and asks for your "
                "password once."
            ),
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Install", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self._install_package(pkg)

    def _install_package(self, pkg):
        shell_cmd = (
            f"sudo python3 /usr/local/bin/darkos-store-gated-install.py -- {shlex.quote(pkg)}; "
            'result=$?; printf "\\nInstall exit status: %s\\nPress Enter to close.\\n" "$result"; '
            'read -r reply; exit "$result"'
        )
        try:
            subprocess.Popen(["/usr/local/bin/the-void.sh", "-e", "/bin/sh", "-c", shell_cmd])
        except OSError as error:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                text=f"Could not open the install terminal: {error}",
            )
            dialog.run()
            dialog.destroy()

    def _confirm_aur_install(self, pkg):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text=f"Build {pkg} from AUR?",
            secondary_text=(
                "AUR packages are build scripts (PKGBUILDs), not pre-built binaries — "
                "DarkOS cannot scan source code for malicious behavior before building it. "
                "A terminal will open showing the PKGBUILD; you decide whether it's safe to "
                "build. Shield only scans the finished package afterward, which does not "
                "undo anything a bad build step already did. This is real risk pacman "
                "installs don't carry."
            ),
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Review PKGBUILD", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self._install_aur_package(pkg)

    def _install_aur_package(self, pkg):
        # No leading `sudo` — cloning and building run as the invoking user
        # (makepkg refuses to run as root); the script asks for a password
        # itself, only for the final `pacman -U`.
        shell_cmd = (
            f"python3 /usr/local/bin/darkos-store-gated-aur-install.py -- {shlex.quote(pkg)}; "
            'result=$?; printf "\\nInstall exit status: %s\\nPress Enter to close.\\n" "$result"; '
            'read -r reply; exit "$result"'
        )
        try:
            subprocess.Popen(["/usr/local/bin/the-void.sh", "-e", "/bin/sh", "-c", shell_cmd])
        except OSError as error:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                text=f"Could not open the install terminal: {error}",
            )
            dialog.run()
            dialog.destroy()

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
        self.installed_view.get_buffer().set_text("Loading installed packages…")
        self._submit_job("installed", self._collect_installed, self._apply_installed)

    def _collect_installed(self):
        parts = []
        ok, output = run_tool(["pacman", "-Q"])
        parts.append("=== pacman -Q ===\n" + (output if ok else f"Unavailable: {output}"))
        ok2, output2 = run_tool(["flatpak", "list", "--app"])
        parts.append("=== flatpak list ===\n" + (output2 if ok2 else f"Unavailable: {output2}"))
        return "\n\n".join(parts)

    def _apply_installed(self, success, result):
        self.installed_view.get_buffer().set_text(result if success else f"Unavailable: {result}")

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
        self.updates_view.get_buffer().set_text("Checking available updates…")
        self._submit_job("updates", self._collect_updates, self._apply_updates)

    def _collect_updates(self):
        parts = []
        ok, output = run_tool(["pacman", "-Qu"], empty_exit_one=True)
        parts.append("=== pacman -Qu (local package databases) ===\n" + (
            (output.strip() or "No updates listed in the current local databases.")
            if ok else f"Unavailable: {output}"
        ))
        ok2, output2 = run_tool(["flatpak", "remote-ls", "--updates"])
        parts.append("=== flatpak updates ===\n" + (output2.strip() or "Up to date." if ok2 else f"Unavailable: {output2}"))
        return "\n\n".join(parts)

    def _apply_updates(self, success, result):
        self.updates_view.get_buffer().set_text(result if success else f"Unavailable: {result}")

    # -- Compatibility (Wine/Waydroid) -------------------------------------------
    def _build_compat_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        box.pack_start(Gtk.Label(label="<b>Windows compatibility (Wine/Proton)</b>", xalign=0, use_markup=True), False, False, 0)
        self.compat_label = Gtk.Label(label="Checking compatibility tools…", xalign=0, wrap=True)
        box.pack_start(self.compat_label, False, False, 0)
        box.pack_start(Gtk.Label(label="<b>Android compatibility (Waydroid)</b>", xalign=0, use_markup=True), False, False, 12)
        self.waydroid_label = Gtk.Label(label="Checking Waydroid…", xalign=0, wrap=True)
        box.pack_start(self.waydroid_label, False, False, 0)

        box.pack_start(Gtk.Label(
            label="Status is read from installed commands. Steam, Lutris, Wine, and "
                  "Waydroid are supplied by the Phase 7 image; use Gaming Hub for their "
                  "launcher and detailed compatibility status.",
            xalign=0, wrap=True,
        ), False, False, 16)
        self._submit_job("compatibility", self._collect_compatibility, self._apply_compatibility)
        return box

    def _collect_compatibility(self):
        ok, output = run_tool(["wine", "--version"])
        wine = "Wine: " + (output.strip() if ok else f"Unavailable: {output}")
        proton = shutil.which("proton")
        proton_status = (
            f"Proton command: {proton} (not executed)." if proton
            else "No standalone Proton command. Gaming Hub also checks Steam-managed Proton."
        )
        ok, output = run_tool(["waydroid", "status"])
        waydroid = "Waydroid: " + (output.strip() if ok else f"Unavailable: {output}")
        return f"{wine}\n{proton_status}", waydroid

    def _apply_compatibility(self, success, result):
        if success:
            compatibility, waydroid = result
        else:
            compatibility = waydroid = f"Unavailable: {result}"
        self.compat_label.set_text(compatibility)
        self.waydroid_label.set_text(waydroid)


def build_window(app):
    return StoreWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
