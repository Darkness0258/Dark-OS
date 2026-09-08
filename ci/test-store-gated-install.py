#!/usr/bin/env python3
"""Shield-gated Store install regressions.

Verifies the orchestration in darkos-store-gated-install.py: resolve -> download
-> verify -> scan -> install. Any non-clean scan, download failure, or resolution
mismatch must make pacman -U unreachable. Loads the real script by file path
(bypassing darkos_shell's package __init__, which needs GTK) with a lightweight
stand-in for darkos_shell.shield, exactly like ci/test-store.py stands in for
darkos_shell.app_kit. Each test patches gated.scan_path for the duration of that
test only (unittest.mock.patch.object), so results never leak between tests.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
darkos_shell_pkg = types.ModuleType("darkos_shell")
darkos_shell_pkg.__path__ = []  # mark as a package without running its real __init__
shield_stub = types.ModuleType("darkos_shell.shield")
shield_stub.scan_path = lambda *_a, **_kw: None  # placeholder; every test patches this
sys.modules["darkos_shell"] = darkos_shell_pkg
sys.modules["darkos_shell.shield"] = shield_stub

spec = importlib.util.spec_from_file_location(
    "darkos_store_gated_install_tested",
    ROOT / "airootfs/usr/local/bin/darkos-store-gated-install.py",
)
assert spec is not None and spec.loader is not None
gated = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gated)


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def result(outcome, detail="ok"):
    return types.SimpleNamespace(outcome=outcome, detail=detail)


class ResolveTargetsTests(unittest.TestCase):
    def test_parses_urls_into_cache_paths(self):
        run = unittest.mock.Mock(side_effect=[
            completed(0, "https://mirror.example/core/os/x86_64/pkg-1-1-x86_64.pkg.tar.zst\n"
                         "https://mirror.example/core/os/x86_64/dep-2-1-x86_64.pkg.tar.zst\n"),
            completed(0, "/var/cache/pacman/pkg/\n"),
        ])
        targets = gated.resolve_targets("pkg", run=run)
        self.assertEqual(targets, [
            "/var/cache/pacman/pkg/pkg-1-1-x86_64.pkg.tar.zst",
            "/var/cache/pacman/pkg/dep-2-1-x86_64.pkg.tar.zst",
        ])

    def test_falls_back_to_default_cache_dir_when_pacman_conf_fails(self):
        run = unittest.mock.Mock(side_effect=[
            completed(0, "https://mirror.example/core/os/x86_64/pkg-1-1-x86_64.pkg.tar.zst\n"),
            completed(1, "", "pacman-conf: config not found"),
        ])
        targets = gated.resolve_targets("pkg", run=run)
        self.assertEqual(targets, [f"{gated.DEFAULT_CACHE_DIR}/pkg-1-1-x86_64.pkg.tar.zst"])

    def test_nonzero_sp_exit_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(1, "", "target not found: pkg"))
        with self.assertRaises(gated.GatedInstallError):
            gated.resolve_targets("pkg", run=run)

    def test_empty_sp_output_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(0, ""))
        with self.assertRaises(gated.GatedInstallError):
            gated.resolve_targets("pkg", run=run)

    def test_spawn_failure_is_refused(self):
        run = unittest.mock.Mock(side_effect=FileNotFoundError())
        with self.assertRaises(gated.GatedInstallError):
            gated.resolve_targets("pkg", run=run)


class DownloadAndInstallTests(unittest.TestCase):
    def test_download_nonzero_exit_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(1, "", "could not download"))
        with self.assertRaises(gated.GatedInstallError):
            gated.download("pkg", run=run)

    def test_download_success_returns_none(self):
        run = unittest.mock.Mock(return_value=completed(0))
        self.assertIsNone(gated.download("pkg", run=run))

    def test_install_nonzero_exit_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(1, "", "transaction failed"))
        with self.assertRaises(gated.GatedInstallError):
            gated.install(["/var/cache/pacman/pkg/pkg-1-1-x86_64.pkg.tar.zst"], run=run)

    def test_install_invokes_pacman_dash_u_with_every_resolved_path(self):
        run = unittest.mock.Mock(return_value=completed(0))
        paths = ["/var/cache/pacman/pkg/a.pkg.tar.zst", "/var/cache/pacman/pkg/b.pkg.tar.zst"]
        gated.install(paths, run=run)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ["pacman", "-U", "--noconfirm"])
        self.assertEqual(argv[-2:], paths)


class VerifyDownloadedTests(unittest.TestCase):
    def test_missing_file_is_refused(self):
        with self.assertRaises(gated.GatedInstallError):
            gated.verify_downloaded(["/nonexistent/path/definitely-not-here.pkg.tar.zst"])

    def test_all_present_passes(self):
        with patch("os.path.isfile", return_value=True):
            gated.verify_downloaded(["/var/cache/pacman/pkg/a.pkg.tar.zst"])


class ScanAllTests(unittest.TestCase):
    def test_clean_result_for_every_file_passes(self):
        with patch.object(gated, "scan_path", return_value=result("clean")) as mock_scan:
            gated.scan_all(["/a", "/b"])
            self.assertEqual(mock_scan.call_count, 2)

    def test_any_non_clean_outcome_is_refused(self):
        for outcome in ("detected", "error", "cancelled"):
            with self.subTest(outcome=outcome):
                with patch.object(gated, "scan_path", return_value=result(outcome)):
                    with self.assertRaises(gated.GatedInstallError):
                        gated.scan_all(["/a"])

    def test_second_file_detection_stops_before_further_scans(self):
        with patch.object(gated, "scan_path", side_effect=[
            result("clean"), result("detected", "EICAR-Test-Signature"),
        ]) as mock_scan:
            with self.assertRaises(gated.GatedInstallError):
                gated.scan_all(["/a", "/b", "/c"])
            self.assertEqual(mock_scan.call_count, 2)  # never reached "/c"


class RunGatedInstallIntegrationTests(unittest.TestCase):
    """End-to-end orchestration: pacman -U must be unreachable on any failure."""

    def test_full_clean_run_resolves_downloads_scans_then_installs_in_order(self):
        sp_result = completed(0, "https://mirror.example/core/os/x86_64/pkg-1-1-x86_64.pkg.tar.zst\n")
        cache_result = completed(0, "/var/cache/pacman/pkg/\n")
        download_result = completed(0)
        install_result = completed(0)
        run = unittest.mock.Mock(side_effect=[sp_result, cache_result, download_result, install_result])
        with patch("os.path.isfile", return_value=True), \
             patch.object(gated, "scan_path", return_value=result("clean")) as mock_scan:
            gated.run_gated_install("pkg", run=run)
            self.assertEqual(mock_scan.call_count, 1)
        install_call = run.call_args_list[-1]
        self.assertIn("-U", install_call.args[0])

    def test_detection_blocks_install_entirely(self):
        sp_result = completed(0, "https://mirror.example/core/os/x86_64/pkg-1-1-x86_64.pkg.tar.zst\n")
        cache_result = completed(0, "/var/cache/pacman/pkg/\n")
        download_result = completed(0)
        run = unittest.mock.Mock(side_effect=[sp_result, cache_result, download_result])
        with patch("os.path.isfile", return_value=True), \
             patch.object(gated, "scan_path", return_value=result("detected", "malware")):
            with self.assertRaises(gated.GatedInstallError):
                gated.run_gated_install("pkg", run=run)
        # Only -Sp, CacheDir, -Sw ran. -U must never be called.
        self.assertEqual(run.call_count, 3)
        for made_call in run.call_args_list:
            self.assertNotIn("-U", made_call.args[0])

    def test_download_failure_means_scan_never_runs(self):
        sp_result = completed(0, "https://mirror.example/core/os/x86_64/pkg-1-1-x86_64.pkg.tar.zst\n")
        cache_result = completed(0, "/var/cache/pacman/pkg/\n")
        download_result = completed(1, "", "network unreachable")
        run = unittest.mock.Mock(side_effect=[sp_result, cache_result, download_result])
        with patch.object(gated, "scan_path") as mock_scan:
            with self.assertRaises(gated.GatedInstallError):
                gated.run_gated_install("pkg", run=run)
            mock_scan.assert_not_called()

    def test_resolution_mismatch_after_download_is_refused_before_scanning(self):
        sp_result = completed(0, "https://mirror.example/core/os/x86_64/pkg-1-1-x86_64.pkg.tar.zst\n")
        cache_result = completed(0, "/var/cache/pacman/pkg/\n")
        download_result = completed(0)
        run = unittest.mock.Mock(side_effect=[sp_result, cache_result, download_result])
        with patch("os.path.isfile", return_value=False), \
             patch.object(gated, "scan_path") as mock_scan:
            with self.assertRaises(gated.GatedInstallError):
                gated.run_gated_install("pkg", run=run)
            mock_scan.assert_not_called()


class MainTests(unittest.TestCase):
    def test_refuses_when_not_root(self):
        with patch("os.geteuid", return_value=1000):
            self.assertEqual(gated.main(["prog", "--", "pkg"]), 2)

    def test_wrong_argument_count_is_usage_error(self):
        with patch("os.geteuid", return_value=0):
            self.assertEqual(gated.main(["prog"]), 2)
            self.assertEqual(gated.main(["prog", "--", "a", "b"]), 2)

    def test_success_exits_zero(self):
        with patch("os.geteuid", return_value=0), \
             patch.object(gated, "run_gated_install", return_value=None) as mocked:
            self.assertEqual(gated.main(["prog", "--", "pkg"]), 0)
            mocked.assert_called_once_with("pkg")

    def test_blocked_install_exits_one_not_zero(self):
        with patch("os.geteuid", return_value=0), \
             patch.object(gated, "run_gated_install", side_effect=gated.GatedInstallError("blocked")):
            self.assertEqual(gated.main(["prog", "--", "pkg"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
