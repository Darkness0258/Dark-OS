#!/usr/bin/env python3
"""Basic native Mail: a read-only IMAPS inbox and confirmed SMTPS text sending.

Account details, passwords and drafts live only in memory. Both protocols use
certificate-verified implicit TLS. No HTML renderer, attachments or OAuth flow.
"""
import imaplib
import ipaddress
import re
import smtplib
import socket
import ssl
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.Mail"
WM_CLASS = "darkos-mail"
SOCKET_TIMEOUT = 8
OPERATION_TIMEOUT = 35
INBOX_LIMIT = 25
HEADER_LIMIT = 16384
MESSAGE_LIMIT = 1024 * 1024
BODY_LIMIT = 256 * 1024
RESPONSE_LIMIT = 2 * 1024 * 1024
UID_PATTERN = re.compile(rb"\bUID ([0-9]+)\b", re.I)
SIZE_PATTERN = re.compile(rb"\bRFC822\.SIZE ([0-9]+)\b", re.I)
LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*\Z")
HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


class MailError(ValueError):
    """A locally generated, credential-free explanation suitable for the UI."""


def single_line(value, label, maximum):
    if not isinstance(value, str) or len(value) > maximum or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise MailError(f"{label} contains unsupported characters or is too long.")
    return value


def validate_host(value):
    value = single_line(value, "Server hostname", 253).strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if not value or not all(HOST_LABEL.fullmatch(part) for part in value.split(".")):
            raise MailError("Enter a server hostname without a URL scheme, path or spaces.") from None
        return value.lower()


def validate_address(value):
    value = single_line(value, "Email address", 254).strip()
    if value.count("@") != 1:
        raise MailError("Use a plain email address such as name@example.com, without a display name.")
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or not LOCAL_PART.fullmatch(local) or not all(
        HOST_LABEL.fullmatch(part) for part in domain.split(".")
    ):
        raise MailError("Use a plain ASCII email address; quoted names and address groups are not supported.")
    return local + "@" + domain.lower()


@dataclass(frozen=True)
class Account:
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    username: str
    sender: str
    password: str = field(repr=False, compare=False)

    def validate(self):
        for port in (self.imap_port, self.smtp_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise MailError("Server ports must be numbers from 1 to 65535.")
        username = single_line(self.username, "Username", 320).strip()
        password = single_line(self.password, "Password", 1024)
        if not username or not password or not username.isascii() or not password.isascii():
            raise MailError("Enter an ASCII username and password or provider app password.")
        return Account(
            validate_host(self.imap_host), self.imap_port, validate_host(self.smtp_host),
            self.smtp_port, username, validate_address(self.sender), password,
        )


@dataclass(frozen=True)
class Draft:
    sender: str
    recipients: tuple
    subject: str
    body: str = field(repr=False)


def prepare_draft(sender, recipients, subject, body):
    single_line(recipients, "Recipients", 6000)
    items = recipients.split(",")
    if not 1 <= len(items) <= 20:
        raise MailError("Send to between 1 and 20 comma-separated email addresses.")
    addresses = tuple(dict.fromkeys(validate_address(item) for item in items))
    subject = single_line(subject, "Subject", 200)
    if not isinstance(body, str) or len(body.encode("utf-8")) > BODY_LIMIT or "\x00" in body:
        raise MailError("The message body must be text of at most 256 KiB without NUL characters.")
    return Draft(validate_address(sender), addresses, subject, body)


def build_message(draft):
    # Validate again at the transport boundary, including callers outside GTK.
    checked = prepare_draft(draft.sender, ", ".join(draft.recipients), draft.subject, draft.body)
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = checked.sender
    message["To"] = ", ".join(checked.recipients)
    message["Subject"] = checked.subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(checked.body)
    return message


def tls_context():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class MailOperation:
    """A deadline and socket cancellation handle; never stores credentials."""
    def __init__(self):
        self.deadline = time.monotonic() + OPERATION_TIMEOUT
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._socket = None
        self.submission_started = False

    def checkpoint(self):
        if self.cancelled.is_set() or time.monotonic() >= self.deadline:
            raise TimeoutError("Mail operation cancelled or timed out")

    def attach(self, connection):
        with self._lock:
            self._socket = connection.sock
        if self.cancelled.is_set():
            self.cancel()
        self.checkpoint()
        self._socket.settimeout(min(SOCKET_TIMEOUT, max(0.1, self.deadline - time.monotonic())))

    def cancel(self):
        self.cancelled.set()
        with self._lock:
            current = self._socket
        if current is not None:
            try:
                current.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                current.close()
            except OSError:
                pass


class BoundedIMAPSSL(imaplib.IMAP4_SSL):
    """Reject oversized literals before imaplib allocates/reads their payload."""
    def __init__(self, *args, **kwargs):
        self._received = 0
        super().__init__(*args, **kwargs)

    def read(self, size):
        if size < 0 or size > MESSAGE_LIMIT + 1 or self._received + size > RESPONSE_LIMIT:
            raise MailError("The mail server returned a response larger than the reader limit.")
        self._received += size
        return super().read(size)

    def readline(self):
        line = super().readline()
        self._received += len(line)
        if self._received > RESPONSE_LIMIT:
            raise MailError("The mail server returned too much data for one request.")
        return line


def require_ok(response, explanation):
    status, data = response
    if status != "OK":
        raise MailError(explanation)
    return data


def uid_number(value):
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="strict")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,10}", value):
        raise MailError("The mail server returned an invalid message identifier.")
    number = int(value)
    if not 1 <= number <= 4294967295:
        raise MailError("The mail server returned an invalid message identifier.")
    return number


