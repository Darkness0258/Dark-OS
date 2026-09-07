#!/usr/bin/env python3
"""Network Center backed by NetworkManager, BlueZ and upstream KDE Connect.

Probes run outside GTK's main loop. KDE Connect owns discovery, certificates,
pairing and transfers; this app uses its session D-Bus API and bounded CLI calls.
"""
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.NetworkCenter"
WM_CLASS = "darkos-network"
CONNECT_SERVICE = "org.kde.kdeconnect"
CONNECT_PATH = "/modules/kdeconnect"
DEVICE_INTERFACE = "org.kde.kdeconnect.device"
DEVICE_ID = re.compile(r"[A-Za-z0-9_]{1,128}\Z")


def run_tool(argv, timeout=5, include_stderr=False):
    """Return real command status, including missing binaries and timeouts."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,
            env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C"},
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
        output = result.stdout
        if include_stderr and result.stderr.strip():
            output += "\n" + result.stderr.strip()
        # Leading/trailing whitespace can be part of an SSID in terse output.
        return True, output.strip() if include_stderr else output
    except FileNotFoundError:
        return False, f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} timed out; refresh to check the current state"
    except OSError as exc:
        return False, str(exc)


def split_nmcli_fields(line):
    """Decode nmcli terse escaping, including colons and backslashes in SSIDs."""
    fields, current = [], []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def wifi_networks(output):
    networks = {}
    for line in output.splitlines():
        fields = split_nmcli_fields(line)
        if len(fields) != 3 or not fields[0]:
            continue
        ssid, signal_text, security = fields
        try:
            signal = int(signal_text)
        except ValueError:
            continue
        if not 0 <= signal <= 100:
            continue
        if ssid not in networks or signal > networks[ssid][0]:
            networks[ssid] = (signal, security or "Open")
    return [(ssid, *data) for ssid, data in sorted(
        networks.items(), key=lambda item: (-item[1][0], item[0].casefold())
    )]


def validate_device_id(device_id):
    if not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id):
        raise ValueError("KDE Connect returned an invalid device ID")
    return device_id


@dataclass(frozen=True)
class ConnectDevice:
    id: str
    name: str
    paired: bool
    reachable: bool
    pending: bool = False
    incoming: bool = False
    verification_key: str = ""


def connect_call(bus, path, interface, method, parameters=None, timeout=4000):
    return bus.call_sync(
        CONNECT_SERVICE, path, interface, method, parameters, None,
        Gio.DBusCallFlags.NONE, timeout, None,
    ).unpack()


def read_connect_device(bus, device_id, timeout=1500):
    validate_device_id(device_id)
    properties = connect_call(
        bus, f"{CONNECT_PATH}/devices/{device_id}",
        "org.freedesktop.DBus.Properties", "GetAll",
        GLib.Variant("(s)", (DEVICE_INTERFACE,)), timeout,
    )[0]
    if not isinstance(properties.get("name"), str) or any(
        not isinstance(properties.get(key), bool) for key in ("isPaired", "isReachable")
    ):
        raise ValueError("KDE Connect returned incomplete device status")
    return ConnectDevice(
        device_id, properties["name"], properties["isPaired"], properties["isReachable"],
        properties.get("isPairRequested") is True,
        properties.get("isPairRequestedByPeer") is True,
        str(properties.get("verificationKey", "")),
    )


def list_connect_devices(discover=False):
    """Typed upstream state avoids interpreting translated CLI device names."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    if discover:
        connect_call(bus, CONNECT_PATH, "org.kde.kdeconnect.daemon", "forceOnNetworkChange")
    device_ids = connect_call(
        bus, CONNECT_PATH, "org.kde.kdeconnect.daemon", "devices",
        GLib.Variant("(bb)", (False, False)),
    )[0]
    devices, warnings = [], []
    deadline = time.monotonic() + 12
    for device_id in device_ids[:64]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            warnings.append("Device refresh reached its time limit; refresh to try again.")
            break
        try:
            devices.append(read_connect_device(bus, device_id, min(1500, max(1, int(remaining * 1000)))))
        except (GLib.Error, ValueError) as exc:
            warnings.append(f"Could not read a device: {exc}")
    if len(device_ids) > 64:
        warnings.append("Showing the first 64 devices reported by KDE Connect.")
    return sorted(devices, key=lambda device: (not device.reachable, device.name.casefold())), "\n".join(warnings)


def connect_action_argv(action, device_id, filename=None):
    validate_device_id(device_id)
    if action not in {"pair", "unpair", "ring", "share"}:
        raise ValueError("Unsupported Connect action")
    argv = ["kdeconnect-cli", "--device", device_id, f"--{action}"]
    if action == "share":
        if not filename:
            raise ValueError("Select a local file to share")
        path = Path(filename).resolve(strict=True)
        if not path.is_file() or not os.access(path, os.R_OK):
            raise ValueError("Select a readable regular file")
        # A file URI is never mistaken for an option or a remote URL.
        argv.append(path.as_uri())
    return argv


