#!/usr/bin/env python3
"""DarkOS Mission / Spaces — workspace + window overview and switcher.

Queries `hyprctl -j workspaces` and `hyprctl -j clients` — real calls against
Hyprland's actual (documented, stable) JSON IPC, same approach as Network
Center's nmcli/bluetoothctl calls. Reported here rather than earlier: this
is NOT the same category of gap as Shield — Shield's correctness is
fundamentally unverifiable without a real scan engine and test malware;
this is a data-display problem against a documented, stable schema, and
the failure path (no compositor running) is exactly as real and testable
here as nmcli's was.
"""
import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Mission"
WM_CLASS = "darkos-mission"


def run_hyprctl_json(*args):
    """Returns (ok, data_or_error_string) — mirrors Network Center's
    run_tool(): a missing binary, non-zero exit, bad JSON, or timeout are
    all "no compositor to talk to" the same way nmcli's absence was."""
    try:
        result = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, timeout=3)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
        return True, json.loads(result.stdout)
    except FileNotFoundError:
        return False, "hyprctl is not installed"
    except subprocess.TimeoutExpired:
        return False, "hyprctl timed out"
    except json.JSONDecodeError as e:
        return False, f"hyprctl returned invalid JSON: {e}"
    except OSError as e:
        return False, str(e)


def hyprctl_dispatch(*args):
    try:
        subprocess.run(["hyprctl", "dispatch", *args], timeout=3, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass  # no compositor to dispatch to — same as clicking a disabled control


class MissionWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Mission / Spaces")
        self.set_default_size(760, 560)
        add_class(self, "app-window")

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        toolbar.pack_start(Gtk.Label(label="Mission / Spaces", xalign=0), True, True, 8)
        toolbar.pack_start(make_icon_button("view-refresh-symbolic", "Refresh", lambda *_: self._refresh()), False, False, 0)
        root.pack_start(toolbar, False, False, 0)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.content)
        root.pack_start(scroller, True, True, 0)

        self._refresh()

    def _refresh(self):
        for child in list(self.content.get_children()):
            self.content.remove(child)

        ws_ok, workspaces = run_hyprctl_json("workspaces")
        cl_ok, clients = run_hyprctl_json("clients")

        if not ws_ok:
            self._show_unavailable(workspaces)
            return
        if not cl_ok:
            clients = []  # workspaces alone are still useful even if client listing failed

        by_workspace = {}
        for client in clients:
            ws_id = client.get("workspace", {}).get("id")
            by_workspace.setdefault(ws_id, []).append(client)

        for ws in sorted(workspaces, key=lambda w: w.get("id", 0)):
            self.content.pack_start(self._build_workspace_section(ws, by_workspace.get(ws.get("id"), [])), False, False, 0)
        if not workspaces:
            self.content.pack_start(Gtk.Label(label="No workspaces reported.", xalign=0), False, False, 20)
        self.content.show_all()

    def _show_unavailable(self, error):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Not running under Hyprland</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(label=f"hyprctl: {error}", xalign=0, wrap=True), False, False, 0)
        self.content.pack_start(box, False, False, 0)
        self.content.show_all()

    def _build_workspace_section(self, ws, clients):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        section.set_border_width(12)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(xalign=0)
        ws_name = GLib.markup_escape_text(str(ws.get("name", ws.get("id", "?"))))
        monitor = GLib.markup_escape_text(str(ws.get("monitor", "?")))
        title.set_markup(f"<b>Workspace {ws_name}</b>  —  {monitor}")
        header.pack_start(title, True, True, 0)
        switch_btn = Gtk.Button(label="Switch to")
        add_class(switch_btn, "icon-button")
        switch_btn.connect("clicked", lambda *_, wid=ws.get("id"): hyprctl_dispatch("workspace", str(wid)))
        header.pack_start(switch_btn, False, False, 0)
        section.pack_start(header, False, False, 0)

        if not clients:
            empty = Gtk.Label(label="(empty)", xalign=0)
            add_class(empty, "path-crumb")
            section.pack_start(empty, False, False, 0)
        for client in clients:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            add_class(row, "sidebar-row")
            label = Gtk.Label(label=f"{client.get('class', '?')} — {client.get('title', '')}", xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            row.pack_start(label, True, True, 0)
            focus_btn = Gtk.Button(label="Focus")
            add_class(focus_btn, "icon-button")
            addr = client.get("address")
            focus_btn.connect("clicked", lambda *_, a=addr: hyprctl_dispatch("focuswindow", f"address:{a}"))
            row.pack_start(focus_btn, False, False, 0)
            section.pack_start(row, False, False, 0)
        section.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        return section


def build_window(app):
    return MissionWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
