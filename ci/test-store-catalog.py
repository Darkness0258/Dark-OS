#!/usr/bin/env python3
"""Store catalogue, starter packs and the actions behind them: data rules, parsers, scripts, safe data deletion.

    python ci/test-store-catalog.py

No GTK window is opened and nothing touches the real system: pacman, flatpak and sudo are replaced by fakes on a
temporary PATH, and the install/remove scripts that run in the terminal are executed for real against them, so
what is tested is the shell logic itself, not a description of it. Every deletion happens inside a temp HOME.
"""
import ast
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

from darkos_shell import store_actions as actions  # noqa: E402
from darkos_shell import store_catalog as catalog  # noqa: E402

ACTIONS_PATH = BIN / "darkos_shell" / "store_actions.py"
BANNED_WORDS = {"best", "popular", "featured", "trending", "top", "leading", "recommended", "award", "free",
                "fastest", "ultimate", "#1"}
GENERIC_DIRS = {".config", ".cache", ".local", ".local/share", ".local/state", ".ssh", ".gnupg", "Documents",
                "Downloads", "Pictures", "Music", "Videos", "Desktop"}


class CatalogueRules(unittest.TestCase):
    def test_ids_and_names_are_unique_slugs(self):
        ids = [entry.id for entry in catalog.ENTRIES]
        self.assertEqual(len(ids), len(set(ids)))
        names = [entry.name for entry in catalog.ENTRIES]
        self.assertEqual(len(names), len(set(names)))
        for entry in catalog.ENTRIES:
            self.assertRegex(entry.id, r"^[a-z0-9][a-z0-9-]*$")

    def test_every_entry_passes_the_name_checks_that_guard_the_command_line(self):
        for entry in catalog.ENTRIES:
            actions.check_entry(entry)

    def test_a_package_belongs_to_one_entry_only(self):
        seen = {}
        for entry in catalog.ENTRIES:
            for name in entry.packages:
                self.assertNotIn((entry.source, name), seen, f"{name} is in {entry.id} and {seen.get((entry.source, name))}")
                seen[(entry.source, name)] = entry.id

    def test_sources_and_categories_are_real_and_used(self):
        categories = dict(catalog.CATEGORIES)
        for entry in catalog.ENTRIES:
            self.assertIn(entry.source, catalog.SOURCES)
            self.assertIn(entry.category, categories)
        for category in categories:
            self.assertTrue(catalog.in_category(category), f"empty category {category}")

    def test_summaries_are_plain_and_never_sell(self):
        for entry in catalog.ENTRIES:
            self.assertTrue(entry.summary.endswith("."), entry.id)
            self.assertLessEqual(len(entry.summary), 70, entry.id)
            words = {w.strip(".,").lower() for w in entry.summary.split()}
            self.assertFalse(words & BANNED_WORDS, f"{entry.id}: {words & BANNED_WORDS}")

    def test_entries_carry_no_invented_metadata(self):
        """Sizes, ratings, permissions and login behaviour are read live or shown as Unknown, never typed in."""
        fields = set(catalog.Entry.__dataclass_fields__)
        self.assertEqual(fields, {"id", "name", "summary", "category", "source", "packages", "data_paths"})

    def test_data_paths_are_app_specific_and_safe(self):
        home = tempfile.mkdtemp()
        taken = {}
        for entry in catalog.ENTRIES:
            if entry.source == catalog.SOURCE_FLATPAK:
                self.assertEqual(entry.data_paths, (), f"{entry.id}: Flatpak deletes its own data")
            for relative in entry.data_paths:
                self.assertIsNotNone(actions.safe_data_path(home, relative), f"{entry.id}: {relative}")
                self.assertNotIn(relative, GENERIC_DIRS, f"{entry.id}: {relative} is not specific to the app")
                self.assertNotIn(relative.split("/")[0], {"Documents", "Downloads", "Pictures", "Music", "Videos",
                                                          "Desktop"}, f"{entry.id} must not delete the person's files")
                self.assertNotIn(relative, taken, f"{relative} is claimed by {entry.id} and {taken.get(relative)}")
                taken[relative] = entry.id

    def test_the_two_catalogue_modules_never_import_a_toolkit(self):
        for name in ("store_catalog.py", "store_actions.py"):
            tree = ast.parse((BIN / "darkos_shell" / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                for module in modules:
                    self.assertNotIn(module.split(".")[0], {"gi", "cairo"}, f"{name} imports {module}")


class Packs(unittest.TestCase):
    def test_six_packs_in_a_fixed_order(self):
        self.assertEqual([pack.name for pack in catalog.PACKS],
                         ["Everyday", "Student", "Developer", "Creator", "Gamer", "Office"])

    def test_pack_members_exist_without_repeats_and_are_a_sensible_size(self):
        for pack in catalog.PACKS:
            self.assertEqual(len(pack.entries), len(set(pack.entries)), pack.id)
            self.assertTrue(3 <= len(pack.entries) <= 10, pack.id)
            for entry_id in pack.entries:
                self.assertIsNotNone(catalog.get(entry_id), f"{pack.id}: {entry_id}")
            self.assertEqual([e.id for e in catalog.pack_entries(pack.id)], list(pack.entries))

    def test_apps_the_base_image_will_shed_have_a_home(self):
        """The base diet moves these out of packages.x86_64; each must already be an entry in the right pack."""
        wanted = {"everyday": {"geary", "kooha"}, "gamer": {"steam", "lutris", "wine", "waydroid"}}
        for pack_id, ids in wanted.items():
            self.assertTrue(ids <= set(catalog.pack(pack_id).entries), pack_id)
        pacman, _flatpak = catalog.packages_of([catalog.get(i) for i in ("geary", "kooha", "steam", "lutris", "wine",
                                                                         "waydroid")])
        for package in ("geary", "kooha", "steam", "lutris", "wine", "wine-gecko", "wine-mono", "winetricks",
                        "waydroid"):
            self.assertIn(package, pacman)

    def test_recommend_is_static_and_changes_nothing(self):
        first = catalog.recommend()
        self.assertEqual(first, list(catalog.PACKS))
        self.assertEqual(catalog.recommend({"role": "student", "gpu": "nvidia"}), first)
        first.clear()
        self.assertEqual(len(catalog.recommend()), 6, "callers get a copy")

    def test_packages_of_merges_without_repeats(self):
        pacman, flatpak = catalog.packages_of(catalog.pack_entries("student") + catalog.pack_entries("office"))
        self.assertEqual(len(pacman), len(set(pacman)))
        self.assertEqual(pacman.count("libreoffice-fresh"), 1)
        self.assertEqual(flatpak, ["net.ankiweb.Anki", "md.obsidian.Obsidian", "org.zotero.Zotero"])


class Lookups(unittest.TestCase):
    def test_search(self):
        self.assertEqual(len(catalog.search("")), len(catalog.ENTRIES))
        self.assertEqual({e.id for e in catalog.search("PHOTO")}, {"gimp", "darktable", "simple-scan"})
        self.assertEqual([e.id for e in catalog.search("video editing")], ["kdenlive"])
        self.assertIn("libreoffice", {e.id for e in catalog.search("office")}, "category label is searched")
        self.assertEqual(catalog.search("zzzz-no-such-app"), [])
        self.assertEqual([e.id for e in catalog.search("compiler", entries=[catalog.get("go"), catalog.get("gimp")])], ["go"])

    def test_source_labels_are_honest(self):
        self.assertIn("Unscanned", catalog.badge("flatpak"))
        self.assertNotIn("Unscanned", catalog.badge("pacman"))
        self.assertIn("Shield scans", catalog.source_note("pacman"))
        self.assertIn("does not scan", catalog.source_note("flatpak"))


class Parsers(unittest.TestCase):
    def test_parse_size(self):
        self.assertEqual(actions.parse_size("12.34 MiB"), 12939428)
        self.assertEqual(actions.parse_size("107.8 MB"), 107800000)
        self.assertEqual(actions.parse_size("1,5 GB"), 1500000000)
        self.assertEqual(actions.parse_size("< 1 kB"), 1000)
        self.assertEqual(actions.parse_size("512 B"), 512)
        for bad in ("", None, "big", "12 parsecs", "MiB"):
            self.assertIsNone(actions.parse_size(bad), bad)

    def test_parse_pacman_si(self):
        block = ("Repository      : extra\nName            : gimp\nVersion         : 3.0.4-1\n"
                 "Download Size   : 22.08 MiB\nInstalled Size  : 98.21 MiB\nPackager        : Someone\n")
        self.assertEqual(actions.parse_pacman_si(block), {"download": 23152558, "installed": 102980649})
        self.assertEqual(actions.parse_pacman_si("error: package 'x' was not found"),
                         {"download": None, "installed": None})

    def test_parse_print_sizes_ignores_noise(self):
        self.assertEqual(actions.parse_print_sizes("1234\n5678\nwarning: something\n\n"), (2, 6912))
        self.assertEqual(actions.parse_print_sizes(""), (0, 0))

    def test_parse_flatpak_remote_info(self):
        text = "Ref: app/net.ankiweb.Anki/x86_64/stable\nID: net.ankiweb.Anki\nDownload: 107.8 MB\nInstalled: 360.6 MB\n"
        self.assertEqual(actions.parse_flatpak_remote_info(text), {"download": 107800000, "installed": 360600000})
        self.assertEqual(actions.parse_flatpak_remote_info("error: nope"), {"download": None, "installed": None})

    def test_human_size_never_invents(self):
        self.assertEqual(actions.human_size(None), "Unknown")
        self.assertEqual(actions.human_size(0), "0 B")
        self.assertEqual(actions.human_size(1536), "1.5 KiB")
        self.assertEqual(actions.human_size(5 * 1024 ** 3), "5.0 GiB")

    def test_permissions_plain_app(self):
        metadata = ("[Application]\nname=net.ankiweb.Anki\ncommand=anki\n\n[Context]\nshared=network;ipc;\n"
                    "sockets=x11;wayland;pulseaudio;fallback-x11;\ndevices=dri;\nfilesystems=xdg-download;/tmp;\n\n"
                    "[Session Bus Policy]\norg.freedesktop.Notifications=talk\n")
        found = actions.parse_permissions(metadata)
        self.assertEqual([p.text for p in found], ["Uses the network", "Plays and records sound",
                                                   "Graphics acceleration", "Downloads folder", "Folder /tmp"])
        self.assertFalse(any(p.broad for p in found))

    def test_permissions_broad_ones_are_flagged_and_unknown_ones_are_not_hidden(self):
        metadata = ("[Context]\nshared=network;\nsockets=ssh-auth;weird-socket;\ndevices=all;\n"
                    "filesystems=host;home:ro;!xdg-music;~/.mozilla:create;\n")
        found = {p.text: p.broad for p in actions.parse_permissions(metadata)}
        self.assertTrue(found["Every file on this computer"])
        self.assertTrue(found["Uses your SSH keys"])
        self.assertTrue(found["Every device"])
        self.assertIn("Socket: weird-socket", found)
        self.assertIn("Folder ~/.mozilla (can create it)", found)
        self.assertNotIn("Music folder", found, "a denied location is not a permission")
        self.assertFalse(found["Your whole home folder (read-only)"], "read-only home is not flagged as broad")

    def test_permissions_of_nothing_is_nothing(self):
        for text in ("", None, "not a keyfile at all", "[Application]\nname=x\n"):
            self.assertEqual(actions.parse_permissions(text), [])

    def test_autostart_entries(self):
        listing = ("kdeconnect /usr/\nkdeconnect /etc/xdg/autostart/org.kde.kdeconnect.daemon.desktop\n"
                   "kdeconnect /etc/xdg/autostart/notes.txt\nkdeconnect /usr/share/applications/x.desktop\n")
        self.assertEqual(actions.autostart_entries(listing), ["/etc/xdg/autostart/org.kde.kdeconnect.daemon.desktop"])
        self.assertEqual(actions.autostart_entries(""), [])
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(actions.autostart_entries(home=home, flatpak_id="a.b.C"), [])
            folder = Path(home, ".config", "autostart")
            folder.mkdir(parents=True)
            (folder / "a.b.C.desktop").write_text("[Desktop Entry]\n")
            self.assertEqual(actions.autostart_entries(home=home, flatpak_id="a.b.C"), [str(folder / "a.b.C.desktop")])


class InstalledState(unittest.TestCase):
    def test_entry_state(self):
        wine = catalog.get("wine")
        self.assertEqual(actions.entry_state(wine, set(wine.packages), set()), "installed")
        self.assertEqual(actions.entry_state(wine, {"wine"}, set()), "partial")
        self.assertEqual(actions.entry_state(wine, set(), set()), "absent")
        anki = catalog.get("anki")
        self.assertEqual(actions.entry_state(anki, set(), {"net.ankiweb.Anki"}), "installed")
        self.assertEqual(actions.entry_state(anki, {"net.ankiweb.Anki"}, set()), "absent", "sources are not mixed")

    def test_installed_sets_with_a_fake_runner(self):
        def run(argv, timeout=30):
            if argv[:2] == ["pacman", "-Qq"]:
                return 0, "git\nsteam\n"
            if argv[:2] == ["flatpak", "list"]:
                return 0, "net.ankiweb.Anki\n"
            return 1, ""
        self.assertEqual(actions.installed_sets(run), ({"git", "steam"}, {"net.ankiweb.Anki"}))
        self.assertEqual(actions.installed_sets(lambda argv, timeout=30: (127, "")), (set(), set()))

    def test_pacman_sizes_use_the_real_plan_and_say_none_when_unreadable(self):
        def run(argv, timeout=30):
            if argv[:2] == ["pacman", "-Sp"]:
                return 0, "100\n200\n"
            if argv[:2] == ["pacman", "-Si"]:
                return 0, "Installed Size  : 1.00 MiB\n"
            return 1, ""
        self.assertEqual(actions.pacman_sizes(["a", "b"], run), {"download": 300, "count": 2, "installed": 2097152})

        def broken(argv, timeout=30):
            return (1, "") if argv[:2] == ["pacman", "-Sp"] else (0, "Name : x\n")
        self.assertEqual(actions.pacman_sizes(["a"], broken), {"download": None, "count": None, "installed": None})

    def test_flatpak_details_with_and_without_flathub(self):
        def run(argv, timeout=30):
            if "--show-metadata" in argv:
                return 0, "[Context]\nshared=network;\n"
            return 0, "Download: 10 MB\nInstalled: 30 MB\n"
        found = actions.flatpak_details("a.b.C", run)
        self.assertEqual((found["download"], found["installed"]), (10000000, 30000000))
        self.assertEqual([p.text for p in found["permissions"]], ["Uses the network"])
        none = actions.flatpak_details("a.b.C", lambda argv, timeout=30: (1, ""))
        self.assertEqual(none, {"download": None, "installed": None, "permissions": None})


class SafeData(unittest.TestCase):
    def test_safe_data_path(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(actions.safe_data_path(home, ".config/inkscape"), Path(home) / ".config/inkscape")
            for bad in ("", "/etc", "../x", "a/../b", "a//b", "./a", ".config/..", None, 5):
                self.assertIsNone(actions.safe_data_path(home, bad), repr(bad))

    def test_a_parent_folder_that_is_a_symlink_out_of_home_is_refused(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "inkscape").mkdir()
            (Path(outside) / "inkscape" / "keep.txt").write_text("precious")
            os.symlink(outside, Path(home) / ".config")
            self.assertIsNone(actions.safe_data_path(home, ".config/inkscape"))
            self.assertEqual(actions.forget_data(catalog.get("inkscape"), home, log=lambda *_: None), [])
            self.assertTrue((Path(outside) / "inkscape" / "keep.txt").exists())

    def test_path_size_counts_real_files_and_does_not_follow_links(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as outside:
            root = Path(home, "app")
            root.mkdir()
            (root / "a.bin").write_bytes(b"x" * 1000)
            (root / "sub").mkdir()
            (root / "sub" / "b.bin").write_bytes(b"y" * 500)
            (Path(outside) / "huge.bin").write_bytes(b"z" * 10_000_000)
            os.symlink(outside, root / "link")
            size, complete = actions.path_size(root)
            self.assertTrue(complete)
            self.assertGreaterEqual(size, 1500)
            self.assertLess(size, 1_000_000, "a symlink is counted as a link, not as what it points at")
            self.assertEqual(actions.path_size(root, limit=1)[1], False, "a huge tree reports that it is a floor")

    def test_forget_data_deletes_only_what_the_catalogue_lists(self):
        steam = catalog.get("steam")
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as outside:
            home = Path(home)
            (home / ".local/share/Steam/steamapps").mkdir(parents=True)
            (home / ".local/share/Steam/steamapps/game.bin").write_bytes(b"x" * 10)
            outside = Path(outside)
            (outside / "target").mkdir()
            (outside / "target" / "keep.txt").write_text("keep")
            os.symlink(outside / "target", home / ".steam")                  # a link: removed as a link only
            (home / ".local/share/Other").mkdir()
            (home / ".config").mkdir()
            (home / ".config/steam-like-name").write_text("not listed")
            (home / "Documents").mkdir()
            (home / "Documents/essay.txt").write_text("mine")
            self.assertEqual({str(p.relative_to(home)) for p, _s, _c in actions.data_dirs(steam, home)},
                             {".local/share/Steam", ".steam"})
            removed = actions.forget_data(steam, home, log=lambda *_: None)
            self.assertEqual({str(p.relative_to(home)) for p in removed}, {".local/share/Steam", ".steam"})
            self.assertFalse((home / ".local/share/Steam").exists())
            self.assertFalse(os.path.lexists(home / ".steam"))
            self.assertTrue((outside / "target" / "keep.txt").exists(), "the link's target is never touched")
            for survivor in (".local/share/Other", ".config/steam-like-name", "Documents/essay.txt"):
                self.assertTrue((home / survivor).exists(), survivor)

    def test_the_cli_refuses_anything_that_is_not_a_catalogue_id(self):
        with tempfile.TemporaryDirectory() as home:
            for argument in ("../etc", "no-such-app", "STEAM", "steam; rm -rf ~", ""):
                done = subprocess.run([sys.executable, str(ACTIONS_PATH), "forget", argument], env=dict(os.environ, HOME=home),
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 2, argument)
            done = subprocess.run([sys.executable, str(ACTIONS_PATH)], env=dict(os.environ, HOME=home),
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 2)
            self.assertIn("usage", done.stderr)

    def test_the_cli_runs_as_a_plain_script_without_a_toolkit(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, ".config/inkscape").mkdir(parents=True)
            Path(home, ".config/inkscape/preferences.xml").write_text("<x/>")
            Path(home, ".config/other").mkdir()
            done = subprocess.run([sys.executable, "-X", "importtime", str(ACTIONS_PATH), "forget", "inkscape"],
                                  env=dict(os.environ, HOME=home), capture_output=True, text=True, cwd=home)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            imported = {line.split("|")[-1].strip() for line in done.stderr.splitlines()
                        if line.startswith("import time:")}
            self.assertFalse({m for m in imported if m == "gi" or m.startswith("gi.")}, "the helper must not load GTK")
            self.assertFalse(Path(home, ".config/inkscape").exists())
            self.assertTrue(Path(home, ".config/other").exists())
            again = subprocess.run([sys.executable, str(ACTIONS_PATH), "forget", "inkscape"], env=dict(os.environ, HOME=home),
                                   capture_output=True, text=True)
            self.assertEqual(again.returncode, 0)
            self.assertIn("No Inkscape data found", again.stdout)


class Scripts(unittest.TestCase):
    """The install and remove scripts, run for real against fake sudo / flatpak on a temp PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.log = self.dir / "calls.log"
        fake = ('#!/bin/sh\necho "%s $*" >> "$FAKE_LOG"\n'
                '[ "%s" = flatpak ] && [ "$1" = remote-add ] && [ -n "$FAKE_NO_REMOTE" ] && exit 1\n'
                'for bad in $FAKE_FAIL; do for a in "$@"; do [ "$a" = "$bad" ] && exit 1; done; done\nexit 0\n')
        for name in ("sudo", "flatpak"):
            path = self.bin / name
            path.write_text(fake % (name, name))
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.home = self.dir / "home"
        self.home.mkdir()

    def run_argv(self, argv, fail="", no_remote=False, script_fix=None):
        self.assertEqual(argv[:4], [actions.VOID_BIN, "-e", "/bin/sh", "-c"])
        script = argv[4] if script_fix is None else script_fix(argv[4])
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_LOG=str(self.log), FAKE_FAIL=fail,
                   HOME=str(self.home))
        if no_remote:
            env["FAKE_NO_REMOTE"] = "1"
        done = subprocess.run(["/bin/sh", "-c", script, *argv[5:]], input="\n", env=env, capture_output=True,
                              text=True, timeout=60)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return done, calls

    def pack_argv(self, *ids, cfg="", marker=""):
        return actions.install_argv([catalog.get(i) for i in ids], cfg, marker)

    def test_install_argv_layout_and_no_names_in_the_script_text(self):
        entries = [catalog.get(i) for i in ("libreoffice", "anki", "wine", "steam")]
        argv = actions.install_argv(entries)
        pacman, flatpak = catalog.packages_of(entries)
        self.assertEqual(argv[5], "darkos-store")
        self.assertEqual(argv[8], str(len(pacman)))
        self.assertEqual(argv[9:], [*pacman, *flatpak])
        for name in (*pacman, *flatpak):
            self.assertNotIn(name, argv[4], "names travel as arguments, never inside the script text")

    def test_install_rejects_nothing_and_unsafe_names(self):
        with self.assertRaises(ValueError):
            actions.install_argv([])
        evil = catalog.Entry("evil", "Evil", "Bad.", "games", "pacman", ("good; rm -rf ~",))
        with self.assertRaises(ValueError):
            actions.install_argv([evil])
        evil_id = catalog.Entry("Evil Id", "Evil", "Bad.", "games", "pacman", ("good",))
        with self.assertRaises(ValueError):
            actions.install_argv([evil_id])
        two = catalog.Entry("two", "Two", "Bad.", "games", "flatpak", ("a.b.C", "d.e.F"))
        with self.assertRaises(ValueError):
            actions.install_argv([two])

    def test_install_runs_every_package_through_the_gate_then_flathub(self):
        done, calls = self.run_argv(self.pack_argv("thunderbird", "anki"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        gate = actions.GATE_BIN
        self.assertEqual(calls, [
            f"sudo python3 {gate} -- thunderbird",
            f"flatpak remote-add --user --if-not-exists flathub {catalog.FLATHUB_URL}",
            "flatpak install --user --noninteractive -y flathub net.ankiweb.Anki",
        ])
        self.assertIn("Everything you picked is installed", done.stdout)

    def test_install_with_only_pacman_never_touches_flatpak(self):
        done, calls = self.run_argv(self.pack_argv("gimp"))
        self.assertEqual(done.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("sudo python3 "))

    def test_one_failure_is_reported_and_does_not_stop_the_rest_or_write_the_marker(self):
        cfg = self.dir / "config"
        marker = cfg / "extras.done"
        done, calls = self.run_argv(self.pack_argv("gimp", "krita", cfg=str(cfg), marker=str(marker)), fail="gimp")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(calls), 2, "krita was still tried after gimp failed")
        self.assertIn("These did not install: gimp", done.stdout)
        self.assertFalse(marker.exists())

    def test_the_marker_is_written_only_when_everything_installed(self):
        cfg = self.dir / "config"
        marker = cfg / "extras.done"
        done, _ = self.run_argv(self.pack_argv("gimp", "anki", cfg=str(cfg), marker=str(marker)))
        self.assertEqual(done.returncode, 0)
        self.assertTrue(marker.exists())
        marker.unlink()
        done, _ = self.run_argv(self.pack_argv("anki", cfg=str(cfg), marker=str(marker)), fail="net.ankiweb.Anki")
        self.assertEqual(done.returncode, 1)
        self.assertFalse(marker.exists())
        done, _ = self.run_argv(self.pack_argv("gimp"))     # no marker requested: none written
        self.assertEqual(done.returncode, 0)

    def test_if_flathub_cannot_be_added_no_flatpak_is_attempted(self):
        done, calls = self.run_argv(self.pack_argv("anki", "zotero"), no_remote=True)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("flathub", done.stdout)

    def test_remove_pacman_passes_only_installed_packages(self):
        wine = catalog.get("wine")
        argv = actions.remove_argv(wine, installed_packages={"wine", "winetricks", "git"}, forget_data=False)
        self.assertEqual(argv[5:], ["darkos-store", "0", "wine", "wine", "winetricks"])
        with self.assertRaises(ValueError):
            actions.remove_argv(wine, installed_packages={"git"})

    def test_remove_keeps_the_data_unless_asked_and_only_after_pacman_succeeds(self):
        steam = catalog.get("steam")
        data = self.home / ".local/share/Steam"
        data.mkdir(parents=True)
        (data / "game.bin").write_text("saves")
        fix = lambda text: text.replace(actions.SELF_PATH, str(ACTIONS_PATH))
        # keep the data
        done, calls = self.run_argv(actions.remove_argv(steam, {"steam"}, forget_data=False), script_fix=fix)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(calls, ["sudo pacman -Rns -- steam"])
        self.assertTrue((data / "game.bin").exists())
        # pacman refuses: the data must survive even though deletion was requested
        done, _ = self.run_argv(actions.remove_argv(steam, {"steam"}, forget_data=True), fail="steam", script_fix=fix)
        self.assertEqual(done.returncode, 1)
        self.assertTrue((data / "game.bin").exists())
        self.assertIn("Not removed", done.stdout)
        # pacman succeeds and deletion was requested
        done, _ = self.run_argv(actions.remove_argv(steam, {"steam"}, forget_data=True), script_fix=fix)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(data.exists())
        self.assertIn("Deleted", done.stdout)

    def test_remove_flatpak_with_and_without_its_data(self):
        anki = catalog.get("anki")
        argv = actions.remove_argv(anki, forget_data=True)
        self.assertEqual(argv[5:], ["darkos-store", "1", "net.ankiweb.Anki"])
        done, calls = self.run_argv(argv)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(calls, ["flatpak uninstall --user --noninteractive -y --delete-data -- net.ankiweb.Anki"])
        self.log.unlink()
        done, calls = self.run_argv(actions.remove_argv(anki, forget_data=False))
        self.assertEqual(calls, ["flatpak uninstall --user --noninteractive -y -- net.ankiweb.Anki"])


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
