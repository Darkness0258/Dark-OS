#!/usr/bin/env python3
"""The Void (darkos-terminal.py): theme/tab regressions, and v2.

    python ci/test-void.py                                # darkos_void only (no display needed)
    xvfb-run -a dbus-run-session -- python ci/test-void.py # everything, incl. GTK/VTE

v2 added split panes, scrollback search, the engagement workspace, the
BlackArch tool launcher, clickable links and the command palette. Its
logic lives in the GTK-free darkos_void package (unit-tested below with
no display needed); the GTK-gated classes further down drive the real
widgets — real VTE, real spawned shells — under xvfb to prove the two
actually wired up correctly together.

Behaviour of the shell inside it (spawning, --cwd, -e) is covered by
test-native-apps-linux.py; this file pins what the redesign fixed.
"""
import importlib.util
import os
import re
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

from darkos_void import catalogue  # noqa: E402
from darkos_void import commands as void_commands  # noqa: E402
from darkos_void import engagement as engagement_mod  # noqa: E402
from darkos_void import linkify, session_log  # noqa: E402

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk

    GTK_AVAILABLE = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK_AVAILABLE = False


# ---------------------------------------------------------------------------
# darkos_void: pure-Python logic, no display required for any of this.
# ---------------------------------------------------------------------------

class EngagementModuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "engagements"

    def test_create_makes_the_four_subfolders_and_engagement_json(self):
        eng = engagement_mod.create_engagement("Acme Corp Pentest", "203.0.113.10", root=self.root)
        for sub in engagement_mod.SUBDIRS:
            self.assertTrue((eng.dir / sub).is_dir(), sub)
        self.assertTrue(eng.json_path.is_file())

    def test_env_carries_target_and_engagement_dir(self):
        eng = engagement_mod.create_engagement("Acme Corp Pentest", "203.0.113.10", root=self.root)
        self.assertEqual(eng.env(), {"ENGAGEMENT_DIR": str(eng.dir), "TARGET": "203.0.113.10"})

    def test_env_omits_target_when_none_was_given(self):
        eng = engagement_mod.create_engagement("No Target Yet", root=self.root)
        self.assertNotIn("TARGET", eng.env())

    def test_load_round_trips_what_create_wrote(self):
        eng = engagement_mod.create_engagement("Acme Corp Pentest", "203.0.113.10", root=self.root)
        loaded = engagement_mod.load_engagement(eng.dir)
        self.assertEqual(loaded.name, eng.name)
        self.assertEqual(loaded.target, eng.target)

    def test_list_engagements_is_newest_first(self):
        engagement_mod.create_engagement("First", root=self.root)
        second = engagement_mod.create_engagement("Second", root=self.root)
        names = [e.name for e in engagement_mod.list_engagements(self.root)]
        self.assertEqual(names[0], second.name)

    def test_update_target_persists(self):
        eng = engagement_mod.create_engagement("Acme Corp Pentest", root=self.root)
        engagement_mod.update_target(eng, "198.51.100.7")
        self.assertEqual(engagement_mod.load_engagement(eng.dir).target, "198.51.100.7")

    def test_empty_name_is_rejected(self):
        with self.assertRaises(engagement_mod.EngagementError):
            engagement_mod.create_engagement("   ", root=self.root)

    def test_duplicate_name_is_rejected_rather_than_overwritten(self):
        engagement_mod.create_engagement("Acme Corp Pentest", "1.2.3.4", root=self.root)
        with self.assertRaises(engagement_mod.EngagementError):
            engagement_mod.create_engagement("Acme Corp Pentest", "9.9.9.9", root=self.root)

    def test_slugify_blocks_path_traversal(self):
        eng = engagement_mod.create_engagement("../../etc", root=self.root)
        self.assertIn(self.root, eng.dir.parents)
        self.assertNotIn("..", eng.dir.name)


