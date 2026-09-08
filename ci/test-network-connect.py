#!/usr/bin/env python3
"""Network helper regressions without hardware, GTK, D-Bus or actual pairing."""
import importlib.util
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


gi = types.ModuleType("gi")
gi.require_version = lambda *_: None
repository = types.ModuleType("gi.repository")
repository.Gtk = types.SimpleNamespace(ApplicationWindow=object)
repository.Gio = types.SimpleNamespace(
    BusType=types.SimpleNamespace(SESSION=0), bus_get_sync=Mock(return_value=object()),
)
repository.GLib = types.SimpleNamespace(
    Error=RuntimeError, Variant=lambda signature, value: value, SOURCE_REMOVE=False,
    idle_add=Mock(),
)
kit = types.ModuleType("darkos_shell.app_kit")
kit.add_class = lambda widget, *_: widget
kit.run_app = lambda *_: None
module_path = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin/darkos-network.py"
spec = importlib.util.spec_from_file_location("darkos_network_tested", module_path)
network = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "gi": gi, "gi.repository": repository, "darkos_shell.app_kit": kit,
    spec.name: network,
}):
    spec.loader.exec_module(network)


class NetworkRegressionTests(unittest.TestCase):
    def test_escaped_ssid_colons_backslashes_and_strongest_duplicate(self):
        output = "Cafe\\:5G:51:WPA2\nCafe\\:5G:92:WPA3\nDesk\\\\NAS:70:\n:25:WPA2\n"
        self.assertEqual(network.wifi_networks(output), [
            ("Cafe:5G", 92, "WPA3"), ("Desk\\NAS", 70, "Open"),
        ])

    def test_malformed_signal_does_not_become_valid_network(self):
        self.assertEqual(network.wifi_networks("Bad:101:WPA2\nOther:invalid:\nNot:3:fields:here"), [])

    def test_nmcli_whitespace_in_network_name_survives_command_wrapper(self):
        with patch.object(network.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, "  Lobby  :82:\n", "",
        )):
            ok, output = network.run_tool(["nmcli"])
        self.assertTrue(ok)
        self.assertEqual(network.wifi_networks(output), [("  Lobby  ", 82, "Open")])

    def test_device_identifiers_cannot_inject_options_or_dbus_paths(self):
        for device_id in ("--ring", "../peer", "peer/name", "peer\nother", "", "a" * 129, None):
            with self.subTest(device_id=device_id), self.assertRaises(ValueError):
                network.connect_action_argv("pair", device_id)
        with self.assertRaises(ValueError):
            network.connect_action_argv("execute-command", "peer123")

    def test_file_share_uses_exact_local_uri_and_rejects_directories(self):
        with tempfile.TemporaryDirectory(prefix="darkos-connect-test-") as folder:
            path = Path(folder) / "--pair & photo.txt"
            path.touch()
            self.assertEqual(network.connect_action_argv("share", "peer123", str(path)), [
                "kdeconnect-cli", "--device", "peer123", "--share", path.resolve().as_uri(),
            ])
            with self.assertRaises(ValueError):
                network.connect_action_argv("share", "peer123", folder)

    def test_cli_failures_are_visible(self):
        for failure, expected in (
            (FileNotFoundError(), "is not installed"),
            (subprocess.TimeoutExpired("kdeconnect-cli", 5), "timed out"),
        ):
            with patch.object(network.subprocess, "run", side_effect=failure):
                ok, message = network.run_tool(["kdeconnect-cli"])
            self.assertFalse(ok)
            self.assertIn(expected, message)
        with patch.object(network.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 1, "", "D-Bus unavailable",
        )):
            self.assertEqual(network.run_tool(["kdeconnect-cli"]), (False, "D-Bus unavailable"))

    def test_success_keeps_pairing_diagnostics_from_stderr(self):
        with patch.object(network.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, "", "Pair requested\n",
        )) as command:
            self.assertEqual(network.run_tool(["kdeconnect-cli"], include_stderr=True), (True, "Pair requested"))
        self.assertNotIn("shell", command.call_args.kwargs)
        self.assertEqual(command.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_device_status_preserves_name_without_parsing_or_markup(self):
        properties = {"name": "Phone: (paired) <b>name</b>", "isPaired": False, "isReachable": True}
        with patch.object(network, "connect_call", return_value=(properties,)):
            device = network.read_connect_device(object(), "peer123")
        self.assertEqual(device.name, properties["name"])
        self.assertFalse(device.paired)
        with patch.object(network, "connect_call", return_value=({"name": "Phone"},)):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                network.read_connect_device(object(), "peer123")

    def test_stale_pairing_or_reachability_prevents_actions(self):
        for device, action in (
            (network.ConnectDevice("peer123", "Phone", True, False), "ring"),
            (network.ConnectDevice("peer123", "Phone", False, True), "ring"),
            (network.ConnectDevice("peer123", "Phone", True, True), "pair"),
            (network.ConnectDevice("peer123", "Phone", False, True, pending=True), "pair"),
        ):
            with self.subTest(device=device, action=action), patch.object(
                network, "read_connect_device", return_value=device,
            ), patch.object(network, "run_tool") as command:
                self.assertFalse(network.perform_connect_action(action, device.id)[0])
                command.assert_not_called()

    def test_offline_device_can_be_unpaired(self):
        device = network.ConnectDevice("peer123", "Phone", True, False)
        with patch.object(network, "read_connect_device", return_value=device), patch.object(
            network, "run_tool", return_value=(True, "Successfully unpaired"),
        ) as command:
            ok, detail = network.perform_connect_action("unpair", device.id)
        self.assertTrue(ok)
        self.assertIn("Refresh", detail)
        self.assertEqual(command.call_args.args[0], ["kdeconnect-cli", "--device", "peer123", "--unpair"])

    def test_upstream_pair_exit_zero_does_not_hide_missing_device(self):
        device = network.ConnectDevice("peer123", "Phone", False, True)
        with patch.object(network, "read_connect_device", return_value=device), patch.object(
            network, "run_tool", return_value=(True, "Device not found"),
        ):
            self.assertEqual(network.perform_connect_action("pair", device.id), (False, "Device not found"))

    def test_worker_is_background_and_destroyed_window_never_receives_callback(self):
        window = object.__new__(network.NetworkWindow)
        window._closed = False
        window._busy = set()
        finished = threading.Event()
        queued = []
        worker_thread = []
        callback = Mock()

        def worker():
            worker_thread.append(threading.get_ident())
            return True, "ready"

        def queue(function):
            queued.append(function)
            finished.set()

        with patch.object(network.GLib, "idle_add", side_effect=queue):
            window._run_async("wifi", worker, callback)
            self.assertTrue(finished.wait(2), "worker did not queue its main-loop callback")
            window._run_async("wifi", Mock(side_effect=AssertionError("duplicate probe")), callback)
        self.assertNotEqual(worker_thread[0], threading.get_ident())
        self.assertEqual(len(queued), 1)
        window._on_destroy()
        queued[0]()
        callback.assert_not_called()
        self.assertNotIn("wifi", window._busy)

    def test_replaced_error_content_is_shown(self):
        container, old, error_label = Mock(), object(), object()
        container.get_children.return_value = [old]
        network.NetworkWindow._replace(container, error_label)
        container.remove.assert_called_once_with(old)
        container.pack_start.assert_called_once_with(error_label, True, True, 0)
        container.show_all.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
