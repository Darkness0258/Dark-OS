"""Settings > Updates: the "Download mirrors" card.

Ranking asks for administrator rights (pkexec) and can take a minute or two,
so it runs on a worker thread and the card shows that it is working. The root
side is darkos-mirrors.py; this card only builds its argument list from a fixed
country table and reads the JSON it prints.
"""
import json
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from darkos_shell import mirrors, user_settings  # noqa: E402
from darkos_shell.app_kit import add_class  # noqa: E402

CLI = "/usr/local/bin/darkos-mirrors.py"
ANYWHERE = "Anywhere (fastest overall)"
PKEXEC_DISMISSED = (126, 127)   # authentication dismissed / not authorised


def privileged_run(argv, timeout=mirrors.RUN_TIMEOUT * 2 + 30):
    """Run `argv` as root through pkexec. Returns (returncode, stdout, stderr)."""
    try:
        done = subprocess.run(["pkexec", *argv], capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    except FileNotFoundError:
        return 127, "", "pkexec is not installed."
    except subprocess.TimeoutExpired:
        return 124, "", "Ranking took too long and was stopped."


def _label(text, css=None, wrap=True):
    label = Gtk.Label(label=text)
    label.set_xalign(0.0)
    label.set_line_wrap(wrap)
    if css:
        add_class(label, css)
    return label


def message_from(code, stdout, stderr):
    """What to tell the user after a pkexec run of the CLI. Returns (ok, text)."""
    for line in reversed((stdout or "").strip().splitlines()):
        try:
            data = json.loads(line)
            return bool(data.get("ok")), str(data.get("message", ""))
        except ValueError:
            continue
    if code in PKEXEC_DISMISSED:
        return False, "Cancelled: administrator rights are needed to change the mirror list."
    detail = (stderr or "").strip().splitlines()
    return False, detail[-1] if detail else f"It did not finish (exit {code})."


class MirrorCard(Gtk.Box):
    def __init__(self, load=None, save=None, status=None, run=None, live=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(self, "card")
        self.set_border_width(14)
        self.load_settings = load or user_settings.load_settings
        self.save_settings = save or user_settings.save_settings
        self.read_status = status or mirrors.status
        self.run = run or privileged_run
        self.live = live
        self.busy = False
        self._closed = False
        self.pack_start(_label("Download mirrors", "section-title"), False, False, 0)
        self.pack_start(_label(
            "Mirrors are the servers updates come from. Ranking picks fast, current HTTPS ones and "
            "keeps a backup of the list you had.", "body-muted"), False, False, 0)
        self.summary = _label("", "lead")
        self.pack_start(self.summary, False, False, 0)

        row = Gtk.Box(spacing=12)
        row.pack_start(_label("Prefer mirrors in", "body-muted", wrap=False), False, False, 0)
        self.country_combo = Gtk.ComboBoxText()
        self.country_combo.get_accessible().set_name("Mirror country")
        self.country_combo.append_text(ANYWHERE)
        for _code, name in mirrors.COUNTRIES:
            self.country_combo.append_text(name)
        row.pack_start(self.country_combo, False, False, 0)
        self.pack_start(row, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        self.rank_btn = Gtk.Button(label="Rank mirrors")
        add_class(self.rank_btn, "action-button")
        self.rank_btn.connect("clicked", lambda *_: self.rank())
        self.restore_btn = Gtk.Button(label="Restore previous list")
        self.restore_btn.connect("clicked", lambda *_: self.restore())
        buttons.pack_start(self.rank_btn, False, False, 0)
        buttons.pack_start(self.restore_btn, False, False, 0)
        self.pack_start(buttons, False, False, 0)
        self.result = _label("", "body-muted")
        self.pack_start(self.result, False, False, 0)
        self.connect("destroy", lambda *_: setattr(self, "_closed", True))
        self._select_saved_country()
        self.refresh()

    # -- state --------------------------------------------------------------
    def _select_saved_country(self):
        saved = str(self.load_settings().get("mirror_country", "") or "").upper()
        codes = [""] + [code for code, _name in mirrors.COUNTRIES]
        self.country_combo.set_active(codes.index(saved) if saved in codes else 0)

    def selected_country(self):
        index = self.country_combo.get_active()
        return "" if index <= 0 else mirrors.COUNTRIES[index - 1][0]

    def refresh(self):
        info = self.read_status()
        self.summary.set_text("Mirrors are chosen on the installed system, so this does nothing on the live ISO."
                              if self.live else mirrors.describe(info))
        self._sync(info.has_backup)

    def _sync(self, has_backup=None):
        if has_backup is None:
            has_backup = self.read_status().has_backup
        usable = not self.busy and not self.live
        self.rank_btn.set_sensitive(usable)
        self.restore_btn.set_sensitive(usable and has_backup)
        self.country_combo.set_sensitive(usable)

    # -- actions ------------------------------------------------------------
    def rank(self):
        if self.busy or self.live:
            return
        country = self.selected_country()
        settings = self.load_settings()
        if settings.get("mirror_country", "") != country:
            settings["mirror_country"] = country
            self.save_settings(settings)
        argv = [CLI, "rank", "--json", "--number", str(mirrors.DEFAULT_NUMBER)]
        if country:
            argv += ["--country", country]
        self._start(argv, "Ranking mirrors... this can take a minute or two. Your current list stays "
                          "in use until the new one is ready.")

    def restore(self):
        if self.busy or self.live:
            return
        self._start([CLI, "restore", "--json"], "Restoring the earlier list...")

    def _start(self, argv, working_text):
        self.busy = True
        self._sync()
        self.result.set_text(working_text)

        def work():
            code, out, err = self.run(argv)
            ok, text = message_from(code, out, err)
            GLib.idle_add(self._finished, ok, text)

        threading.Thread(target=work, daemon=True).start()

    def _finished(self, ok, text):
        self.busy = False
        if self._closed:
            return False
        self.result.set_text(text if ok else f"Not changed: {text}")
        self.refresh()
        return False
