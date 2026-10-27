#!/usr/bin/env python3
"""The Void (darkos-terminal.py): theme and tab regressions.

    xvfb-run -a dbus-run-session -- python ci/test-void.py

Behaviour of the shell inside it (spawning, --cwd, -e) is covered by
test-native-apps-linux.py; this file pins what the redesign fixed.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk

    GTK_AVAILABLE = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK_AVAILABLE = False


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


if __name__ == "__main__":
    unittest.main(verbosity=1)