class CatalogueModuleTests(unittest.TestCase):
    def test_every_blackarch_group_from_the_spec_is_covered(self):
        for group in ("scanner", "webapp", "cracker", "exploitation", "sniffer",
                      "proxy", "forensic", "wireless", "recon"):
            self.assertTrue(catalogue.tools_for_group(group), group)

    def test_target_is_substituted_when_given(self):
        nmap = next(t for t in catalogue.tools_for_group("scanner") if t.name == "nmap")
        self.assertEqual(catalogue.expand_command(nmap.template, "203.0.113.10"),
                          "nmap -sV -Pn 203.0.113.10")

    def test_target_placeholder_survives_when_none_is_set(self):
        nmap = next(t for t in catalogue.tools_for_group("scanner") if t.name == "nmap")
        self.assertIn("$TARGET", catalogue.expand_command(nmap.template, None))

    def test_search_finds_sqlmap_by_name(self):
        self.assertTrue(any(t.name == "sqlmap" for t in catalogue.search("sql")))

    def test_every_template_is_shell_tokenisable(self):
        """Every template must survive expand_argv with and without a
        target — a typo (unbalanced quote, etc.) would raise here."""
        for tool in catalogue.all_tools():
            catalogue.expand_argv(tool.template, "203.0.113.10")
            catalogue.expand_argv(tool.template, None)

    def test_installed_packages_degrades_to_none_without_pacman(self):
        missing = catalogue.installed_packages(run=lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        self.assertIsNone(missing)

    def test_is_installed_reads_the_pacman_snapshot(self):
        nmap = next(t for t in catalogue.tools_for_group("scanner") if t.name == "nmap")
        self.assertTrue(catalogue.is_installed(nmap, {"nmap", "vte3"}))
        self.assertFalse(catalogue.is_installed(nmap, {"vte3"}))


class LinkifyModuleTests(unittest.TestCase):
    def test_classifies_url_ip_cidr_hash_and_cve_in_one_line(self):
        text = ("scan https://example.com/report now, host 203.0.113.10/24 "
                "and 198.51.100.5, hash 5d41402abc4b2a76b9719d911017c592 "
                "and CVE-2021-44228 found")
        kinds = [m.kind for m in linkify.classify(text)]
        self.assertEqual(kinds, ["url", "ipv4_cidr", "ipv4", "md5", "cve"])

    def test_a_hash_looking_run_inside_a_url_is_reported_once_as_the_url(self):
        text = "https://example.com/5d41402abc4b2a76b9719d911017c592"
        kinds = [m.kind for m in linkify.classify(text)]
        self.assertEqual(kinds, ["url"])

    def test_cve_id_is_matched_case_insensitively(self):
        kinds = [m.kind for m in linkify.classify("see cve-2024-1234 please")]
        self.assertEqual(kinds, ["cve"])

    def test_sha256_is_distinguished_from_sha1_and_md5_by_length(self):
        text = "a" * 64 + " " + "b" * 40 + " " + "c" * 32
        kinds = [m.kind for m in linkify.classify(text)]
        self.assertEqual(kinds, ["sha256", "sha1", "md5"])

    def test_url_actions_lead_with_open(self):
        self.assertEqual(linkify.actions_for("url")[0][0], "open")

    def test_ip_actions_lead_with_set_target(self):
        self.assertEqual(linkify.actions_for("ipv4")[0][0], "set-target")

    def test_hashes_and_cve_only_offer_copy_never_a_network_lookup(self):
        for kind in ("md5", "sha1", "sha256", "cve"):
            self.assertEqual(linkify.actions_for(kind), (("copy", "Copy"),))


class CommandsModuleTests(unittest.TestCase):
    def test_empty_query_returns_every_command_in_order(self):
        self.assertEqual(void_commands.filter_commands(""), list(void_commands.BASE_COMMANDS))

    def test_split_matches_both_split_commands(self):
        ids = {c.id for c in void_commands.filter_commands("split")}
        self.assertEqual(ids, {"split-right", "split-down"})

    def test_nonsense_query_matches_nothing(self):
        self.assertEqual(void_commands.filter_commands("xyzxyznotacommand"), [])

    def test_title_prefix_match_ranks_above_mid_title_match(self):
        results = void_commands.filter_commands("new")
        self.assertEqual(results[0].id, "new-tab")  # "New Tab" starts with "new"


class SessionLogModuleTests(unittest.TestCase):
    def test_exec_command_ends_in_a_newline_so_it_runs_immediately(self):
        line = session_log.exec_command("/tmp/x/session.log")
        self.assertTrue(line.endswith("\n"))
        self.assertTrue(line.startswith("exec script -qfe "))

    def test_exec_command_shell_quotes_a_path_with_spaces(self):
        line = session_log.exec_command("/tmp/has space/out.log")
        self.assertIn("has space", line)
        self.assertTrue("'" in line or '"' in line)

    def test_wrap_with_script_runs_the_given_argv_under_dash_c(self):
        argv = session_log.wrap_with_script(["nmap", "-sV", "10.0.0.1"], "/tmp/out.log")
        self.assertEqual(argv, ["script", "-qfe", "-c", "nmap -sV 10.0.0.1", "/tmp/out.log"])

    def test_log_dir_prefers_the_engagement_when_given(self):
        self.assertEqual(session_log.default_log_dir("/tmp/eng"), Path("/tmp/eng/logs"))


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class VoidThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_test", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)
        from darkos_shell import palette, tokens

        cls.palette, cls.tokens = palette, tokens

    def test_background_foreground_and_cursor_come_from_the_tokens(self):
        self.assertEqual(self.void.BACKGROUND, self.tokens.SURFACE_BASE)
        self.assertEqual(self.void.FOREGROUND, self.tokens.TEXT)

    def test_there_are_sixteen_ansi_colours(self):
        self.assertEqual(len(self.void.PALETTE), 16)

    def test_every_colour_programs_print_text_in_reads_at_4_5_to_1(self):
        for index, colour in enumerate(self.void.PALETTE):
            if index in (0, 8):  # black / bright black: backgrounds and dim text
                continue
            ratio = self.palette.contrast_ratio(colour, self.void.BACKGROUND)
            self.assertGreaterEqual(ratio, 4.5, f"ANSI {index} {colour} is {ratio:.2f}:1")

    def test_bright_black_used_for_comments_still_reads_at_3_to_1(self):
        ratio = self.palette.contrast_ratio(self.void.PALETTE[8], self.void.BACKGROUND)
        self.assertGreaterEqual(ratio, 3.0, ratio)

    def test_ansi_black_is_distinguishable_from_the_background(self):
        self.assertNotEqual(self.void.PALETTE[0], self.void.BACKGROUND)

    def test_the_mono_font_names_the_nerd_font_family_first(self):
        self.assertTrue(self.tokens.FONT_MONO_PANGO.startswith("JetBrainsMono Nerd Font"))


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class TabLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_tabs", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)

    def test_a_tab_label_never_collapses_to_an_ellipsis(self):
        """Regression: with only a max width the label's minimum was ~1 char,
        so a Gtk.Notebook tab showed just '...'."""
        label = self.void.TabLabel("Shell", lambda *_: None)
        minimum, _natural = label.label.get_preferred_width()
        layout = label.label.create_pango_layout("Shell")
        text_width = layout.get_pixel_size()[0]
        self.assertGreaterEqual(minimum, text_width, "label must be wide enough for a short title")
        self.assertGreaterEqual(label.label.get_width_chars(), 10)


# ---------------------------------------------------------------------------
# v2 features against the real widgets: real VTE, real spawned /bin/bash
# children, under the GTK main loop pumped by hand (no Gtk.Application.run()
# needed — a registered Gtk.Application is enough to own a window).
# ---------------------------------------------------------------------------

def _pump(ms):
    end = GLib.get_monotonic_time() + ms * 1000
    while GLib.get_monotonic_time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.01)


