#!/usr/bin/env python3
"""DarkOS Network Center — Wi-Fi, Bluetooth, Connect, Cloud.

Wi-Fi/Bluetooth shell out to nmcli/bluetoothctl (the correct real approach —
NetworkManager and BlueZ own the actual hardware state, this app doesn't
reimplement that) and report the real failure when there's no backend
running rather than faking a device list. Confirmed in this sandbox: with
no NetworkManager/bluetoothd running, nmcli exits 1 with a clear message
and bluetoothctl aborts outright (no D-Bus) — both are caught the same way,
by checking the subprocess result, not by assuming success.

Connect (real KDE Connect protocol phone integration) is a UI shell only.
build-plan.md already flags pykdeconnect as "not production-ready as-is" —
implementing the actual pairing/discovery/packet protocol is a substantial
project on its own and isn't something to half-build here.
"""
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.NetworkCenter"
WM_CLASS = "darkos-network"


def run_tool(argv, timeout=4):
    """Returns (ok, output). ok is False for a missing binary, non-zero
    exit, or timeout — the three ways "no real backend" shows up here."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
        return True, result.stdout
    except FileNotFoundError:
        return False, f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} timed out"
    except OSError as e:
        return False, str(e)


class NetworkWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Network Center")
        self.set_default_size(720, 540)
        add_class(self, "app-window")

        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        notebook.append_page(self._build_wifi_tab(), Gtk.Label(label="Wi-Fi"))
        notebook.append_page(self._build_bluetooth_tab(), Gtk.Label(label="Bluetooth"))
        notebook.append_page(self._build_connect_tab(), Gtk.Label(label="Connect"))
        notebook.append_page(self._build_cloud_tab(), Gtk.Label(label="Cloud"))
        self.add(notebook)

    def _status_page(self, title, ok, detail, retry_cb):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        label = Gtk.Label(label=title, xalign=0)
        label.set_markup(f"<b>{title}</b>")
        box.pack_start(label, False, False, 0)
        detail_label = Gtk.Label(label=detail, xalign=0, wrap=True)
        box.pack_start(detail_label, False, False, 0)
        retry_btn = Gtk.Button(label="Refresh")
        add_class(retry_btn, "icon-button")
        retry_btn.set_halign(Gtk.Align.START)
        retry_btn.connect("clicked", retry_cb)
        box.pack_start(retry_btn, False, False, 8)
        return box

    # -- Wi-Fi -----------------------------------------------------------------
    def _build_wifi_tab(self):
        self.wifi_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._refresh_wifi()
        return self.wifi_container

    def _refresh_wifi(self, *_):
        for child in list(self.wifi_container.get_children()):
            self.wifi_container.remove(child)
        ok, output = run_tool(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"])
        if not ok:
            self.wifi_container.pack_start(
                self._status_page("Wi-Fi", False, f"Couldn't reach NetworkManager: {output}", self._refresh_wifi),
                True, True, 0,
            )
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Nearby networks</b>", xalign=0, use_markup=True), False, False, 4)
        seen = set()
        for line in output.strip().splitlines():
            parts = line.split(":")
            if not parts or not parts[0] or parts[0] in seen:
                continue
            seen.add(parts[0])
            signal = parts[1] if len(parts) > 1 else "?"
            security = parts[2] if len(parts) > 2 and parts[2] else "Open"
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(Gtk.Image.new_from_icon_name("network-wireless-symbolic", Gtk.IconSize.MENU), False, False, 0)
            row.pack_start(Gtk.Label(label=parts[0], xalign=0), True, True, 0)
            row.pack_start(Gtk.Label(label=f"{signal}%  •  {security}"), False, False, 0)
            box.pack_start(row, False, False, 2)
        if not seen:
            box.pack_start(Gtk.Label(label="No networks found by nmcli.", xalign=0), False, False, 0)
        refresh_btn = Gtk.Button(label="Refresh")
        add_class(refresh_btn, "icon-button")
        refresh_btn.set_halign(Gtk.Align.START)
        refresh_btn.connect("clicked", self._refresh_wifi)
        box.pack_start(refresh_btn, False, False, 8)
        self.wifi_container.pack_start(box, True, True, 0)
        self.wifi_container.show_all()

    # -- Bluetooth ---------------------------------------------------------------
    def _build_bluetooth_tab(self):
        self.bt_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._refresh_bluetooth()
        return self.bt_container

    def _refresh_bluetooth(self, *_):
        for child in list(self.bt_container.get_children()):
            self.bt_container.remove(child)
        ok, output = run_tool(["bluetoothctl", "show"])
        if not ok:
            self.bt_container.pack_start(
                self._status_page("Bluetooth", False, f"Couldn't reach bluetoothd: {output}", self._refresh_bluetooth),
                True, True, 0,
            )
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Adapter</b>", xalign=0, use_markup=True), False, False, 4)
        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_monospace(True)
        text_view.get_buffer().set_text(output)
        box.pack_start(text_view, True, True, 0)
        self.bt_container.pack_start(box, True, True, 0)
        self.bt_container.show_all()

    # -- Connect -----------------------------------------------------------------
    def _build_connect_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Connect</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(
            label="No paired devices.\n\n"
                  "Honest scope note: this tab is UI only. Real KDE Connect protocol support "
                  "(TLS pairing, mDNS discovery, the packet protocol for notifications/clipboard/"
                  "file transfer) is a substantial project on its own — build-plan.md already "
                  "flags the one available Python reference implementation (pykdeconnect) as "
                  "early and not production-ready. Wiring this for real is a dedicated follow-up, "
                  "not something to half-build alongside fifteen Settings tabs.",
            xalign=0, wrap=True,
        ), False, False, 0)
        pair_btn = Gtk.Button(label="Pair New Device")
        add_class(pair_btn, "icon-button")
        pair_btn.set_sensitive(False)
        pair_btn.set_halign(Gtk.Align.START)
        pair_btn.set_tooltip_text("Not wired to a real pairing backend yet")
        box.pack_start(pair_btn, False, False, 8)
        return box

    # -- Cloud -----------------------------------------------------------------
    def _build_cloud_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>DarkOS Cloud</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(
            label="Not signed in. DarkOS Cloud (accounts, sync, updates) is Phase 9 — "
                  "nothing to connect to yet.",
            xalign=0, wrap=True,
        ), False, False, 0)
        return box


def build_window(app):
    return NetworkWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
