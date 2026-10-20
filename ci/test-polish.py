#!/usr/bin/env python3
"""Tests for the performance profile, Night Light/Focus, PiP, annotated
screenshots, screen reader, update parsing, and the AI/wallpaper removal.
No compositor needed; external tools are faked."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, BIN / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fx = load("darkos_window_fx", "darkos-window-fx.py")


class PerfApplyTests(unittest.TestCase):
    def run_script(self, settings_json, *args):
        with tempfile.TemporaryDirectory() as home:
            if settings_json is not None:
                cfg = Path(home, ".config/darkos")
                cfg.mkdir(parents=True)
                (cfg / "settings.json").write_text(settings_json)
            env = {**os.environ, "HOME": home, "XDG_CONFIG_HOME": f"{home}/.config"}
            result = subprocess.run(
                ["bash", str(BIN / "darkos-perf-apply"), "--no-reload", *args],
                env=env, capture_output=True, text=True, timeout=20,
            )
            conf = Path(home, ".config/hypr/conf.d/perf-auto.conf")
            return result, conf.read_text() if conf.exists() else None

    def test_lite_disables_effects_and_transparency(self):
        result, conf = self.run_script('{"effects": "lite"}')
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in ("decoration:blur:enabled = false", "decoration:shadow:enabled = false",
                     "animations:enabled = false", "decoration:rounding = 0",
                     "windowrule = opacity 1.0 1.0"):
            self.assertIn(line, conf)

    def test_full_writes_no_overrides(self):
        result, conf = self.run_script('{\n  "effects": "full"\n}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("blur:enabled", conf)
        self.assertNotIn("windowrule", conf)

    def test_garbage_value_falls_back_to_a_valid_profile(self):
        result, conf = self.run_script('{"effects": "turbo"}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("profile=", result.stdout)
        self.assertIsNotNone(conf)

    def test_missing_settings_file_is_fine(self):
        result, conf = self.run_script(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(conf)


class SettingsSchemaTests(unittest.TestCase):
    def test_choices_validate_effects_and_renderer(self):
        from darkos_shell import user_settings as us
        self.assertEqual(us.DEFAULTS["effects"], "auto")
        self.assertEqual(us.DEFAULTS["renderer"], "auto")
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "settings.json")
            path.write_text('{"effects": "x", "renderer": "hardware"}')
            original = us.settings_path
            us.settings_path = lambda: str(path)  # GLib caches the config dir
            try:
                data = us.load_settings()
                self.assertEqual(data["effects"], "auto")      # bad value -> default
                self.assertEqual(data["renderer"], "hardware")  # valid value kept
                data["effects"] = "lite"
                self.assertTrue(us.save_settings(data))
                saved = path.read_text()
            finally:
                us.settings_path = original
        # perf-apply / start-hyprland read this file with grep, so the exact
        # json.dump(indent=2) shape matters.
        self.assertRegex(saved, r'"effects": "lite"')
        self.assertRegex(saved, r'"renderer": "hardware"')


class PipTests(unittest.TestCase):
    MON = {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1.0, "focused": True}

    def test_rect_is_16_9_bottom_right(self):
        box = fx.pip_rect(self.MON)
        self.assertEqual((box["w"], box["h"]), (480, 270))
        self.assertEqual((box["x"], box["y"]), (1920 - 480 - 24, 1080 - 270 - 24))

    def test_rect_shrinks_on_small_screen_and_respects_offset(self):
        box = fx.pip_rect({"x": 1920, "y": 0, "width": 400, "height": 300, "scale": 1.0})
        self.assertEqual(box["w"], 352)
        self.assertGreaterEqual(box["x"], 1920)

    def test_enable_floats_resizes_moves_pins(self):
        calls = []
        rc = fx.run_pip(active={"address": "0xabc", "floating": False, "pinned": False},
                        monitors=[self.MON], dispatch=lambda *a: calls.append(a))
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], ("togglefloating", "address:0xabc"))
        self.assertEqual(calls[1], ("resizewindowpixel", "exact", "480", "270,address:0xabc"))
        self.assertEqual(calls[2], ("movewindowpixel", "exact", "1416", "786,address:0xabc"))
        self.assertEqual(calls[3], ("pin", "address:0xabc"))

    def test_already_floating_window_is_not_toggled(self):
        calls = []
        fx.run_pip(active={"address": "0x1", "floating": True, "pinned": False},
                   monitors=[self.MON], dispatch=lambda *a: calls.append(a))
        self.assertNotIn(("togglefloating", "address:0x1"), calls)

    def test_toggle_off_unpins_and_tiles_again(self):
        calls = []
        fx.run_pip(active={"address": "0x1", "floating": True, "pinned": True},
                   monitors=[self.MON], dispatch=lambda *a: calls.append(a))
        self.assertEqual(calls, [("pin", "address:0x1"), ("togglefloating", "address:0x1")])

    def test_no_active_window_fails_cleanly(self):
        fx._notify = Mock()
        self.assertEqual(fx.run_pip(active={}, monitors=[], dispatch=Mock()), 1)


class SnipAnnotateTests(unittest.TestCase):
    def fake_run(self, log):
        def run(argv, **_kw):
            log.append(argv)
            out = "10,20 300x200\n" if argv[0] == "slurp" else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        return run

    def test_annotate_runs_swappy_on_the_saved_file_before_copy(self):
        log, order = [], []
        with tempfile.TemporaryDirectory() as home:
            fx.run_snip(True, pick_settle=0, home=home, run=self.fake_run(log), sleep=lambda _s: None,
                        notify=Mock(), copy=lambda p: order.append("copy") or True, annotate=True)
        names = [a[0] for a in log]
        self.assertEqual(names, ["slurp", "grim", "swappy"])
        swappy = log[2]
        self.assertEqual(swappy[1], "-f")
        self.assertEqual(swappy[2], swappy[4])  # edited in place (-o same path)
        self.assertEqual(order, ["copy"])

    def test_plain_snip_never_starts_swappy(self):
        log = []
        with tempfile.TemporaryDirectory() as home:
            fx.run_snip(True, pick_settle=0, home=home, run=self.fake_run(log), sleep=lambda _s: None,
                        notify=Mock(), copy=lambda p: True)
        self.assertNotIn("swappy", [a[0] for a in log])


class ScreenReaderTests(unittest.TestCase):
    def test_missing_orca_reports_unavailable(self):
        fx._notify = Mock()
        self.assertEqual(fx.run_screen_reader("on", which=lambda _n: None, run=Mock()), 1)

    def test_on_starts_orca_once(self):
        popen = Mock()
        run = Mock(return_value=subprocess.CompletedProcess([], 1))  # pgrep: not running
        self.assertEqual(fx.run_screen_reader("on", run=run, popen=popen, which=lambda _n: "/usr/bin/orca"), 0)
        popen.assert_called_once()
        popen.reset_mock()
        run.return_value = subprocess.CompletedProcess([], 0)  # already running
        fx.run_screen_reader("on", run=run, popen=popen, which=lambda _n: "/usr/bin/orca")
        popen.assert_not_called()

    def test_off_quits_only_when_running(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        fx.run_screen_reader("off", run=run, popen=Mock(), which=lambda _n: "/usr/bin/orca")
        self.assertEqual(run.call_args_list[-1].args[0], ["orca", "--quit"])

    def test_a11y_apply_starts_reader_only_when_enabled(self):
        reader = Mock()
        fx.apply_zoom = Mock(return_value=0)
        fx.run_a11y_apply({"a11y_speech": True}, screen_reader=reader)
        reader.assert_called_once_with("on")
        reader.reset_mock()
        fx.run_a11y_apply({"a11y_speech": False}, screen_reader=reader)
        reader.assert_not_called()


class NightLightFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from darkos_shell import _night_light_apply, _focus_apply
        cls.night, cls.focus = staticmethod(_night_light_apply), staticmethod(_focus_apply)

    def test_night_light_missing_tool_is_an_error(self):
        msg, failed = self.night(True, which=lambda _n: None, run=Mock(), popen=Mock())
        self.assertTrue(failed)
        self.assertIn("hyprsunset", msg)

    def test_night_light_on_restarts_cleanly_and_off_only_kills(self):
        run, popen = Mock(), Mock()
        _msg, failed = self.night(True, which=lambda _n: "/x", run=run, popen=popen)
        self.assertFalse(failed)
        self.assertEqual(popen.call_args.args[0][:2], ["hyprsunset", "-t"])
        run.assert_called_with(["pkill", "-x", "hyprsunset"], capture_output=True)
        popen.reset_mock()
        self.night(False, which=lambda _n: "/x", run=run, popen=popen)
        popen.assert_not_called()

    def test_focus_uses_mako_modes(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        _m, failed = self.focus(True, which=lambda _n: "/x", run=run)
        self.assertFalse(failed)
        self.assertEqual(run.call_args.args[0], ["makoctl", "mode", "-s", "do-not-disturb"])
        self.focus(False, which=lambda _n: "/x", run=run)
        self.assertEqual(run.call_args.args[0], ["makoctl", "mode", "-s", "default"])

    def test_focus_reports_unreachable_mako(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1, "", "boom"))
        _m, failed = self.focus(True, which=lambda _n: "/x", run=run)
        self.assertTrue(failed)


class UpdateParsingTests(unittest.TestCase):
    def test_parse_checkupdates(self):
        spec = importlib.util.spec_from_file_location(
            "settings_mod", BIN / "darkos-settings.py")
        text = (BIN / "darkos-settings.py").read_text()
        start = text.index("def parse_checkupdates")
        end = text.index("@dataclass(frozen=True)\nclass PowerProfileState")
        ns = {}
        exec(text[start:end], ns)  # the function is pure; avoid building the GTK app
        parse = ns["parse_checkupdates"]
        self.assertEqual(parse("linux 6.1-1 -> 6.2-1\nfoo 1 -> 2\nnoise\n"),
                         [("linux", "6.1-1", "6.2-1"), ("foo", "1", "2")])
        self.assertEqual(parse(""), [])
        self.assertEqual(parse(None), [])
        del spec


class WallpaperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from darkos_shell import wallpapers
        cls.w = wallpapers
        cls.bg = ROOT / "airootfs/usr/share/backgrounds/darkos"

    def test_catalog_has_nine_real_images_with_thumbnails(self):
        from PIL import Image
        entries = self.w.catalog(str(self.bg))
        self.assertEqual(len(entries), 9)
        self.assertEqual(len({e["id"] for e in entries}), 9)
        for e in entries:
            with Image.open(e["path"]) as im:
                self.assertEqual(im.format, "JPEG", e["path"])
                self.assertGreaterEqual(im.size[0], 1920, e["path"])
            with Image.open(e["thumb"]) as th:
                self.assertLessEqual(th.size[0], 320, e["thumb"])
        files = {p.name for p in self.bg.glob("*.jpg")}
        self.assertEqual(files, {Path(e["path"]).name for e in entries},
                         "every shipped jpg must be in the catalogue (and vice versa)")

    def test_default_exists_and_is_used_by_greeter_and_lock_screen(self):
        default = Path(self.w.default_path(str(self.bg)))
        self.assertTrue(default.is_file())
        shipped = "/usr/share/backgrounds/darkos/" + self.w.DEFAULT_FILE
        self.assertIn(shipped, (ROOT / "airootfs/etc/greetd/regreet.toml").read_text())
        self.assertIn(shipped, (ROOT / "airootfs/etc/xdg/hypr/hyprlock.conf").read_text())
        self.assertIn("swaybg", (ROOT / "packages.x86_64").read_text().split())

    def test_resolve_prefers_valid_choice_then_default_then_none(self):
        d = str(self.bg)
        pick = str(self.bg / "05-amber-flow.jpg")
        self.assertEqual(self.w.resolve(pick, d), pick)
        default = self.w.default_path(d)
        for bad in ("", None, "relative/x.jpg", "/nonexistent/x.jpg", "/etc/passwd",
                    str(self.bg / "thumbs")):
            self.assertEqual(self.w.resolve(bad, d), default, repr(bad))
        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(self.w.resolve("", empty))

    def test_apply_starts_new_swaybg_before_stopping_old(self):
        events = []
        run = lambda argv, **_k: subprocess.CompletedProcess(argv, 0, "111 222\n", "")
        popen = lambda argv, **_k: events.append(("start", argv))
        kill = lambda pid, sig: events.append(("kill", pid))
        pick = str(self.bg / "03-green-glass.jpg")
        started, resolved = self.w.apply(pick, str(self.bg), run=run, popen=popen,
                                         sleep=lambda _s: events.append(("wait",)),
                                         which=lambda _n: "/usr/bin/swaybg", kill=kill)
        self.assertTrue(started)
        self.assertEqual(resolved, pick)
        self.assertEqual([e[0] for e in events], ["start", "wait", "kill", "kill"])
        self.assertEqual(events[0][1][:3], ["swaybg", "-i", pick])
        self.assertIn("fill", events[0][1])
        self.assertEqual([e[1] for e in events if e[0] == "kill"], [111, 222])

    def test_apply_without_image_uses_plain_colour_and_without_swaybg_reports_it(self):
        events = []
        with tempfile.TemporaryDirectory() as empty:
            started, resolved = self.w.apply("", empty,
                run=lambda a, **_k: subprocess.CompletedProcess(a, 1, "", ""),
                popen=lambda a, **_k: events.append(a), sleep=lambda _s: None,
                which=lambda _n: "/usr/bin/swaybg")
        self.assertEqual((started, resolved), (True, None))
        self.assertEqual(events[0], ["swaybg", "-c", self.w.FALLBACK_COLOR])
        self.assertEqual(self.w.apply("", which=lambda _n: None), (False, None))

    def test_window_fx_commands(self):
        calls = []
        fx._notify = Mock()
        rc = fx.run_wallpaper_apply({"wallpaper_path": "/x.jpg"},
                                    apply=lambda p: calls.append(p) or (True, None))
        self.assertEqual((rc, calls), (0, ["/x.jpg"]))
        self.assertEqual(fx.run_wallpaper_apply({}, apply=lambda p: (False, None)), 1)
        self.assertEqual(fx.run_wallpaper_apply({"wallpaper_path": ""},
                                                apply=lambda p: calls.append(p) or (True, None)), 0)
        self.assertEqual(calls[-1], "")

    def test_fallback_colour_matches_hyprland_background(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text()
        self.assertIn("background_color = rgb(%s)" % self.w.FALLBACK_COLOR.lstrip("#"), conf)


class RemovalTests(unittest.TestCase):
    """The AI assistant and the old generated wallpaper are gone and must stay gone."""

    def test_ai_and_wallpaper_files_removed(self):
        for rel in ("airootfs/usr/local/bin/darkos_shell/ai_brain.py",
                    "airootfs/usr/local/bin/darkos_shell/assistant_trigger.py",
                    "airootfs/usr/local/bin/darkos_shell/actions.py",
                    "airootfs/usr/local/bin/darkos_shell/activity_detector.py",
                    "airootfs/usr/local/bin/darkos-ai-snapshot",
                    "airootfs/usr/local/bin/generate-wallpaper.py",
                    "airootfs/usr/share/backgrounds/darkos/darkos-wallpaper.png",
                    "airootfs/usr/local/bin/darkos_shell/darkos_cloud.py",
                    "airootfs/etc/sudoers.d/darkos-ai-snapshot",
                    "ci/test-activity-detector.py", "ci/test-phase3-linux.py",
                    "ci/vm-verify-phase3.py", "ci/build-darkos-calamares-module.sh",
                    "ci/vmware-phase3-guest.sh", "ci/vmware-calamares-atspi.py",
                    "ci/vmware-installed-flow-guest.sh", "ci/run-vmware-test.ps1",
                    "calamares-modules"):
            self.assertFalse((ROOT / rel).exists(), rel)

    def test_no_references_remain_in_runtime_config(self):
        banned = ("ai_brain", "assistant_trigger", "ActionDispatcher", "AI_ASSISTANT",
                  "--ptt-", "--toggle-ai", "darkos-wallpaper.png", "generate-wallpaper",
                  "darkosapikeys", "hyprctl hyprpaper", "ai-entry", "orb-button", "installer API keys",
                  ".config/darkos/env", "GROQ_API", "OPENROUTER_API")
        roots = [ROOT / "airootfs", ROOT / "build-iso.sh", ROOT / "profiledef.sh",
                 ROOT / "packages.x86_64"]
        offenders = []
        for base in roots:
            files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
            for path in files:
                if path.suffix in {".png", ".pyc", ".svg", ".ttf", ".gz"} or "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                offenders += [f"{path.relative_to(ROOT)}: {b}" for b in banned if b in text]
        self.assertEqual(offenders, [])

    def test_hyprland_conf_shape(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text()
        self.assertIn("background_color = rgb(0d0f12)", conf)  # fallback colour
        self.assertIn("darkos-window-fx.py --wallpaper-apply", conf)
        self.assertTrue(conf.rstrip().splitlines()[-1].startswith("source = ~/.config/hypr/conf.d/perf-auto.conf"),
                        "perf-auto.conf must be the last line so Lite wins")
        binds = [l for l in conf.splitlines() if l.startswith(("bind", "bindel", "bindl", "bindm"))]
        keys = [l.split("=", 1)[1].split(",")[0:2] for l in binds if l.startswith("bind =")]
        seen = {}
        for mods, key in ((k[0].strip(), k[1].strip()) for k in keys):
            self.assertNotIn((mods, key), seen, f"duplicate bind {mods} {key}")
            seen[(mods, key)] = True


if __name__ == "__main__":
    unittest.main(verbosity=2)