def _wait_for(pane, needle, timeout_ms=5000):
    end = GLib.get_monotonic_time() + timeout_ms * 1000
    while GLib.get_monotonic_time() < end:
        if needle in pane.vte.get_text_format(Vte.Format.TEXT):
            return True
        _pump(100)
    return False


_marker_seq = [0]


def _wait_shell_ready(pane, timeout_ms=8000):
    """Prompt-agnostic readiness check (root's "#" vs. a user's "$"):
    resend a unique sentinel until its own echo shows up, since a single
    feed_run can land before spawn_async has actually attached the child
    to the pty and be silently dropped."""
    _marker_seq[0] += 1
    marker = f"READY_{_marker_seq[0]}_{os.getpid()}"
    end = GLib.get_monotonic_time() + timeout_ms * 1000
    while GLib.get_monotonic_time() < end:
        pane.feed_run(f"echo {marker}")
        _pump(400)
        if marker in pane.vte.get_text_format(Vte.Format.TEXT):
            return True
    return False


if GTK_AVAILABLE:
    from gi.repository import Gio, GLib, Vte

    _SHELL = ["/bin/bash", "--norc", "--noprofile", "-i"]
    _app_id_seq = [0]

    def _new_app_window(void_module, command=None):
        # A counter, not id(object()): a throwaway object is immediately
        # GC-eligible, so two calls can get the same freed-and-reused
        # address and collide on "already exported" when both register().
        _app_id_seq[0] += 1
        # NON_UNIQUE, matching main()'s real flag: without it, Gtk.Application
        # tries to claim single-instance D-Bus ownership of application_id,
        # which is both pointless here and the source of "already exported"/
        # "assertion 'local_error == NULL'" noise across back-to-back tests.
        app = Gtk.Application(
            application_id=f"org.darkos.VoidTest{os.getpid()}x{_app_id_seq[0]}",
            flags=Gio.ApplicationFlags.NON_UNIQUE)
        # GLib-GIO-CRITICAL "g_application_impl_attempt_primary" is known
        # harmless noise from creating several short-lived Gtk.Application
        # instances in one process (every test here does); it doesn't
        # affect app.register()'s success or anything these tests check.
        app.register()
        win = void_module.TerminalWindow(app, command=command or _SHELL)
        win.show_all()
        return win


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class SplitPaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_split", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)

    def setUp(self):
        self.win = _new_app_window(self.void)
        self.addCleanup(self.win.destroy)
        self.tab = self.win.focused_tab()
        self.assertTrue(_wait_shell_ready(self.tab.focused), "initial shell never became ready")

    def _assert_tree_well_formed(self):
        children = self.tab.get_children()
        self.assertEqual(len(children), 1, "TabRoot must have exactly one direct child")

        def walk(widget):
            if isinstance(widget, Gtk.Paned):
                c1, c2 = widget.get_child1(), widget.get_child2()
                self.assertIsNotNone(c1, "Paned missing child1")
                self.assertIsNotNone(c2, "Paned missing child2")
                walk(c1)
                walk(c2)
        walk(children[0])

    def test_two_splits_produce_three_leaves_in_a_well_formed_tree(self):
        self.win.split_focused(Gtk.Orientation.HORIZONTAL)
        _pump(300)
        self.assertEqual(len(self.tab.leaves), 2)
        self.assertTrue(_wait_shell_ready(self.tab.focused))

        self.win.split_focused(Gtk.Orientation.VERTICAL)
        _pump(300)
        self.assertEqual(len(self.tab.leaves), 3)
        self.assertTrue(_wait_shell_ready(self.tab.focused))
        self._assert_tree_well_formed()

    def test_closing_a_middle_pane_merges_its_sibling_up(self):
        self.win.split_focused(Gtk.Orientation.HORIZONTAL)
        _pump(200)
        middle = self.tab.focused
        self.assertTrue(_wait_shell_ready(middle))
        self.win.split_focused(Gtk.Orientation.VERTICAL)
        _pump(200)
        self.assertTrue(_wait_shell_ready(self.tab.focused))

        result = self.tab.close_pane(middle)
        _pump(200)
        self.assertEqual(result, "closed")
        self.assertEqual(len(self.tab.leaves), 2)
        self.assertNotIn(middle, self.tab.leaves)
        self._assert_tree_well_formed()

    def test_closing_the_last_pane_in_a_tab_reports_close_tab(self):
        result = self.tab.close_pane(self.tab.leaves[0])
        self.assertEqual(result, "close-tab")

    def test_closing_a_pane_that_already_lost_its_parent_is_a_no_op(self):
        """Regression: child-exited firing mid window-destroy (VTE
        teardown kills the child, which reports exit while GTK's destroy
        cascade is already unparenting widgets) must not raise."""
        leaf = self.tab.leaves[0]
        parent = leaf.get_parent()
        parent.remove(leaf)
        self.assertIsNone(leaf.get_parent())
        self.assertIsNone(self.tab.close_pane(leaf))  # must not raise


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class EngagementIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_eng", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)

    def setUp(self):
        self.win = _new_app_window(self.void)
        self.addCleanup(self.win.destroy)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_a_new_pane_inherits_target_and_engagement_dir(self):
        eng = engagement_mod.create_engagement("Func Test Co", "203.0.113.55",
                                                root=Path(self._tmp.name))
        self.win.set_engagement(eng)
        tab = self.win.new_tab()
        pane = tab.focused
        self.assertTrue(_wait_shell_ready(pane))
        pane.feed_run("echo TARGET_IS=$TARGET ENGDIR_IS=$ENGAGEMENT_DIR")
        self.assertTrue(_wait_for(pane, "TARGET_IS=203.0.113.55"))
        self.assertIn(f"ENGDIR_IS={eng.dir}", pane.vte.get_text_format(Vte.Format.TEXT))

    def test_clearing_the_engagement_resets_the_window_title(self):
        eng = engagement_mod.create_engagement("Func Test Co", root=Path(self._tmp.name))
        self.win.set_engagement(eng)
        self.assertIn("Func Test Co", self.win.get_title())
        self.win.set_engagement(None)
        self.assertEqual(self.win.get_title(), self.void.WINDOW_TITLE)

    def test_set_target_exports_into_the_focused_pane_and_persists(self):
        eng = engagement_mod.create_engagement("Func Test Co", root=Path(self._tmp.name))
        self.win.set_engagement(eng)
        pane = self.win.focused_pane()
        self.assertTrue(_wait_shell_ready(pane))
        self.win.set_target("198.51.100.42")
        self.assertTrue(_wait_for(pane, "198.51.100.42"))
        self.assertEqual(engagement_mod.load_engagement(eng.dir).target, "198.51.100.42")


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class ToolLauncherIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_tools", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)

    def setUp(self):
        self.win = _new_app_window(self.void)
        self.addCleanup(self.win.destroy)
        self.pane = self.win.focused_pane()
        self.assertTrue(_wait_shell_ready(self.pane))
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _select(self, listbox, predicate):
        for i in range(len(listbox.get_children())):
            row = listbox.get_row_at_index(i)
            if predicate(row):
                listbox.select_row(row)
                return row
        self.fail("no matching row found")

    def test_insert_command_expands_target_and_never_runs_it(self):
        eng = engagement_mod.create_engagement("Func Test Co", "203.0.113.55",
                                                root=Path(self._tmp.name))
        self.win.set_engagement(eng)
        dialog = self.void.ToolLauncherDialog(self.win)
        self.addCleanup(dialog.destroy)
        dialog.target_pane = self.pane
        self._select(dialog._group_list, lambda row: row.group == "scanner")
        _pump(150)
        self._select(dialog._tool_list, lambda row: row.tool.name == "nmap")
        dialog._on_response(dialog, Gtk.ResponseType.OK)
        _pump(200)
        text = self.pane.vte.get_text_format(Vte.Format.TEXT)
        self.assertIn("nmap -sV -Pn 203.0.113.55", text)
        # not executed: the typed command is still the last thing on screen,
        # no new prompt/output line has appeared after it
        self.assertTrue(text.rstrip("\n").endswith("nmap -sV -Pn 203.0.113.55"))

    def test_insert_command_leaves_target_placeholder_visible_with_no_engagement(self):
        dialog = self.void.ToolLauncherDialog(self.win)
        self.addCleanup(dialog.destroy)
        dialog.target_pane = self.pane
        self._select(dialog._group_list, lambda row: row.group == "scanner")
        _pump(150)
        self._select(dialog._tool_list, lambda row: row.tool.name == "nmap")
        dialog._on_response(dialog, Gtk.ResponseType.OK)
        _pump(200)
        self.assertIn("nmap -sV -Pn $TARGET", self.pane.vte.get_text_format(Vte.Format.TEXT))

    def test_install_group_opens_a_new_tab_running_the_group_installer(self):
        """The spawned argv itself — not whether `sudo`/the real installed
        path happen to exist on whatever machine runs this test; those are
        only meaningful on an actual deployed root filesystem."""
        dialog = self.void.ToolLauncherDialog(self.win)
        self.addCleanup(dialog.destroy)
        self._select(dialog._group_list, lambda row: row.group == "scanner")
        captured = {}
        real_new_tab = self.win.new_tab
        self.win.new_tab = lambda **kw: captured.update(kw) or real_new_tab(command=["/bin/true"])
        try:
            dialog._on_response(dialog, 1)  # "Install Group"
        finally:
            self.win.new_tab = real_new_tab
        self.assertEqual(captured.get("command"),
                          ["sudo", "/usr/local/bin/darkos-tool-groups", "install", "blackarch-scanner"])


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class CommandPaletteDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_palette", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)

    def setUp(self):
        self.win = _new_app_window(self.void)
        self.addCleanup(self.win.destroy)
        self.assertTrue(_wait_shell_ready(self.win.focused_pane()))

    def test_split_right_command_actually_splits(self):
        tab = self.win.focused_tab()
        before = len(tab.leaves)
        self.win.run_palette_command("split-right")
        _pump(200)
        self.assertEqual(len(tab.leaves), before + 1)

    def test_zoom_in_and_reset_commands_change_font_size(self):
        pane = self.win.focused_pane()
        start = pane.font_size
        self.win.run_palette_command("zoom-in")
        self.assertEqual(pane.font_size, start + 1)
        self.win.run_palette_command("zoom-reset")
        self.assertEqual(pane.font_size, 11)

    def test_palette_list_matches_the_filter(self):
        dialog = self.void.CommandPaletteDialog(self.win)
        self.addCleanup(dialog.destroy)
        dialog._entry.set_text("zoom")
        dialog._refresh()
        ids = {row.command_id for row in dialog._list.get_children()}
        self.assertEqual(ids, {"zoom-in", "zoom-out", "zoom-reset"})


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class SessionLoggingAndExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_log", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)

    def setUp(self):
        self.win = _new_app_window(self.void)
        self.addCleanup(self.win.destroy)
        self.pane = self.win.focused_pane()
        self.assertTrue(_wait_shell_ready(self.pane))

    def test_start_logging_wraps_the_shell_and_the_log_file_gets_real_output(self):
        self.pane.start_logging()
        _pump(400)
        match = re.search(r"exec script -qfe (\S+)", self.pane.vte.get_text_format(Vte.Format.TEXT))
        self.assertIsNotNone(match, "exec script line was not typed into the pane")
        log_path = match.group(1)
        self.assertTrue(_wait_shell_ready(self.pane), "logged sub-shell never became ready")
        self.pane.feed_run("echo FROM_LOGGED_SHELL")
        self.assertTrue(_wait_for(self.pane, "FROM_LOGGED_SHELL"))
        _pump(800)
        self.assertTrue(os.path.isfile(log_path))
        with open(log_path, "rb") as fh:
            logged = fh.read()
        self.assertIn(b"FROM_LOGGED_SHELL", logged)

    def test_scrollback_write_path_captures_pane_content(self):
        self.pane.feed_run("echo SCROLLBACK_MARKER")
        self.assertTrue(_wait_for(self.pane, "SCROLLBACK_MARKER"))
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "scrollback-out.txt")
            gfile = Gio.File.new_for_path(out_path)
            stream = gfile.replace(None, False, Gio.FileCreateFlags.NONE, None)
            self.pane.vte.write_contents_sync(stream, Vte.WriteFlags.DEFAULT, None)
            stream.close(None)
            with open(out_path, "rb") as fh:
                saved = fh.read()
        self.assertIn(b"SCROLLBACK_MARKER", saved)


