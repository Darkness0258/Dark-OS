#!/usr/bin/env python3
"""AUR install-gate regressions.

Verifies darkos-store-gated-aur-install.py: validate -> clone -> show
PKGBUILD + require y/N -> build (never as root) -> resolve -> verify -> scan
-> install. Any refusal at any step must make pacman -U unreachable. Same
loading trick as ci/test-store-gated-install.py (bypass darkos_shell's
package __init__, which needs GTK) with a lightweight stand-in for
darkos_shell.shield. Each test patches gated.scan_path for the duration of
that test only.
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
if "darkos_shell" not in sys.modules:
    darkos_shell_pkg = types.ModuleType("darkos_shell")
    darkos_shell_pkg.__path__ = []
    shield_stub = types.ModuleType("darkos_shell.shield")
    shield_stub.scan_path = lambda *_a, **_kw: None
    sys.modules["darkos_shell"] = darkos_shell_pkg
    sys.modules["darkos_shell.shield"] = shield_stub

spec = importlib.util.spec_from_file_location(
    "darkos_store_gated_aur_install_tested",
    ROOT / "airootfs/usr/local/bin/darkos-store-gated-aur-install.py",
)
assert spec is not None and spec.loader is not None
gated = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gated)


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def result(outcome, detail="ok"):
    return types.SimpleNamespace(outcome=outcome, detail=detail)


class ValidatePkgNameTests(unittest.TestCase):
    def test_accepts_normal_names(self):
        for name in ("firefox", "visual-studio-code-bin", "python-numpy", "a.b_c+d@e"):
            with self.subTest(name=name):
                gated.validate_pkg_name(name)  # must not raise

    def test_rejects_shell_metacharacters_and_empty(self):
        for name in ("", "; rm -rf ~", "$(whoami)", "../etc/passwd", "pkg name", "-leading-dash"):
            with self.subTest(name=name):
                with self.assertRaises(gated.GatedInstallError):
                    gated.validate_pkg_name(name)


class CloneAndReadTests(unittest.TestCase):
    def test_clone_nonzero_exit_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(1, "", "repository not found"))
        with self.assertRaises(gated.GatedInstallError):
            gated.clone("pkg", "/tmp/workdir", run=run)

    def test_clone_uses_the_real_aur_url(self):
        run = unittest.mock.Mock(return_value=completed(0))
        gated.clone("mypkg", "/tmp/workdir", run=run)
        argv = run.call_args.args[0]
        self.assertIn("https://aur.archlinux.org/mypkg.git", argv)

    def test_clone_spawn_failure_is_refused(self):
        run = unittest.mock.Mock(side_effect=FileNotFoundError())
        with self.assertRaises(gated.GatedInstallError):
            gated.clone("pkg", "/tmp/workdir", run=run)

    def test_read_pkgbuild_missing_file_is_refused(self):
        with self.assertRaises(gated.GatedInstallError):
            gated.read_pkgbuild(Path("/nonexistent/definitely-not-here"))


class BuildTests(unittest.TestCase):
    def test_refuses_to_build_as_root(self):
        with patch("os.geteuid", return_value=0):
            with self.assertRaises(gated.GatedInstallError):
                gated.build(Path("/tmp/pkgdir"), run=unittest.mock.Mock())

    def test_nonzero_exit_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(1, "", "==> ERROR: a failure occurred"))
        with patch("os.geteuid", return_value=1000):
            with self.assertRaises(gated.GatedInstallError):
                gated.build(Path("/tmp/pkgdir"), run=run)

    def test_success_returns_none(self):
        run = unittest.mock.Mock(return_value=completed(0))
        with patch("os.geteuid", return_value=1000):
            self.assertIsNone(gated.build(Path("/tmp/pkgdir"), run=run))


class ResolveBuiltPackagesTests(unittest.TestCase):
    def test_parses_multiple_lines(self):
        run = unittest.mock.Mock(return_value=completed(0, "/tmp/pkgdir/a-1-1-x86_64.pkg.tar.zst\n"))
        self.assertEqual(gated.resolve_built_packages(Path("/tmp/pkgdir"), run=run),
                          ["/tmp/pkgdir/a-1-1-x86_64.pkg.tar.zst"])

    def test_nonzero_exit_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(1, "", "malformed PKGBUILD"))
        with self.assertRaises(gated.GatedInstallError):
            gated.resolve_built_packages(Path("/tmp/pkgdir"), run=run)

    def test_empty_output_is_refused(self):
        run = unittest.mock.Mock(return_value=completed(0, ""))
        with self.assertRaises(gated.GatedInstallError):
            gated.resolve_built_packages(Path("/tmp/pkgdir"), run=run)


class VerifyBuiltTests(unittest.TestCase):
    def test_missing_file_is_refused(self):
        with self.assertRaises(gated.GatedInstallError):
            gated.verify_built(["/nonexistent/definitely-not-here.pkg.tar.zst"])

    def test_all_present_passes(self):
        with patch("os.path.isfile", return_value=True):
            gated.verify_built(["/tmp/pkgdir/a.pkg.tar.zst"])


class ScanAllTests(unittest.TestCase):
    def test_clean_passes(self):
        with patch.object(gated, "scan_path", return_value=result("clean")) as mock_scan:
            gated.scan_all(["/a"])
            mock_scan.assert_called_once()

    def test_non_clean_outcome_is_refused(self):
        with patch.object(gated, "scan_path", return_value=result("detected", "malware")):
            with self.assertRaises(gated.GatedInstallError):
                gated.scan_all(["/a"])


class ConfirmBuildTests(unittest.TestCase):
    def test_yes_returns_true(self):
        for answer in ("y", "Y", " y "):
            with self.subTest(answer=answer):
                prompt = unittest.mock.Mock(return_value=answer)
                self.assertTrue(gated.confirm_build("pkgbuild text", "pkg", prompt=prompt))

    def test_anything_else_returns_false(self):
        for answer in ("n", "", "yes", "no"):
            with self.subTest(answer=answer):
                prompt = unittest.mock.Mock(return_value=answer)
                self.assertFalse(gated.confirm_build("pkgbuild text", "pkg", prompt=prompt))

    def test_prints_the_actual_pkgbuild_text(self):
        prompt = unittest.mock.Mock(return_value="n")
        with patch("builtins.print") as mock_print:
            gated.confirm_build("MARKER-PKGBUILD-CONTENT", "pkg", prompt=prompt)
        printed = "\n".join(str(call.args[0]) if call.args else "" for call in mock_print.call_args_list)
        self.assertIn("MARKER-PKGBUILD-CONTENT", printed)


class RunGatedAurInstallIntegrationTests(unittest.TestCase):
    """End-to-end orchestration: pacman -U must be unreachable on any refusal."""

    def _mocks(self, clone_ok=True, build_ok=True, packagelist="/w/pkg/a-1-1-x86_64.pkg.tar.zst\n"):
        run = unittest.mock.Mock(side_effect=[
            completed(0 if clone_ok else 1, "", "" if clone_ok else "clone failed"),
            completed(0 if build_ok else 1, "", "" if build_ok else "build failed"),
            completed(0, packagelist),
            completed(0),
        ])
        return run

    def test_declining_the_pkgbuild_review_blocks_everything_after(self):
        run = unittest.mock.Mock(return_value=completed(0))
        with patch.object(Path, "read_text", return_value="some pkgbuild"), \
             patch.object(gated, "build") as mock_build, \
             patch.object(gated, "scan_path") as mock_scan:
            with self.assertRaises(gated.GatedInstallError):
                gated.run_gated_aur_install("pkg", "/tmp/w", run=run, prompt=lambda _p: "n")
            mock_build.assert_not_called()
            mock_scan.assert_not_called()

    def test_full_clean_run_installs(self):
        run = self._mocks()
        with patch.object(Path, "read_text", return_value="some pkgbuild"), \
             patch("os.geteuid", return_value=1000), \
             patch("os.path.isfile", return_value=True), \
             patch.object(gated, "scan_path", return_value=result("clean")) as mock_scan:
            gated.run_gated_aur_install("pkg", "/tmp/w", run=run, prompt=lambda _p: "y")
            mock_scan.assert_called_once()
        install_call = run.call_args_list[-1]
        self.assertIn("-U", install_call.args[0])
        self.assertIn("sudo", install_call.args[0])

    def test_build_failure_means_scan_never_runs(self):
        run = self._mocks(build_ok=False)
        with patch.object(Path, "read_text", return_value="some pkgbuild"), \
             patch("os.geteuid", return_value=1000), \
             patch.object(gated, "scan_path") as mock_scan:
            with self.assertRaises(gated.GatedInstallError):
                gated.run_gated_aur_install("pkg", "/tmp/w", run=run, prompt=lambda _p: "y")
            mock_scan.assert_not_called()

    def test_detected_scan_blocks_install(self):
        run = self._mocks()
        with patch.object(Path, "read_text", return_value="some pkgbuild"), \
             patch("os.geteuid", return_value=1000), \
             patch("os.path.isfile", return_value=True), \
             patch.object(gated, "scan_path", return_value=result("detected", "malware")):
            with self.assertRaises(gated.GatedInstallError):
                gated.run_gated_aur_install("pkg", "/tmp/w", run=run, prompt=lambda _p: "y")
        # clone, build, packagelist ran (3 calls); -U (4th) must never happen.
        self.assertEqual(run.call_count, 3)

    def test_clone_failure_stops_before_any_prompt(self):
        run = self._mocks(clone_ok=False)
        prompt = unittest.mock.Mock()
        with self.assertRaises(gated.GatedInstallError):
            gated.run_gated_aur_install("pkg", "/tmp/w", run=run, prompt=prompt)
        prompt.assert_not_called()


class MainTests(unittest.TestCase):
    def test_refuses_when_root(self):
        with patch("os.geteuid", return_value=0):
            self.assertEqual(gated.main(["prog", "--", "pkg"]), 2)

    def test_wrong_argument_count_is_usage_error(self):
        with patch("os.geteuid", return_value=1000):
            self.assertEqual(gated.main(["prog"]), 2)
            self.assertEqual(gated.main(["prog", "--", "a", "b"]), 2)

    def test_success_exits_zero_and_cleans_up_workdir(self):
        with patch("os.geteuid", return_value=1000), \
             patch.object(gated.tempfile, "mkdtemp", return_value="/tmp/darkos-aur-xyz"), \
             patch.object(gated.shutil, "rmtree") as mock_rmtree, \
             patch.object(gated, "run_gated_aur_install", return_value=None) as mocked:
            self.assertEqual(gated.main(["prog", "--", "pkg"]), 0)
            mocked.assert_called_once_with("pkg", "/tmp/darkos-aur-xyz")
            mock_rmtree.assert_called_once_with("/tmp/darkos-aur-xyz", ignore_errors=True)

    def test_blocked_install_exits_one_and_still_cleans_up(self):
        with patch("os.geteuid", return_value=1000), \
             patch.object(gated.tempfile, "mkdtemp", return_value="/tmp/darkos-aur-xyz"), \
             patch.object(gated.shutil, "rmtree") as mock_rmtree, \
             patch.object(gated, "run_gated_aur_install",
                           side_effect=gated.GatedInstallError("blocked")):
            self.assertEqual(gated.main(["prog", "--", "pkg"]), 1)
            mock_rmtree.assert_called_once_with("/tmp/darkos-aur-xyz", ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