def perform_connect_action(action, device_id, filename=None):
    argv = connect_action_argv(action, device_id, filename)
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    device = read_connect_device(bus, device_id)
    if action != "unpair" and not device.reachable:
        return False, "The device is offline. Refresh after reconnecting it."
    if action in {"ring", "share", "unpair"} and not device.paired:
        return False, "The device is no longer paired. Refresh its status."
    if action == "pair" and (device.paired or device.pending or device.incoming):
        return False, "Pairing status changed. Refresh or open KDE Connect settings."
    ok, output = run_tool(argv, timeout=8, include_stderr=True)
    # Upstream's pair branch can report this with exit code zero.
    if action == "pair" and "Device not found" in output:
        return False, output
    if not ok:
        return False, output
    messages = {
        "pair": "Pairing requested. Check the verification code and approve on your other device, then refresh.",
        "unpair": "Unpair request sent. Refresh to confirm the current pairing state.",
        "ring": "Ring request sent. Your device must support and enable Find My Phone.",
        "share": "Transfer submitted to KDE Connect. Check its notification and the receiving device for completion.",
    }
    return True, messages[action] + (f"\n{output}" if output else "")


class NetworkWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Network Center")
        self.set_default_size(760, 580)
        add_class(self, "app-window")
        self._closed = False
        self._busy = set()
        self.connect("destroy", self._on_destroy)
        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        notebook.append_page(self._build_wifi_tab(), Gtk.Label(label="Wi-Fi"))
        notebook.append_page(self._build_bluetooth_tab(), Gtk.Label(label="Bluetooth"))
        notebook.append_page(self._build_connect_tab(), Gtk.Label(label="Connect"))
        notebook.append_page(self._build_cloud_tab(), Gtk.Label(label="Cloud"))
        self.add(notebook)

    def _on_destroy(self, *_):
        self._closed = True

    def _run_async(self, key, worker, callback):
        if self._closed or key in self._busy:
            return
        self._busy.add(key)

        def work():
            try:
                result = worker()
            except Exception as exc:
                result = (False, str(exc))

            def finish():
                self._busy.discard(key)
                if not self._closed:
                    callback(*result)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(finish)

        threading.Thread(target=work, daemon=True, name=f"network-{key}").start()

    @staticmethod
    def _replace(container, child):
        for old in container.get_children():
            container.remove(old)
        container.pack_start(child, True, True, 0)
        container.show_all()

    @staticmethod
    def _button(label, callback):
        button = Gtk.Button(label=label)
        add_class(button, "icon-button")
        button.connect("clicked", callback)
        return button

    def _status_page(self, title, detail, retry_cb=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label=title, xalign=0), False, False, 0)
        box.pack_start(Gtk.Label(label=detail, xalign=0, wrap=True), False, False, 0)
        if retry_cb:
            retry = self._button("Refresh", retry_cb)
            retry.set_halign(Gtk.Align.START)
            box.pack_start(retry, False, False, 8)
        return box

    def _build_wifi_tab(self):
        self.wifi_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._refresh_wifi()
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.wifi_container)
        return scroll

    def _refresh_wifi(self, *_):
        if "wifi" in self._busy:
            return
        self._replace(self.wifi_container, self._status_page("Wi-Fi", "Reading nearby networks…"))
        self._run_async("wifi", lambda: run_tool([
            "nmcli", "--escape", "yes", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
        ]), self._show_wifi)

    def _show_wifi(self, ok, output):
        box = self._status_page("Nearby networks", "" if ok else f"Couldn't reach NetworkManager: {output}", self._refresh_wifi)
        if ok:
            networks = wifi_networks(output)
            for ssid, signal, security in networks:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row.pack_start(Gtk.Label(label=ssid, xalign=0), True, True, 0)
                row.pack_start(Gtk.Label(label=f"{signal}%  •  {security}"), False, False, 0)
                box.pack_start(row, False, False, 2)
            if not networks:
                box.pack_start(Gtk.Label(label="No networks found by nmcli.", xalign=0), False, False, 0)
        self._replace(self.wifi_container, box)

    def _build_bluetooth_tab(self):
        self.bt_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._refresh_bluetooth()
        return self.bt_container

    def _refresh_bluetooth(self, *_):
        if "bluetooth" in self._busy:
            return
        self._replace(self.bt_container, self._status_page("Bluetooth", "Reading adapter status…"))
        self._run_async("bluetooth", lambda: run_tool(["bluetoothctl", "show"]), self._show_bluetooth)

    def _show_bluetooth(self, ok, output):
        box = self._status_page("Bluetooth adapter", "" if ok else f"Couldn't reach bluetoothd: {output}", self._refresh_bluetooth)
        if ok:
            text = Gtk.TextView(editable=False, monospace=True)
            text.get_buffer().set_text(output or "No adapter was reported by bluetoothctl.")
            scroll = Gtk.ScrolledWindow()
            scroll.add(text)
            box.pack_start(scroll, True, True, 0)
        self._replace(self.bt_container, box)

    def _build_connect_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(
            label="Connect your phone with KDE Connect on the same network. "
                  "Notification, clipboard and plugin permissions are managed in KDE Connect settings.",
            xalign=0, wrap=True,
        ), False, False, 0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.connect_refresh = self._button("Refresh devices", self._refresh_connect)
        toolbar.pack_start(self.connect_refresh, False, False, 0)
        toolbar.pack_start(self._button("KDE Connect settings", self._open_connect_settings), False, False, 0)
        box.pack_start(toolbar, False, False, 0)
        self.connect_notice = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.pack_start(self.connect_notice, False, False, 0)
        self.connect_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.connect_container)
        box.pack_start(scroll, True, True, 0)
        self._refresh_connect()
        return box

    def _refresh_connect(self, *_):
        if "connect" in self._busy:
            return
        self.connect_refresh.set_sensitive(False)
        self._replace(self.connect_container, Gtk.Label(label="Reading KDE Connect devices…", xalign=0))
        self._run_async("connect", lambda: (True, list_connect_devices(discover=bool(_))), self._show_connect)

    def _show_connect(self, ok, result):
        self.connect_refresh.set_sensitive(True)
        if not ok:
            self._replace(self.connect_container, Gtk.Label(
                label=f"Couldn't reach KDE Connect: {result}\nInstall kdeconnect and open it in your desktop session.",
                xalign=0, wrap=True,
            ))
            return
        devices, warning = result
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        if warning:
            box.pack_start(Gtk.Label(label=warning, xalign=0, wrap=True), False, False, 0)
        if not devices:
            box.pack_start(Gtk.Label(
                label="No devices reported. Open KDE Connect on your phone, check the shared network, then refresh.",
                xalign=0, wrap=True,
            ), False, False, 0)
        for device in devices:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            status = "Paired" if device.paired else "Not paired"
            status += " · Online" if device.reachable else " · Offline"
            if device.incoming:
                status += " · Incoming pairing request — open settings to verify"
            elif device.pending:
                status += " · Waiting for pairing approval"
            row.pack_start(Gtk.Label(label=f"{device.name}\n{device.id}\n{status}", xalign=0, wrap=True), False, False, 0)
            if (device.pending or device.incoming) and device.verification_key:
                row.pack_start(Gtk.Label(label=f"Verification code: {device.verification_key}", xalign=0, selectable=True), False, False, 0)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            action = "unpair" if device.paired else "pair"
            pair = self._button("Unpair" if device.paired else "Pair", lambda _, d=device, a=action: self._confirm_pair_action(d, a))
            pair.set_sensitive(device.paired or (device.reachable and not device.pending and not device.incoming))
            actions.pack_start(pair, False, False, 0)
            for label, callback in (
                ("Ring", lambda _, d=device: self._start_connect_action("ring", d)),
                ("Share file", lambda _, d=device: self._choose_share_file(d)),
            ):
                button = self._button(label, callback)
                button.set_sensitive(device.paired and device.reachable)
                actions.pack_start(button, False, False, 0)
            row.pack_start(actions, False, False, 0)
            box.pack_start(row, False, False, 0)
        self._replace(self.connect_container, box)

    def _confirm_pair_action(self, device, action):
        if "connect" in self._busy:
            return
        pairing = action == "pair"
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE, text=f"{'Pair with' if pairing else 'Unpair'} {device.name}?",
        )
        dialog.format_secondary_text(
            f"Device ID: {device.id}\n" + (
                "Check the verification code in KDE Connect on both devices before approving. "
                "Only approve a device you recognize."
                if pairing else "This revokes the trusted connection and stops sharing with this device."
            )
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Request pairing" if pairing else "Unpair", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self._start_connect_action(action, device)

    def _choose_share_file(self, device):
        if "connect" in self._busy:
            return
        dialog = Gtk.FileChooserDialog(
            title=f"Share file with {device.name}", transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.set_local_only(True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Send file", Gtk.ResponseType.OK)
        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and filename:
            self._start_connect_action("share", device, filename)

    def _start_connect_action(self, action, device, filename=None):
        if "connect" in self._busy:
            return
        self.connect_container.set_sensitive(False)
        self.connect_refresh.set_sensitive(False)
        self.connect_notice.set_text(f"Contacting {device.name}…")

        def finished(ok, detail):
            self.connect_container.set_sensitive(True)
            self.connect_notice.set_text(detail if ok else f"Connect action failed: {detail}")
            self._refresh_connect()

        self._run_async("connect", lambda: perform_connect_action(action, device.id, filename), finished)

    def _open_connect_settings(self, *_):
        executable = shutil.which("kdeconnect-app")
        if not executable:
            self.connect_notice.set_text("KDE Connect settings is not installed. Install the kdeconnect package.")
            return
        try:
            subprocess.Popen([executable], stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self.connect_notice.set_text(f"Couldn't open KDE Connect settings: {exc}")

    def _build_cloud_tab(self):
        return self._status_page("DarkOS Cloud", "Not signed in. Accounts, sync and cloud updates are planned for Phase 9.")


def build_window(app):
    return NetworkWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