@unittest.skipUnless(GTK_AVAILABLE, "GTK/VTE not available")
class LinkifyLiveMatchTests(unittest.TestCase):
    """The regex/tagging side on real rendered content, and the action
    dispatch that a right-click would trigger. The pixel-accurate
    button-press -> match_check_event hop itself needs a real pointer
    device to verify convincingly (a hand-built Gdk.Event under Xvfb came
    back with no match even positioned squarely over live-rendered text,
    most likely an Xvfb/synthetic-event limitation rather than anything
    in match_check_event's own contract — match_check(col, row), which
    shares that contract, DOES find the same matches on the same content
    from the same button-press-event handler's code path); that one hop
    is a manual spot-check item, called out in TESTING-MANUAL.md."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("darkos_terminal_links", BIN / "darkos-terminal.py")
        cls.void = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.void)

    def setUp(self):
        self.win = _new_app_window(self.void)
        self.addCleanup(self.win.destroy)
        self.pane = self.win.focused_pane()
        self.assertTrue(_wait_shell_ready(self.pane))

    def test_matches_resolve_to_the_right_kind_on_live_rendered_text(self):
        self.pane.feed_run(
            "printf 'see https://example.com/x and 203.0.113.9 and CVE-2024-9999\\n'")
        self.assertTrue(_wait_for(self.pane, "CVE-2024-9999"))
        _pump(200)
        found = set()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # match_check() itself is deprecated; fine for a test
            text = self.pane.vte.get_text_format(Vte.Format.TEXT)
            for row in range(min(6, text.count("\n") + 1)):
                for col in range(90):
                    result = self.pane.vte.match_check(col, row)
                    if result and result[0]:
                        found.add(self.pane._match_tags.get(result[1]))
        self.assertTrue({"url", "ipv4", "cve"} & found, found)

    def test_set_target_action_updates_the_engagement(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = engagement_mod.create_engagement("Func Test Co", root=Path(tmp))
            self.win.set_engagement(eng)
            self.pane._run_link_action("set-target", "198.51.100.42")
            self.assertEqual(self.win.engagement.target, "198.51.100.42")


if __name__ == "__main__":
    unittest.main(verbosity=1)
