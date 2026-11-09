#!/usr/bin/env python3
"""Every shipped app and shell module is registered where the ISO build looks.

A new file under airootfs/usr/local/bin only reaches the ISO if build-iso.sh
copies it, profiledef.sh gives it a mode, and ci/verify-iso.sh checks it. Miss
one and the failure shows up only after a 20-minute ISO build (or, worse, not
at all: an app that is simply absent). This test catches it in a second.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
APPS = ROOT / "airootfs/usr/share/applications"

BUILD = (ROOT / "build-iso.sh").read_text(encoding="utf-8")
PROFILE = (ROOT / "profiledef.sh").read_text(encoding="utf-8")
VERIFY = (ROOT / "ci/verify-iso.sh").read_text(encoding="utf-8")

# Library modules appear in two build-iso.sh lists and at least two
# verify-iso.sh lists (payload, library_modules; newer ones also required_files);
# apps in one of each.
MODULE_MIN = {"build": 2, "profile": 1, "verify": 2}
APP_MIN = {"build": 1, "profile": 1, "verify": 1}

# Present before this test existed and in none of the three registries. They
# are started with `python <path>` or by sudo, so they do reach the ISO (archiso
# copies all of airootfs), but build-iso.sh and verify-iso.sh never check them.
# Grandfathered, not blessed: register one and the test below tells you to
# delete it from this set. Nothing new may be added here.
UNREGISTERED_MODULES = {"continuous_watch.py", "palette.py", "quarantine.py"}
UNREGISTERED_APPS = {
    "darkos-integrity-check.py", "darkos-netwatch.py", "darkos-protect.py", "darkos-snapshot.py",
}


def count(text, rel, leading_slash=False):
    needle = ("/" if leading_slash else "") + rel
    # Whole-path match: `darkos-store.py` must not be satisfied by
    # `darkos-store.py.bak`, nor `foo.py` by `darkos_foo.py`.
    return len(re.findall(r"(?<![\w./-])" + re.escape(needle) + r"(?![\w.-])", text))


class RegistrationTests(unittest.TestCase):
    def check(self, rel, minimums):
        problems = []
        for key, text, slash in (("build", BUILD, False), ("profile", PROFILE, True),
                                 ("verify", VERIFY, False)):
            seen = count(text, rel, slash)
            if seen < minimums[key]:
                problems.append(f"{key}: listed {seen}x, needs {minimums[key]}")
        return problems

    def test_every_shell_module_is_registered(self):
        modules = sorted((BIN / "darkos_shell").glob("*.py"))
        self.assertGreaterEqual(len(modules), 8)
        bad = {}
        for path in modules:
            if path.name in UNREGISTERED_MODULES:
                continue
            problems = self.check(f"usr/local/bin/darkos_shell/{path.name}", MODULE_MIN)
            if problems:
                bad[path.name] = problems
        self.assertEqual(bad, {})

    def test_every_native_app_is_registered(self):
        apps = sorted(BIN.glob("darkos-*.py"))
        self.assertGreaterEqual(len(apps), 20)
        bad = {}
        for path in apps:
            if path.name in UNREGISTERED_APPS:
                continue
            problems = self.check(f"usr/local/bin/{path.name}", APP_MIN)
            if problems:
                bad[path.name] = problems
        self.assertEqual(bad, {})

    def test_every_launcher_is_verified_and_points_at_a_real_script(self):
        bad = {}
        for desktop in sorted(APPS.glob("darkos-*.desktop")):
            text = desktop.read_text(encoding="utf-8")
            exec_line = next((l for l in text.splitlines() if l.startswith("Exec=")), "")
            target = exec_line.split("=", 1)[1].split()[0] if exec_line else ""
            problems = []
            if target.startswith("/usr/local/bin/") and not (ROOT / "airootfs" / target.lstrip("/")).exists():
                problems.append(f"Exec target missing: {target}")
            if count(VERIFY, f"usr/share/applications/{desktop.name}") < 1 and target.endswith(".py"):
                problems.append("not in verify-iso.sh native_desktop_entries")
            if problems:
                bad[desktop.name] = problems
        self.assertEqual(bad, {})

    def test_the_grandfather_list_only_shrinks(self):
        stale = []
        for name in sorted(UNREGISTERED_MODULES):
            rel = f"usr/local/bin/darkos_shell/{name}"
            if not (BIN / "darkos_shell" / name).exists() or not self.check(rel, MODULE_MIN):
                stale.append(name)
        for name in sorted(UNREGISTERED_APPS):
            rel = f"usr/local/bin/{name}"
            if not (BIN / name).exists() or not self.check(rel, APP_MIN):
                stale.append(name)
        self.assertEqual(stale, [], "now registered or deleted: remove from the grandfather sets")

    def test_the_counter_can_fail(self):
        # Guard the guard: a path that is not registered must report 0.
        self.assertEqual(count(BUILD, "usr/local/bin/darkos-does-not-exist.py"), 0)
        # ...and a prefix must not satisfy a longer name.
        self.assertEqual(count("usr/local/bin/darkos-store.py.bak", "usr/local/bin/darkos-store.py"), 0)


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
