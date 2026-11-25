#!/usr/bin/env python3
"""Every pacman package the Store catalogue names exists in the repositories pacman knows.

    python ci/test-store-catalogue-live.py

This is the one check that needs a real pacman with synced databases, so it runs on the Arch CI runner and
skips everywhere else (a laptop, the Ubuntu sandbox) with the reason printed. The catalogue's package names are
typed from knowledge, not from a repository, so this is what turns "believed to exist" into "exists".

Packages already in packages.x86_64 are not asked about again: the ISO build resolves those (some live in
multilib, which a stock container does not enable). Every other name must be in the databases pacman has.
"""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "airootfs/usr/local/bin"))

from darkos_shell import store_catalog  # noqa: E402


def pacman(*args):
    done = subprocess.run(["pacman", *args], capture_output=True, text=True, timeout=60, check=False)
    return done.returncode, done.stdout + done.stderr


def base_packages():
    names = set()
    for line in (ROOT / "packages.x86_64").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line)
    return names


class LiveRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("pacman"):
            raise unittest.SkipTest("no pacman here; this runs on the Arch CI runner")
        code, _out = pacman("-Si", "pacman")
        if code != 0:
            raise unittest.SkipTest("pacman has no synced package databases here (pacman -Syu has not run)")

    def test_every_pacman_package_in_the_catalogue_exists(self):
        base = base_packages()
        missing, checked = [], 0
        for entry in store_catalog.ENTRIES:
            if entry.source != store_catalog.SOURCE_PACMAN:
                continue
            for name in entry.packages:
                if name in base:
                    continue
                checked += 1
                code, out = pacman("-Si", "--", name)
                if code != 0:
                    missing.append(f"{entry.id}: {name}  ({out.strip().splitlines()[-1] if out.strip() else 'no output'})")
        self.assertGreater(checked, 10, "the check looked at too few packages to mean anything")
        self.assertEqual(missing, [], "catalogue names pacman cannot find; fix the name or drop the entry:\n  "
                         + "\n  ".join(missing))

    def test_the_download_plan_reads_the_way_the_store_parses_it(self):
        """The Store sizes an install from `pacman -Sp --print-format %s`: one integer line per package to fetch."""
        from darkos_shell import store_actions
        for probe in ("htop", "tree", "strace", "lsof"):
            code, out = pacman("-Sp", "--print-format", "%s", "--", probe)
            if code != 0:
                continue
            count, total = store_actions.parse_print_sizes(out)
            if count == 0:
                continue                      # already installed here: prints nothing, proves nothing
            self.assertGreater(total, 0)
            for line in (l for l in out.splitlines() if l.strip()):
                self.assertTrue(line.strip().isdigit() or line.startswith(("warning", "error")),
                                f"unexpected line from pacman -Sp: {line!r}")
            return
        self.skipTest("every probe package is already installed or unplannable here")


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