def open_inbox(account, operation):
    operation.checkpoint()
    connection = BoundedIMAPSSL(
        account.imap_host, account.imap_port, ssl_context=tls_context(), timeout=SOCKET_TIMEOUT,
    )
    try:
        operation.attach(connection)
        connection.debug = 0
        require_ok(connection.login(account.username, account.password), "The mail server rejected the account login.")
        operation.checkpoint()
        count = require_ok(connection.select("INBOX", readonly=True), "The server could not open the inbox read-only.")
        validity = connection.response("UIDVALIDITY")[1]
        if not validity or validity[0] is None:
            raise MailError("The server did not provide stable inbox identifiers.")
        generation = uid_number(validity[0])
        if not count or not re.fullmatch(rb"[0-9]{1,10}", count[0]):
            raise MailError("The server returned an invalid inbox count.")
        return connection, int(count[0]), generation
    except Exception:
        connection.shutdown()
        raise


def display_header(message, name, fallback):
    value = str(message.get(name, fallback))
    return " ".join(value.split())[:300]


@dataclass(frozen=True)
class MessageSummary:
    uid: int
    size: int
    sender: str
    subject: str
    date: str


def parse_summaries(data):
    messages = {}
    for item in data:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        metadata, raw = item
        if not isinstance(metadata, bytes) or not isinstance(raw, bytes):
            continue
        uid_match, size_match = UID_PATTERN.search(metadata), SIZE_PATTERN.search(metadata)
        if not uid_match or not size_match or len(raw) > HEADER_LIMIT:
            raise MailError("The server returned incomplete or oversized message headers.")
        uid = uid_number(uid_match[1])
        message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
        messages[uid] = MessageSummary(
            uid, int(size_match[1]), display_header(message, "From", "Unknown sender"),
            display_header(message, "Subject", "(No subject)"), display_header(message, "Date", ""),
        )
        if len(messages) > INBOX_LIMIT:
            raise MailError("The server returned more inbox messages than requested.")
    return sorted(messages.values(), key=lambda message: message.uid, reverse=True)


def fetch_inbox(account, operation):
    account = account.validate()
    connection, count, validity = open_inbox(account, operation)
    try:
        if count == 0:
            return validity, []
        operation.checkpoint()
        first = max(1, count - INBOX_LIMIT + 1)
        data = require_ok(connection.fetch(
            f"{first}:{count}", f"(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)]<0.{HEADER_LIMIT}>)",
        ), "The server could not read inbox headers.")
        return validity, parse_summaries(data)
    finally:
        # Local shutdown cannot expunge messages, unlike IMAP CLOSE.
        connection.shutdown()


