#!/usr/bin/env python3
"""DarkOS Security Center — Vault, Privacy, Shield, Permissions, Encrypt.

Vault and Encrypt use real, standard primitives (PBKDF2-HMAC-SHA256 key
derivation + Fernet authenticated encryption from the `cryptography`
library) — not a homemade scheme. Shield is a deliberate honest stub, same
treatment as Connect in Network Center: real on-access scanning needs
fanotify (CAP_SYS_ADMIN) and real ClamAV/rkhunter/AIDE daemons this sandbox
can't grant or verify even in principle, so it isn't faked here.
"""
import base64
import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from cryptography.fernet import Fernet, InvalidToken  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.SecurityCenter"
WM_CLASS = "darkos-security"
KDF_ITERATIONS = 480_000
SALT_LEN = 16


def derive_key(password, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def vault_path():
    d = os.path.join(GLib.get_user_data_dir(), "darkos")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "vault.dat")


def privacy_settings_path():
    d = os.path.join(GLib.get_user_data_dir(), "darkos")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "privacy-settings.json")


def load_privacy_settings():
    try:
        with open(privacy_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_privacy_settings(data):
    keys = ("privacy_camera_indicator", "privacy_mic_indicator", "privacy_deny_location")
    try:
        with open(privacy_settings_path(), "w", encoding="utf-8") as f:
            json.dump({k: data.get(k, False) for k in keys}, f, indent=2)
    except OSError:
        pass


class SecurityWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Security Center")
        self.set_default_size(720, 560)
        add_class(self, "app-window")

        self.vault_key = None
        self.vault_salt = None
        self.vault_entries = []

        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        notebook.append_page(self._build_vault_tab(), Gtk.Label(label="Vault"))
        notebook.append_page(self._build_privacy_tab(), Gtk.Label(label="Privacy"))
        notebook.append_page(self._build_shield_tab(), Gtk.Label(label="Shield"))
        notebook.append_page(self._build_permissions_tab(), Gtk.Label(label="Permissions"))
        notebook.append_page(self._build_encrypt_tab(), Gtk.Label(label="Encrypt"))
        self.add(notebook)

    # -- Vault -----------------------------------------------------------------
    def _build_vault_tab(self):
        self.vault_stack = Gtk.Stack()
        self.vault_stack.add_named(self._build_vault_lock_screen(), "locked")
        self.vault_stack.add_named(self._build_vault_unlocked_screen(), "unlocked")
        return self.vault_stack

    def _build_vault_lock_screen(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(24)
        exists = os.path.exists(vault_path())
        title = "Unlock Vault" if exists else "Create Vault"
        box.pack_start(Gtk.Label(label=f"<b>{title}</b>", xalign=0, use_markup=True), False, False, 0)
        self.vault_pw_entry = Gtk.Entry(visibility=False, placeholder_text="Master password")
        self.vault_pw_entry.set_activates_default(True)
        box.pack_start(self.vault_pw_entry, False, False, 0)
        if not exists:
            self.vault_pw_confirm = Gtk.Entry(visibility=False, placeholder_text="Confirm password")
            box.pack_start(self.vault_pw_confirm, False, False, 0)
        self.vault_error_label = Gtk.Label(label="", xalign=0)
        box.pack_start(self.vault_error_label, False, False, 0)
        action_btn = Gtk.Button(label="Unlock" if exists else "Create")
        add_class(action_btn, "action-button")
        action_btn.set_halign(Gtk.Align.START)
        action_btn.connect("clicked", self._on_vault_unlock if exists else self._on_vault_create)
        box.pack_start(action_btn, False, False, 8)
        return box

    def _build_vault_unlocked_screen(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        toolbar.pack_start(Gtk.Label(label="Vault", xalign=0), True, True, 8)
        add_btn = Gtk.Button(label="Add Entry")
        add_class(add_btn, "icon-button")
        add_btn.connect("clicked", self._add_vault_entry)
        toolbar.pack_start(add_btn, False, False, 0)
        lock_btn = Gtk.Button(label="Lock")
        add_class(lock_btn, "icon-button")
        lock_btn.connect("clicked", self._lock_vault)
        toolbar.pack_start(lock_btn, False, False, 0)
        box.pack_start(toolbar, False, False, 0)

        self.vault_list = Gtk.ListBox()
        self.vault_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.vault_list, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.vault_list)
        box.pack_start(scroller, True, True, 0)
        return box

    def _on_vault_create(self, *_):
        pw = self.vault_pw_entry.get_text()
        confirm = self.vault_pw_confirm.get_text()
        if not pw:
            self.vault_error_label.set_text("Password can't be empty")
            return
        if pw != confirm:
            self.vault_error_label.set_text("Passwords don't match")
            return
        self.vault_salt = os.urandom(SALT_LEN)
        self.vault_key = derive_key(pw, self.vault_salt)
        self.vault_entries = []
        self._save_vault()
        self._refresh_vault_list()
        self.vault_stack.set_visible_child_name("unlocked")

    def _on_vault_unlock(self, *_):
        pw = self.vault_pw_entry.get_text()
        try:
            with open(vault_path(), "rb") as f:
                raw = f.read()
            salt, token = raw[:SALT_LEN], raw[SALT_LEN:]
            key = derive_key(pw, salt)
            plaintext = Fernet(key).decrypt(token)
            self.vault_salt = salt
            self.vault_key = key
            self.vault_entries = json.loads(plaintext.decode("utf-8"))
        except InvalidToken:
            self.vault_error_label.set_text("Wrong password")
            return
        except (OSError, ValueError, json.JSONDecodeError) as e:
            self.vault_error_label.set_text(f"Couldn't open vault: {e}")
            return
        self._refresh_vault_list()
        self.vault_stack.set_visible_child_name("unlocked")

    def _save_vault(self):
        token = Fernet(self.vault_key).encrypt(json.dumps(self.vault_entries).encode("utf-8"))
        with open(vault_path(), "wb") as f:
            f.write(self.vault_salt + token)

    def _lock_vault(self, *_):
        self.vault_key = None
        self.vault_salt = None
        self.vault_entries = []
        self.vault_pw_entry.set_text("")
        self.vault_error_label.set_text("")
        self.vault_stack.set_visible_child_name("locked")

    def _refresh_vault_list(self):
        for child in list(self.vault_list.get_children()):
            self.vault_list.remove(child)
        for idx, entry in enumerate(self.vault_entries):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            add_class(row, "sidebar-row")
            row.pack_start(Gtk.Label(label=entry.get("title", "Untitled"), xalign=0), True, True, 0)
            reveal_btn = Gtk.Button(label="Show")
            add_class(reveal_btn, "icon-button")
            reveal_btn.connect("clicked", self._make_vault_revealer(idx))
            row.pack_start(reveal_btn, False, False, 0)
            del_btn = Gtk.Button(label="Delete")
            add_class(del_btn, "icon-button")
            del_btn.connect("clicked", self._make_vault_deleter(idx))
            row.pack_start(del_btn, False, False, 0)
            self.vault_list.add(row)
        self.vault_list.show_all()

    def _make_vault_revealer(self, idx):
        def _reveal(*_):
            entry = self.vault_entries[idx]
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                text=entry.get("title", "Untitled"),
            )
            dialog.format_secondary_text(
                f"Username: {entry.get('username', '')}\nSecret: {entry.get('secret', '')}\nNotes: {entry.get('notes', '')}"
            )
            dialog.run()
            dialog.destroy()
        return _reveal

    def _make_vault_deleter(self, idx):
        def _delete(*_):
            if 0 <= idx < len(self.vault_entries):
                self.vault_entries.pop(idx)
                self._save_vault()
                self._refresh_vault_list()
        return _delete

    def _add_vault_entry(self, *_):
        dialog = Gtk.Dialog(title="Add Vault Entry", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_border_width(12)
        fields = {}
        for key, placeholder, hidden in [
            ("title", "Title (e.g. GitHub)", False),
            ("username", "Username / email", False),
            ("secret", "Password / secret", True),
            ("notes", "Notes (optional)", False),
        ]:
            entry = Gtk.Entry(placeholder_text=placeholder, visibility=not hidden)
            box.pack_start(entry, False, False, 2)
            fields[key] = entry
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            new_entry = {k: e.get_text() for k, e in fields.items()}
            if new_entry.get("title"):
                self.vault_entries.append(new_entry)
                self._save_vault()
                self._refresh_vault_list()
        dialog.destroy()

    # -- Privacy -----------------------------------------------------------------
    def _build_privacy_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Privacy</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(
            label="DarkOS sends no telemetry by default — there's no analytics pipeline in this "
                  "codebase to opt out of. The toggles below are real, saved preferences for apps "
                  "that check them going forward; nothing currently reads camera/mic/location "
                  "access, so treat these as staged, not enforced yet.",
            xalign=0, wrap=True,
        ), False, False, 8)
        settings = load_privacy_settings()
        for key, label in [
            ("privacy_camera_indicator", "Show an indicator when the camera is in use"),
            ("privacy_mic_indicator", "Show an indicator when the microphone is in use"),
            ("privacy_deny_location", "Deny location access to all apps by default"),
        ]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            switch = Gtk.Switch()
            switch.set_active(bool(settings.get(key, False)))
            switch.connect("state-set", self._make_privacy_toggler(key))
            row.pack_start(switch, False, False, 0)
            box.pack_start(row, False, False, 0)
        return box

    def _make_privacy_toggler(self, key):
        def _toggle(_switch, state):
            s = load_privacy_settings()
            s[key] = state
            save_privacy_settings(s)
        return _toggle

    # -- Shield ------------------------------------------------------------------
    def _build_shield_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Shield</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(
            label="Not implemented — and deliberately not faked. Real on-access scanning needs "
                  "fanotify, which needs CAP_SYS_ADMIN and a real kernel this sandbox doesn't grant "
                  "even in principle, plus actual ClamAV/rkhunter/AIDE daemons to scan and baseline "
                  "against. There's no way to verify a security tool here — writing one blind, with "
                  "no way to confirm it catches or misses anything, would be worse than waiting "
                  "until it can be built and checked on real hardware.",
            xalign=0, wrap=True,
        ), False, False, 8)
        scan_btn = Gtk.Button(label="Run Scan")
        add_class(scan_btn, "icon-button")
        scan_btn.set_sensitive(False)
        scan_btn.set_halign(Gtk.Align.START)
        scan_btn.set_tooltip_text("Not wired to a real scan engine yet")
        box.pack_start(scan_btn, False, False, 0)
        return box

    # -- Permissions -------------------------------------------------------------
    def _build_permissions_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Permissions</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(
            label="Same list as Settings > Permissions, same honest gap: no portal/sandboxing "
                  "backend exists yet to actually enforce a per-app permission toggle.",
            xalign=0, wrap=True,
        ), False, False, 8)
        open_btn = Gtk.Button(label="Open Settings > Permissions")
        add_class(open_btn, "icon-button")
        open_btn.set_halign(Gtk.Align.START)
        open_btn.connect("clicked", lambda *_: subprocess.Popen(["/usr/local/bin/darkos-settings.py"]))
        box.pack_start(open_btn, False, False, 0)
        return box

    # -- Encrypt -----------------------------------------------------------------
    def _build_encrypt_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Encrypt a file</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(
            label="PBKDF2-HMAC-SHA256 (480,000 iterations) derives the key; Fernet (AES-128-CBC "
                  "+ HMAC) does the actual authenticated encryption — both from the `cryptography` "
                  "library, nothing homemade.",
            xalign=0, wrap=True,
        ), False, False, 4)

        self.encrypt_file_label = Gtk.Label(label="No file chosen", xalign=0)
        pick_btn = Gtk.Button(label="Choose File…")
        add_class(pick_btn, "icon-button")
        pick_btn.connect("clicked", self._choose_encrypt_file)
        box.pack_start(pick_btn, False, False, 4)
        box.pack_start(self.encrypt_file_label, False, False, 0)

        self.encrypt_pw_entry = Gtk.Entry(visibility=False, placeholder_text="Passphrase")
        box.pack_start(self.encrypt_pw_entry, False, False, 4)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        enc_btn = Gtk.Button(label="Encrypt")
        add_class(enc_btn, "action-button")
        enc_btn.connect("clicked", self._do_encrypt)
        action_row.pack_start(enc_btn, False, False, 0)
        dec_btn = Gtk.Button(label="Decrypt")
        add_class(dec_btn, "icon-button")
        dec_btn.connect("clicked", self._do_decrypt)
        action_row.pack_start(dec_btn, False, False, 0)
        box.pack_start(action_row, False, False, 8)

        self.encrypt_status_label = Gtk.Label(label="", xalign=0, wrap=True)
        box.pack_start(self.encrypt_status_label, False, False, 0)
        self._encrypt_target = None
        return box

    def _choose_encrypt_file(self, *_):
        chooser = Gtk.FileChooserDialog(title="Choose file", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        if chooser.run() == Gtk.ResponseType.OK:
            self._encrypt_target = chooser.get_filename()
            self.encrypt_file_label.set_text(self._encrypt_target)
        chooser.destroy()

    def _do_encrypt(self, *_):
        if not self._encrypt_target or not self.encrypt_pw_entry.get_text():
            self.encrypt_status_label.set_text("Choose a file and enter a passphrase first.")
            return
        try:
            with open(self._encrypt_target, "rb") as f:
                data = f.read()
            salt = os.urandom(SALT_LEN)
            key = derive_key(self.encrypt_pw_entry.get_text(), salt)
            token = Fernet(key).encrypt(data)
            out_path = self._encrypt_target + ".darkvault"
            with open(out_path, "wb") as f:
                f.write(salt + token)
            self.encrypt_status_label.set_text(f"Encrypted to {out_path}")
        except OSError as e:
            self.encrypt_status_label.set_text(f"Couldn't encrypt: {e}")

    def _do_decrypt(self, *_):
        if not self._encrypt_target or not self.encrypt_pw_entry.get_text():
            self.encrypt_status_label.set_text("Choose a .darkvault file and enter its passphrase first.")
            return
        try:
            with open(self._encrypt_target, "rb") as f:
                raw = f.read()
            salt, token = raw[:SALT_LEN], raw[SALT_LEN:]
            key = derive_key(self.encrypt_pw_entry.get_text(), salt)
            data = Fernet(key).decrypt(token)
            out_path = self._encrypt_target[:-10] if self._encrypt_target.endswith(".darkvault") else self._encrypt_target + ".decrypted"
            with open(out_path, "wb") as f:
                f.write(data)
            self.encrypt_status_label.set_text(f"Decrypted to {out_path}")
        except InvalidToken:
            self.encrypt_status_label.set_text("Wrong passphrase, or not a valid encrypted file.")
        except OSError as e:
            self.encrypt_status_label.set_text(f"Couldn't decrypt: {e}")


def build_window(app):
    return SecurityWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
