#!/usr/bin/env python3
"""Design check: the Calm Dark rules from docs/MASTER-PLAN.md section 5, as tests.

Each rule is one assertion, so a colour that drifts, a font size off the type
scale or a glow where only a focus ring belongs fails CI instead of being
noticed on a screenshot.

    python ci/test-design-tokens.py                                  # pure checks
    xvfb-run -a dbus-run-session -- python ci/test-design-tokens.py  # + GTK CSS parse
"""
import importlib.util
import json
import re
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # noqa: F401

    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

if not GTK_AVAILABLE:
    package = types.ModuleType("darkos_shell")
    package.__path__ = [str(BIN / "darkos_shell")]
    sys.modules["darkos_shell"] = package

from darkos_shell import css, palette, tokens  # noqa: E402

DEFAULT_ACCENT = "#00e5ff"
SURFACES = ("bg_base", "bg_raised", "bg_overlay")
TEST_ACCENTS = (
    "#00e5ff", "#ff0000", "#00ff00", "#ffff00", "#0000ff",
    "#a855f7", "#ffffff", "#000000", "#222222", "not a colour", None,
)

# Every token name an app or the shell imported before the redesign. Renaming
# one silently breaks that app, so they stay as aliases.
LEGACY_NAMES = (
    "COLOR_BG", "COLOR_BG_ALT", "COLOR_BG_ELEVATED", "COLOR_TEXT", "COLOR_TEXT_MUTED",
    "COLOR_PRIMARY", "COLOR_SECONDARY", "COLOR_ACCENT", "COLOR_WARNING", "COLOR_DANGER",
    "COLOR_SUCCESS", "COLOR_BORDER", "CAIRO_PRIMARY", "CAIRO_SECONDARY", "CAIRO_ACCENT",
    "CAIRO_TEXT", "CAIRO_MUTED", "CAIRO_DANGER", "SPACE_XS", "SPACE_SM", "SPACE_MD",
    "SPACE_LG", "SPACE_XL", "RADIUS_CONTROL", "RADIUS_PANEL", "RADIUS_DIALOG",
    "FONT_BODY", "FONT_HEADING", "FONT_MONO", "REDUCE_MOTION", "HIGH_CONTRAST",
    "DOCK_POSITIONS", "DOCK_SIZES", "dock_layout", "dock_exclusive_zone",
)