def message_text(raw):
    if len(raw) > MESSAGE_LIMIT:
        raise MailError("This message exceeds the 1 MiB reader limit. Open it in a full mail client.")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        body = "This message has no plain-text body. HTML and attachments are not displayed in basic Mail."
    else:
        try:
            body = part.get_content()
        except (LookupError, UnicodeError):
            body = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if not isinstance(body, str):
            body = "This message does not contain a supported plain-text body."
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + "\n\n[Text preview truncated]"
    body = body.replace("\x00", "\ufffd")
    return (
        f"From: {display_header(message, 'From', 'Unknown sender')}\n"
        f"Subject: {display_header(message, 'Subject', '(No subject)')}\n"
        f"Date: {display_header(message, 'Date', '')}\n\n{body}"
    )


def fetch_message(account, validity, uid, operation):
    account = account.validate()
    uid = uid_number(str(uid))
    connection, _count, current_validity = open_inbox(account, operation)
    try:
        if current_validity != validity:
            raise MailError("The inbox changed its message identifiers. Refresh before opening this message.")
        operation.checkpoint()
        data = require_ok(connection.uid("fetch", str(uid), f"(BODY.PEEK[]<0.{MESSAGE_LIMIT + 1}>)"),
                          "The server could not read this message.")
        for item in data:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], bytes):
                match = UID_PATTERN.search(item[0])
                if match and uid_number(match[1]) == uid and isinstance(item[1], bytes):
                    return message_text(item[1])
        raise MailError("This message is no longer available. Refresh the inbox.")
    finally:
        connection.shutdown()


def send_draft(account, draft, operation):
    account = account.validate()
    if draft.sender != account.sender:
        raise MailError("The sender account changed. Review the message again before sending.")
    message = build_message(draft)
    operation.checkpoint()
    connection = smtplib.SMTP_SSL(
        account.smtp_host, account.smtp_port, context=tls_context(), timeout=SOCKET_TIMEOUT,
    )
    try:
        operation.attach(connection)
        connection.set_debuglevel(0)
        connection.login(account.username, account.password)
        operation.checkpoint()
        operation.submission_started = True
        refused = connection.send_message(message, from_addr=draft.sender, to_addrs=list(draft.recipients))
        if refused:
            rejected = [address for address in draft.recipients if address in refused]
            return (
                f"SMTP accepted {len(draft.recipients) - len(rejected)} of {len(draft.recipients)} recipients. "
                f"Refused: {', '.join(rejected)}. Do not resend to recipients already accepted."
            )
        return "SMTP accepted the message for all recipients. Delivery is not yet confirmed; this app does not save a Sent copy."
    finally:
        connection.close()


def error_message(error, operation):
    # Never display arbitrary server/exception strings: an AUTH response may
    # echo credentials, and SMTP errors may include private message content.
    if isinstance(error, MailError):
        return str(error)
    if operation.submission_started:
        return "Send status is uncertain. Check your provider before retrying to avoid sending a duplicate."
    if isinstance(error, ssl.SSLCertVerificationError):
        return "The server certificate could not be verified. Check the hostname, system clock and provider TLS configuration."
    if isinstance(error, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)):
        return "The server rejected the login or IMAP request. Check its app-password and IMAP/SMTP access requirements."
    if isinstance(error, (TimeoutError, socket.timeout)) or operation.cancelled.is_set():
        return "The mail request timed out or was cancelled."
    return "The mail request failed. Check the server settings, TLS support and network connection."


def deliver_current(window, generation, callback, *args):
    """Only the active request may update a live window."""
    if not window._closed and generation == window._generation:
        callback(*args)
    return GLib.SOURCE_REMOVE


class MailWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Mail")
        self.set_default_size(1040, 760)
        add_class(self, "app-window")
        self._closed = False
        self._generation = 0
        self._operation = None
        self._validity = None
        self.connect("destroy", self._on_destroy)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(16)
        self.add(box)
        box.pack_start(Gtk.Label(
            label="Basic Mail uses verified implicit TLS (IMAP usually 993, SMTP usually 465). "
                  "Use your provider's app password where required. OAuth-only or STARTTLS-only accounts "
                  "need a full mail client. Account details and passwords last only for this window.",
            xalign=0, wrap=True,
        ), False, False, 0)
        self.account_grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        self.entries = {}
        for index, (key, label, placeholder, default) in enumerate((
            ("imap_host", "IMAP server", "imap.example.com", ""),
            ("imap_port", "IMAP TLS port", "993", "993"),
            ("smtp_host", "SMTP server", "smtp.example.com", ""),
            ("smtp_port", "SMTP TLS port", "465", "465"),
            ("username", "Username", "name@example.com", ""),
            ("sender", "From address", "name@example.com", ""),
            ("password", "Password / app password", "Session only", ""),
        )):
            row, column = divmod(index, 2)
            self.account_grid.attach(Gtk.Label(label=label, xalign=0), column * 2, row, 1, 1)
            entry = Gtk.Entry(text=default, placeholder_text=placeholder, hexpand=True)
            if key == "password":
                entry.set_visibility(False)
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            self.entries[key] = entry
            self.account_grid.attach(entry, column * 2 + 1, row, 1, 1)
        box.pack_start(self.account_grid, False, False, 0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.refresh_button = Gtk.Button(label="Read inbox")
        self.refresh_button.connect("clicked", self._refresh)
        self.compose_button = Gtk.Button(label="Compose")
        self.compose_button.connect("clicked", self._compose)
        for button in (self.refresh_button, self.compose_button):
            add_class(button, "icon-button")
            toolbar.pack_start(button, False, False, 0)
        box.pack_start(toolbar, False, False, 0)
        self.status = Gtk.Label(label="Enter the account settings, then read your inbox.", xalign=0, wrap=True)
        box.pack_start(self.status, False, False, 0)
        panes = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.message_list = Gtk.ListBox()
        self.message_list.connect("row-selected", self._read_selected)
        sidebar = Gtk.ScrolledWindow()
        sidebar.set_size_request(310, -1)
        sidebar.add(self.message_list)
        panes.pack1(sidebar, False, False)
        self.reader = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.reader.set_left_margin(12)
        self.reader.set_right_margin(12)
        reader_scroll = Gtk.ScrolledWindow()
        reader_scroll.add(self.reader)
        panes.pack2(reader_scroll, True, False)
        box.pack_start(panes, True, True, 0)
        for entry in self.entries.values():
            entry.connect("changed", self._account_changed)

    def _account(self):
        values = {key: entry.get_text() for key, entry in self.entries.items()}
        try:
            values["imap_port"] = int(values["imap_port"])
            values["smtp_port"] = int(values["smtp_port"])
        except ValueError:
            raise MailError("Server ports must be numbers from 1 to 65535.") from None
        return Account(**values).validate()

    def _cancel(self):
        self._generation += 1
        if self._operation:
            self._operation.cancel()
            self._operation = None

    def _on_destroy(self, *_):
        self._closed = True
        self._cancel()
        self.entries["password"].set_text("")

    def _account_changed(self, *_):
        if self._closed:
            return
        self._cancel()
        self._set_busy(False)
        self._clear_inbox()
        self.status.set_text("Account settings changed. Read the inbox to connect.")

    def _set_busy(self, busy, sending=False):
        self.refresh_button.set_sensitive(not busy)
        self.compose_button.set_sensitive(not busy)
        self.account_grid.set_sensitive(not sending)
        self.message_list.set_sensitive(not sending)

    def _launch(self, worker, on_success, sending=False):
        self._cancel()
        generation = self._generation
        operation = MailOperation()
        self._operation = operation
        self._set_busy(True, sending)
        timer = threading.Timer(OPERATION_TIMEOUT, operation.cancel)
        timer.daemon = True
        timer.start()

        def work():
            try:
                result = (True, worker(operation))
            except Exception as exc:
                result = (False, error_message(exc, operation))
            finally:
                timer.cancel()

            def finish(ok, detail):
                self._operation = None
                self._set_busy(False)
                if ok:
                    on_success(detail)
                else:
                    self.status.set_text(detail)

            GLib.idle_add(deliver_current, self, generation, finish, *result)

        threading.Thread(target=work, daemon=True, name="darkos-mail-request").start()

    def _clear_inbox(self):
        self._validity = None
        for row in self.message_list.get_children():
            self.message_list.remove(row)
        self.reader.get_buffer().set_text("")

    def _refresh(self, *_):
        try:
            account = self._account()
        except MailError as exc:
            self.status.set_text(str(exc))
            return
        self._clear_inbox()
        self.status.set_text("Reading the newest 25 inbox headers…")

        def loaded(result):
            self._validity, messages = result
            for message in messages:
                row = Gtk.ListBoxRow()
                row.summary = message
                label = Gtk.Label(label=f"{message.subject}\n{message.sender}\n{message.date}", xalign=0, wrap=True)
                label.set_margin_top(8)
                label.set_margin_bottom(8)
                row.add(label)
                self.message_list.add(row)
            self.message_list.show_all()
            self.status.set_text(f"Showing {len(messages)} recent messages. Reading does not mark them read or delete them.")

        self._launch(lambda operation: fetch_inbox(account, operation), loaded)

    def _read_selected(self, _listbox, row):
        if row is None or self._validity is None:
            return
        # Even a message we cannot preview replaces the previous selection.
        # Invalidate its in-flight request so it cannot repaint the old body.
        self._cancel()
        self._set_busy(False)
        self.reader.get_buffer().set_text("")
        if row.summary.size > MESSAGE_LIMIT:
            self.reader.get_buffer().set_text("This message exceeds the 1 MiB reader limit. Open it in a full mail client.")
            return
        try:
            account = self._account()
        except MailError as exc:
            self.status.set_text(str(exc))
            return
        uid, validity = row.summary.uid, self._validity
        self.status.set_text("Reading message text…")
        self.reader.get_buffer().set_text("")

        def loaded(text):
            self.reader.get_buffer().set_text(text)
            self.status.set_text("Read-only text preview. HTML, attachments and external content are not loaded.")

        self._launch(lambda operation: fetch_message(account, validity, uid, operation), loaded)

    def _compose(self, *_):
        try:
            account = self._account()
        except MailError as exc:
            self.status.set_text(str(exc))
            return
        dialog = Gtk.Dialog(title="Compose text message", transient_for=self, modal=True)
        dialog.set_default_size(680, 500)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Review message", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_border_width(12)
        content.pack_start(Gtk.Label(label=f"From: {account.sender}", xalign=0), False, False, 0)
        recipients = Gtk.Entry(placeholder_text="To: comma-separated email addresses")
        subject = Gtk.Entry(placeholder_text="Subject")
        body = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for entry in (recipients, subject):
            content.pack_start(entry, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.add(body)
        content.pack_start(scroll, True, True, 0)
        validation = Gtk.Label(xalign=0, wrap=True)
        content.pack_start(validation, False, False, 0)
        dialog.show_all()
        draft = None
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                buffer = body.get_buffer()
                draft = prepare_draft(account.sender, recipients.get_text(), subject.get_text(),
                                      buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True))
                if self._confirm_send(draft):
                    break
            except MailError as exc:
                validation.set_text(str(exc))
            draft = None
        dialog.destroy()
        if draft is not None:
            self.status.set_text("Submitting the confirmed message over TLS…")
            self._launch(lambda operation: send_draft(account, draft, operation), self.status.set_text, sending=True)

    def _confirm_send(self, draft):
        dialog = Gtk.Dialog(title="Confirm sending this message", transient_for=self, modal=True)
        dialog.set_default_size(680, 520)
        dialog.add_buttons("Back", Gtk.ResponseType.CANCEL, "Send message", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        content = dialog.get_content_area()
        content.set_border_width(12)
        preview = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        preview.get_buffer().set_text(
            f"From: {draft.sender}\nTo: {', '.join(draft.recipients)}\nSubject: {draft.subject}\n\n{draft.body}"
        )
        scroll = Gtk.ScrolledWindow()
        scroll.add(preview)
        content.pack_start(scroll, True, True, 0)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK


def build_window(app):
    return MailWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
