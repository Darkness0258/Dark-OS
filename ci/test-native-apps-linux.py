#!/usr/bin/env python3
"""Real GTK/X11 startup and persistence regressions in an isolated home.

Run with: xvfb-run -a dbus-run-session -- python ci/test-native-apps-linux.py
This checks GTK behavior, not Wayland, device access, or installed-OS boot.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
APPS = (
    "backup", "calculator", "calendar", "clipboard", "clock", "dashboard",
    "devhub", "downloads", "emoji", "files", "gallery", "gaming", "mail", "mission",
    "network", "notes", "reader", "security", "settings", "store", "terminal",
)


def load_app(name: str):
    path = BIN / f"darkos-{name}.py"
    spec = importlib.util.spec_from_file_location(f"darkos_test_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(BIN))
    sys.argv = [str(path)]
    spec.loader.exec_module(module)
    return module


def worker(name: str) -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gio, GLib, Gtk

    errors = []
    def record_error(*error):
        errors.append(error)
        sys.__excepthook__(*error)
    sys.excepthook = record_error
    module = load_app("security" if name == "security-regressions" else name)
    app = Gtk.Application(application_id="org.darkos.Regression", flags=Gio.ApplicationFlags.NON_UNIQUE)
    assert app.register(None)
    from darkos_shell.css import apply_css

    apply_css()
    window_type = next(
        value for value in vars(module).values()
        if isinstance(value, type) and value.__module__ == module.__name__
        and issubclass(value, Gtk.ApplicationWindow)
    )
    window = window_type(app)
    window.show_all()
    assert window.get_realized() and window.get_children()
    if name == "security-regressions":
        window.vault_pw_entry.set_text("test-only password")
        window.vault_pw_confirm.set_text("test-only password")
        window._on_vault_create()
        vault = Path(module.vault_path())
        assert vault.is_file() and vault.stat().st_mode & 0o777 == 0o600
        original = vault.read_bytes()
        window._lock_vault()
        locked = window.vault_stack.get_child_by_name("locked")
        assert any(isinstance(child, Gtk.Button) and child.get_label() == "Unlock" for child in locked.get_children())
        window.vault_pw_entry.set_text("wrong password")
        window._on_vault_unlock()
        assert window.vault_key is None and vault.read_bytes() == original
        window.vault_pw_entry.set_text("test-only password")
        window._on_vault_unlock()
        assert window.vault_key is not None
        try:
            window._save_vault(new=True)
        except FileExistsError:
            pass
        else:
            raise AssertionError("new vault creation replaced an existing vault")
        assert vault.read_bytes() == original
        target = Path(os.environ["HOME"]) / "private.txt"
        target.write_bytes(b"private round-trip content")
        window._encrypt_target = str(target)
        window.encrypt_pw_entry.set_text("file password")
        window._do_encrypt()
        encrypted = Path(str(target) + ".darkvault")
        assert encrypted.is_file() and encrypted.stat().st_mode & 0o777 == 0o600
        cipher = encrypted.read_bytes()
        window._do_encrypt()
        assert encrypted.read_bytes() == cipher
        target.write_bytes(b"do not overwrite this existing file")
        window._encrypt_target = str(encrypted)
        window._do_decrypt()
        assert target.read_bytes() == b"do not overwrite this existing file"
        target.unlink()  # This test owns the exact temporary file.
        window.encrypt_pw_entry.set_text("wrong password")
        window._do_decrypt()
        assert not target.exists()
        window.encrypt_pw_entry.set_text("file password")
        window._do_decrypt()
        assert target.read_bytes() == b"private round-trip content"
        assert target.stat().st_mode & 0o777 == 0o600
        assert not list(target.parent.glob(".darkos-private-*"))
    if name == "notes":
        window._new_note()
        target = Path(window.current_path)
        window.buffer.set_text("Pending autosave must survive immediate close.")
        window.destroy()
        assert target.read_text() == "Pending autosave must survive immediate close."
        explicit = Path(os.environ["HOME"]) / "explicit.txt"
        explicit.write_text("Existing content")
        window = window_type(app, open_path=str(explicit))
        window.buffer.set_text("Not explicitly saved")
        window.destroy()
        assert explicit.read_text() == "Existing content"
    else:
        GLib.timeout_add(750, lambda: (Gtk.main_quit(), False)[1])
        Gtk.main()
        window.destroy()
    if errors:
        kind, value, trace = errors[0]
        raise value.with_traceback(trace)


def main() -> None:
    if sys.platform != "linux" or not os.environ.get("DISPLAY"):
        raise SystemExit("Run under Linux with xvfb-run and a D-Bus session.")
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
        return
    with tempfile.TemporaryDirectory(prefix="darkos-native-tests-") as directory:
        for name in (*APPS, "security-regressions"):
            home = Path(directory) / name
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(home / "data"),
                   "XDG_CONFIG_HOME": str(home / "config"), "XDG_CACHE_HOME": str(home / "cache"),
                   "GDK_BACKEND": "x11", "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", name],
                cwd=home, env=env, capture_output=True, text=True, timeout=30,
            )
            if result.returncode:
                raise AssertionError(f"{name} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
            print(f"PASS {name}", flush=True)
        # These two invocations share the same session bus. A unique GTK
        # application would silently discard the second invocation's -e/cwd.
        terminal = str(BIN / "darkos-terminal.py")
        home = Path(directory) / "second-terminal"
        home.mkdir()
        marker = home / "second-command.txt"
        env = {**os.environ, "HOME": str(home), "GDK_BACKEND": "x11",
               "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data")}
        with tempfile.TemporaryFile() as log:
            first = subprocess.Popen(
                [sys.executable, terminal, "-e", sys.executable, "-c", "import time; time.sleep(20)"],
                env=env, stdout=log, stderr=log,
            )
            second = None
            try:
                time.sleep(2)
                assert first.poll() is None
                second = subprocess.Popen(
                    [sys.executable, terminal, "--cwd", str(home), "-e", sys.executable, "-c",
                     "import pathlib; pathlib.Path('second-command.txt').write_text(str(pathlib.Path.cwd()))"],
                    env=env, stdout=log, stderr=log,
                )
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert marker.exists() and marker.read_text() == str(home), "Second terminal lost its command/cwd"
                print("PASS concurrent terminal command/cwd", flush=True)
            finally:
                for process in (first, second):
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
    print(f"All {len(APPS)} native GTK startups and security/notes persistence checks passed.")


if __name__ == "__main__":
    main()