class ContrastMathTests(unittest.TestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(palette.contrast_ratio("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(palette.contrast_ratio("#777777", "#ffffff"), 4.48, places=2)
        self.assertAlmostEqual(palette.contrast_ratio("#123456", "#123456"), 1.0, places=6)

    def test_ratio_is_symmetric(self):
        self.assertEqual(
            palette.contrast_ratio("#00e5ff", "#060a11"),
            palette.contrast_ratio("#060a11", "#00e5ff"),
        )

    def test_short_hex_is_accepted_and_garbage_is_rejected(self):
        self.assertEqual(palette.hex_to_rgb("#fff"), (255, 255, 255))
        for bad in ("#12", "#zzzzzz", "", "rgb(1,2,3)"):
            with self.assertRaises(ValueError):
                palette.hex_to_rgb(bad)

    def test_oklch_round_trip_stays_within_one_step(self):
        for colour in ("#00e5ff", "#a855f7", "#2d7bff", "#22e07a", "#808080"):
            back = palette.hex_to_rgb(palette.oklch_to_hex(*palette.hex_to_oklch(colour)))
            original = palette.hex_to_rgb(colour)
            self.assertTrue(
                all(abs(a - b) <= 1 for a, b in zip(back, original)), (colour, back)
            )

    def test_ensure_contrast_only_moves_what_fails(self):
        self.assertEqual(palette.ensure_contrast("#ffffff", "#000000", 4.5), "#ffffff")
        fixed = palette.ensure_contrast("#0000ff", "#060a11", 4.5)
        self.assertGreaterEqual(palette.contrast_ratio(fixed, "#060a11"), 4.5)


class PaletteRuleTests(unittest.TestCase):
    """Rules 1, 2 and 8: tonal surfaces, one accent, contrast on every surface."""

    def test_default_palette_passes_every_rule(self):
        self.assertEqual(palette.validate(palette.generate_palette(DEFAULT_ACCENT)), [])

    def test_surfaces_are_three_distinct_tones_and_not_pure_black(self):
        p = palette.generate_palette(DEFAULT_ACCENT)
        self.assertEqual(len({p[name] for name in SURFACES}), 3)
        self.assertNotEqual(p["bg_base"], "#000000")

    def test_surface_steps_are_wider_than_the_old_1_09(self):
        p = palette.generate_palette(DEFAULT_ACCENT)
        for lower, upper in (("bg_base", "bg_raised"), ("bg_raised", "bg_overlay")):
            self.assertGreaterEqual(
                palette.contrast_ratio(p[lower], p[upper]), palette.MIN_SURFACE_STEP, (lower, upper)
            )

    def test_text_and_semantic_colours_pass_4_5_on_every_surface(self):
        p = palette.generate_palette(DEFAULT_ACCENT)
        for name in ("text", "text_muted", "accent_text", "success", "warning", "danger"):
            for surface in SURFACES:
                self.assertGreaterEqual(
                    palette.contrast_ratio(p[name], p[surface]), 4.5, (name, surface)
                )

    def test_control_borders_pass_3_to_1_on_every_surface(self):
        p = palette.generate_palette(DEFAULT_ACCENT)
        for surface in SURFACES:
            self.assertGreaterEqual(palette.contrast_ratio(p["border_control"], p[surface]), 3.0)

    def test_label_on_an_accent_button_passes_4_5(self):
        for accent in TEST_ACCENTS:
            p = palette.generate_palette(accent)
            self.assertGreaterEqual(
                palette.contrast_ratio(p["on_accent"], p["accent"]), 4.5, accent
            )

    def test_whatever_accent_the_user_picks_the_palette_still_passes(self):
        for accent in TEST_ACCENTS:
            self.assertEqual(palette.validate(palette.generate_palette(accent)), [], accent)

    def test_an_unparseable_accent_falls_back_to_the_default(self):
        self.assertEqual(palette.generate_palette("not a colour")["accent"], DEFAULT_ACCENT)
        self.assertEqual(palette.generate_palette(None)["accent"], DEFAULT_ACCENT)

    def test_high_contrast_is_opaque_black_and_white_at_7_to_1(self):
        p = palette.generate_palette(DEFAULT_ACCENT, high_contrast=True)
        self.assertEqual({p[name] for name in SURFACES}, {"#000000"})
        self.assertEqual(palette.validate(p, high_contrast=True), [])
        for name in ("text", "accent_text", "success", "warning", "danger"):
            self.assertGreaterEqual(palette.contrast_ratio(p[name], p["bg_base"]), 7.0, name)

    def test_validate_actually_catches_a_bad_palette(self):
        bad = dict(palette.generate_palette(DEFAULT_ACCENT), text_muted="#444444")
        self.assertTrue(any("text_muted" in problem for problem in palette.validate(bad)))
        flat = dict(palette.generate_palette(DEFAULT_ACCENT), bg_raised="#060a11")
        self.assertTrue(any("surface step" in problem for problem in palette.validate(flat)))


class TokenTests(unittest.TestCase):
    def test_type_scale_is_12_14_16_20_28(self):
        self.assertEqual(tokens.TYPE_SCALE, (12, 14, 16, 20, 28))

    def test_spacing_scale_is_4_8_16_32_48(self):
        self.assertEqual(
            (tokens.SPACE_XS, tokens.SPACE_SM, tokens.SPACE_MD, tokens.SPACE_LG, tokens.SPACE_XL),
            (4, 8, 16, 32, 48),
        )

    def test_radii_are_8_16_24(self):
        self.assertEqual((tokens.RADIUS_CONTROL, tokens.RADIUS_DIALOG), (8, 24))
        self.assertIn(tokens.RADIUS_PANEL, range(0, 33))

    def test_one_accent_the_old_blue_and_purple_are_aliases(self):
        self.assertEqual(tokens.COLOR_PRIMARY, tokens.COLOR_SECONDARY)
        self.assertEqual(tokens.COLOR_PRIMARY, tokens.COLOR_ACCENT)
        self.assertEqual(tokens.CAIRO_PRIMARY, tokens.CAIRO_ACCENT)

    def test_every_legacy_token_name_still_exists(self):
        missing = [name for name in LEGACY_NAMES if not hasattr(tokens, name)]
        self.assertEqual(missing, [])

    def test_the_glow_tokens_are_gone(self):
        self.assertFalse([n for n in dir(tokens) if "GLOW" in n.upper()])

    def test_one_ui_font_family(self):
        self.assertNotIn("Space Grotesk", tokens.FONT_HEADING)
        self.assertEqual(tokens.FONT_HEADING, tokens.FONT_BODY)

    def test_mono_font_names_the_nerd_font_family_the_package_installs(self):
        self.assertIn("JetBrainsMono Nerd Font", tokens.FONT_MONO)


class StylesheetTests(unittest.TestCase):
    """Rules 3, 4, 5: flat surfaces, glow only on focus, type from the scale."""

    CSS = css.CSS_STYLE

    @staticmethod
    def rules(text):
        return re.findall(r"([^{}]+)\{([^{}]*)\}", text)

    def test_font_sizes_come_from_the_type_scale(self):
        sizes = {int(size) for size in re.findall(r"font-size:\s*(\d+)px", self.CSS)}
        self.assertTrue(sizes <= set(tokens.TYPE_SCALE), sizes - set(tokens.TYPE_SCALE))

    def test_every_colour_in_the_sheet_is_a_palette_colour(self):
        allowed = {value.lower() for value in tokens.PALETTE.values()}
        used = {value.lower() for value in re.findall(r"#[0-9a-fA-F]{6}\b", self.CSS)}
        self.assertEqual(used - allowed, set())

    def test_no_css_transitions_motion_is_the_compositors_job(self):
        self.assertNotRegex(self.CSS, r"\btransition\b")
        self.assertNotRegex(self.CSS, r"@keyframes|\banimation\b")

    def test_a_zero_offset_glow_ring_belongs_to_keyboard_focus_only(self):
        for selector, body in self.rules(self.CSS):
            if re.search(r"box-shadow:\s*0 0 0 \d+px", body):
                self.assertIn(":focus", selector, selector.strip())

    def test_no_blurred_glow_anywhere(self):
        # `0 0 12px` style glows (non-zero blur around a zero offset) are the
        # old HUD look.
        self.assertNotRegex(self.CSS, r"box-shadow:\s*0 0 [1-9]\d*px")

    def test_floating_surfaces_are_the_only_ones_with_drop_shadows(self):
        allowed = (".command-center", ".dock-bar")
        for selector, body in self.rules(self.CSS):
            if re.search(r"box-shadow:\s*0 \d+px \d+px", body):
                self.assertTrue(any(name in selector for name in allowed), selector.strip())

    def test_no_old_hud_classes(self):
        for name in ("hud-stage", "hud-wordmark", "dock-highlight", "dock-clock", ".rail"):
            self.assertNotIn(name, self.CSS)

    def test_stock_gradients_are_reset_on_buttons(self):
        for needle in (".action-button", ".icon-button", ".toggle-button"):
            self.assertIn(needle, self.CSS)
        self.assertIn("background-image: none", self.CSS)

    @unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
    def test_gtk_parses_the_whole_sheet_without_dropping_a_rule(self):
        self.assertEqual(css.css_parse_errors(css.CSS_STYLE), [])

    @unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
    def test_gtk_parses_the_high_contrast_sheet_too(self):
        hc = palette.generate_palette(DEFAULT_ACCENT, high_contrast=True)
        self.assertEqual(css.css_parse_errors(css.build_css(hc, high_contrast=True)), [])

    @unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
    def test_the_sheet_builds_for_any_accent(self):
        for accent in TEST_ACCENTS:
            sheet = css.build_css(palette.generate_palette(accent), high_contrast=False)
            self.assertEqual(css.css_parse_errors(sheet), [], accent)


class ThemeFileTests(unittest.TestCase):
    """The static files (Waybar, mako, login, lock screen, installer) are
    generated from the palette; they must not drift from it."""

    def test_generated_theme_files_are_in_sync_with_the_palette(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/gen-theme.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_waybar_has_no_stubs_and_no_per_second_wakeups(self):
        config = json.loads((ROOT / "airootfs/etc/xdg/waybar/config").read_text(encoding="utf-8"))
        modules = config["modules-left"] + config["modules-center"] + config["modules-right"]
        for dead in ("custom/logo", "custom/avatar", "backlight"):
            self.assertNotIn(dead, modules)
        self.assertGreaterEqual(config["clock"]["interval"], 30)
        self.assertIn("--toggle-control", config["custom/control"]["on-click"])

    def test_the_power_button_never_powers_off_without_a_menu(self):
        config = json.loads((ROOT / "airootfs/etc/xdg/waybar/config").read_text(encoding="utf-8"))
        self.assertNotIn("poweroff", config["custom/power"]["on-click"])

    def test_hyprland_animations_stay_inside_the_motion_budget(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text(encoding="utf-8")
        speeds = {
            name: float(speed)
            for name, speed in re.findall(r"^\s*animation = (\w+), 1, ([\d.]+)", conf, flags=re.M)
        }
        self.assertTrue(speeds)
        for name, speed in speeds.items():
            self.assertLessEqual(speed, 2.5, f"{name} animates for {speed * 100:.0f} ms")

    def test_app_windows_are_solid_and_the_focus_border_is_the_accent(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^windowrule = opacity .*darkos-", conf, flags=re.M))
        match = re.search(r"col\.active_border = rgba\(([0-9a-f]{6})[0-9a-f]{2}\)$", conf, flags=re.M)
        self.assertIsNotNone(match, "active border must be one plain accent colour")
        self.assertEqual("#" + match.group(1), tokens.PALETTE["accent"] if not tokens.HIGH_CONTRAST else DEFAULT_ACCENT)

    def test_no_config_still_names_a_removed_surface(self):
        for relative in ("airootfs/etc/xdg/hypr/hyprland.conf", "ci/hardware-audit.sh", "ci/verify-iso.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"darkos-(rail|left|right|hud)\b", relative)

    def test_mako_keeps_enough_history_for_the_command_center(self):
        text = (ROOT / "airootfs/etc/xdg/mako/config").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^max-history=\d+$")


class ShellSourceRuleTests(unittest.TestCase):
    """Rule 7: no HUD, rings, orbs, fake metrics, stubs or second clock."""

    SOURCES = {
        path.name: path.read_text(encoding="utf-8")
        for path in (BIN / "darkos_shell").glob("*.py")
    }

    def test_removed_surfaces_stay_removed(self):
        for name, text in self.SOURCES.items():
            for legacy in ("RingGauge", "DarkOSIconRail", "DarkOSLeftPanels", "DarkOSRightPanels",
                           "stroke_glow", "GLOW_STROKES"):
                self.assertNotIn(legacy, text, f"{name} still has {legacy}")

    def test_the_dock_has_no_clock_of_its_own(self):
        self.assertNotIn("clock_label", self.SOURCES["surfaces.py"])

    def test_no_weather_stub_in_the_command_center(self):
        self.assertIsNone(re.search(r"(?i)weather", self.SOURCES["surfaces.py"]))

    def test_no_not_connected_placeholder_text(self):
        self.assertIsNone(re.search(r"(?i)not connected", self.SOURCES["surfaces.py"]))

    def test_the_fake_dark_mode_toggle_is_gone(self):
        self.assertNotIn("dark_mode", self.SOURCES["__init__.py"])
        self.assertNotIn("dark_mode", self.SOURCES["surfaces.py"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
