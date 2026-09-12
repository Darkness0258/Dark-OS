#!/usr/bin/env python3
"""DarkOS Security Center — Vault, Privacy, Shield, Permissions, Encrypt.

Vault and Encrypt use PBKDF2-HMAC-SHA256 and authenticated Fernet encryption.
Shield runs cancellable, on-demand ClamAV scans. Continuous monitoring and
system integrity baselines require a separate configured service.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from cryptography.fernet import Fernet, InvalidToken  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402
from darkos_shell.shield import scan_and_quarantine  # noqa: E402

APP_ID = "org.darkos.SecurityCenter"
WM_CLASS = "darkos-security"
KDF_ITERATIONS = 480_000
SALT_LEN = 16
DATA_DIR_MODE = 0o700
VAULT_MODE = 0o600


def derive_key(password, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def write_private_new(path, data):
    """Publish a complete private file without replacing any existing path.

    A hard link makes publication atomic and rejects existing files, including
    symlinks. Unsupported filesystems fail explicitly instead of overwriting.
    """
    parent = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".darkos-private-", dir=parent)
    try:
        os.fchmod(fd, VAULT_MODE)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        os.unlink(temporary)


def darkos_data_dir():
    d = os.path.join(GLib.get_user_data_dir(), "darkos")
    os.makedirs(d, mode=DATA_DIR_MODE, exist_ok=True)
    # os.makedirs() does not update an existing directory's permissions.
    os.chmod(d, DATA_DIR_MODE)
    return d


def vault_path():
    path = os.path.join(darkos_data_dir(), "vault.dat")
    # Repair vaults written by older DarkOS versions with the user's umask.
    if os.path.exists(path):
        os.chmod(path, VAULT_MODE)
    return path


def privacy_settings_path():
    return os.path.join(darkos_data_dir(), "privacy-settings.json")


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
        self._closed = False
        self._scan_cancel = threading.Event()
        self.connect("destroy", self._on_destroy)

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
        try:
            self._save_vault(new=True)
        except OSError as error:
            self.vault_key = self.vault_salt = None
            self.vault_error_label.set_text(f"Couldn't create vault: {error}")
            return
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
            entries = json.loads(plaintext.decode("utf-8"))
            if not isinstance(entries, list) or not all(
                isinstance(entry, dict) and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in entry.items()
                ) for entry in entries
            ):
                raise ValueError("Invalid vault entry format")
            self.vault_salt = salt
            self.vault_key = key
            self.vault_entries = entries
        except InvalidToken:
            self.vault_error_label.set_text("Wrong password")
            return
        except (OSError, ValueError, json.JSONDecodeError) as e:
            self.vault_error_label.set_text(f"Couldn't open vault: {e}")
            return
        self._refresh_vault_list()
        self.vault_stack.set_visible_child_name("unlocked")

    def _save_vault(self, new=False):
        token = Fernet(self.vault_key).encrypt(json.dumps(self.vault_entries).encode("utf-8"))
        path = vault_path()
        if new:
            write_private_new(path, self.vault_salt + token)
            return
        fd, temp_path = tempfile.mkstemp(prefix=".vault-", dir=os.path.dirname(path))
        try:
            # mkstemp is private by default; fchmod also protects against a
            # permissive umask or platform-specific tempfile behavior.
            os.fchmod(fd, VAULT_MODE)
            with os.fdopen(fd, "wb") as f:
                fd = None
                f.write(self.vault_salt + token)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            temp_path = None
            dir_fd = os.open(
                os.path.dirname(path),
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if fd is not None:
                os.close(fd)
            if temp_path:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    def _lock_vault(self, *_):
        self.vault_key = None
        self.vault_salt = None
        self.vault_entries = []
        self.vault_pw_entry.set_text("")
        self.vault_error_label.set_text("")
        # A newly created vault must return to Unlock, not the old Create
        # screen, or a second password could silently replace the vault.
        self.vault_stack.remove(self.vault_stack.get_child_by_name("locked"))
        self.vault_stack.add_named(self._build_vault_lock_screen(), "locked")
        self.vault_stack.show_all()
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
                dialog = Gtk.MessageDialog(
                    transient_for=self, modal=True,
                    message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                    text="Delete this vault entry?",
                )
                dialog.format_secondary_text("This removes the saved entry permanently.")
                approved = dialog.run() == Gtk.ResponseType.OK
                dialog.destroy()
                if not approved:
                    return
                removed = self.vault_entries.pop(idx)
                try:
                    self._save_vault()
                except OSError as error:
                    self.vault_entries.insert(idx, removed)
                    self._show_vault_error(error)
                self._refresh_vault_list()
        return _delete

    def _show_vault_error(self, error):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text="The vault change could not be saved.",
        )
        dialog.format_secondary_text(str(error))
        dialog.run()
        dialog.destroy()

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
                try:
                    self._save_vault()
                except OSError as error:
                    self.vault_entries.pop()
                    self._show_vault_error(error)
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
    def _on_destroy(self, *_):
        self._closed = True
        self._scan_cancel.set()

    def _build_shield_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Shield</b>", xalign=0, use_markup=True), False, False, 0)
        box.pack_start(Gtk.Label(
            label="Scan a file or folder with ClamAV. Update definitions before scanning. "
                  "Scans leave files in place and report threats, unreadable content, or scan limits. "
                  "Continuous protection, quarantine, and system integrity checks are not enabled.",
            xalign=0, wrap=True,
        ), False, False, 8)
        actions = Gtk.Box(spacing=8)
        self._scan_buttons = []
        for label, folder in (("Scan file…", False), ("Scan folder…", True)):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _button, directory=folder: self._choose_scan(directory))
            actions.pack_start(button, False, False, 0)
            self._scan_buttons.append(button)
        update = Gtk.Button(label="Update definitions…")
        update.connect("clicked", self._update_definitions)
        actions.pack_start(update, False, False, 0)
        self._scan_buttons.append(update)
        self._cancel_scan = Gtk.Button(label="Cancel scan")
        self._cancel_scan.set_sensitive(False)
        self._cancel_scan.connect("clicked", lambda *_: self._scan_cancel.set())
        actions.pack_start(self._cancel_scan, False, False, 0)
        box.pack_start(actions, False, False, 0)
        self._scan_report = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
        self._scan_report.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._scan_report.get_buffer().set_text("Choose a file or folder to start a scan.")
        scroll = Gtk.ScrolledWindow()
        scroll.add(self._scan_report)
        box.pack_start(scroll, True, True, 0)
        return box

    def _update_definitions(self, *_):
        try:
            subprocess.Popen([
                "/usr/local/bin/the-void.sh", "-e", "/bin/sh", "-c",
                'sudo freshclam; result=$?; printf "\\nDefinition update exit status: %s\\nPress Enter to close.\\n" "$result"; read -r reply; exit "$result"',
            ])
        except OSError as error:
            self._scan_report.get_buffer().set_text(f"Could not open definition updater: {error}")

    def _choose_scan(self, folder):
        action = Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.OPEN
        chooser = Gtk.FileChooserDialog(title="Select scan target", transient_for=self, action=action)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Scan", Gtk.ResponseType.OK)
        selected = chooser.get_filename() if chooser.run() == Gtk.ResponseType.OK else None
        chooser.destroy()
        if not selected:
            return
        self._scan_cancel = threading.Event()
        for button in self._scan_buttons:
            button.set_sensitive(False)
        self._cancel_scan.set_sensitive(True)
        self._scan_report.get_buffer().set_text(f"Scanning {selected}…")
        threading.Thread(target=self._scan_worker, args=(Path(selected), self._scan_cancel), daemon=True).start()

    def _scan_worker(self, target, cancel):
        result, actions = scan_and_quarantine(target, cancel)
        quarantine_summary = ("\n\nQuarantine:\n" + "\n".join(f"  {a}" for a in actions)) if actions else ""
        GLib.idle_add(self._scan_finished, result, quarantine_summary)

    def _scan_finished(self, result, quarantine_summary=""):
        if self._closed:
            return False
        self._scan_report.get_buffer().set_text(result.detail + quarantine_summary)
        for button in self._scan_buttons:
            button.set_sensitive(True)
        self._cancel_scan.set_sensitive(False)
        return False

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
            write_private_new(out_path, salt + token)
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
            write_private_new(out_path, data)
            self.encrypt_status_label.set_text(f"Decrypted to {out_path}")
        except InvalidToken:
            self.encrypt_status_label.set_text("Wrong passphrase, or not a valid encrypted file.")
        except OSError as e:
            self.encrypt_status_label.set_text(f"Couldn't decrypt: {e}")


def build_window(app):
    return SecurityWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
