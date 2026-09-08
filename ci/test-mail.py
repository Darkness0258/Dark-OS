#!/usr/bin/env python3
"""Mocked native Mail security/transport tests; never connects or sends mail."""
import importlib.util
from pathlib import Path
import ssl
import sys
import types
import unittest
from unittest.mock import Mock, patch

gi = types.ModuleType("gi")
gi.require_version = lambda *_: None
repository = types.ModuleType("gi.repository")
repository.Gtk = types.SimpleNamespace(ApplicationWindow=object)
repository.GLib = types.SimpleNamespace(SOURCE_REMOVE=False)
kit = types.ModuleType("darkos_shell.app_kit")
kit.add_class = kit.run_app = Mock()
spec = importlib.util.spec_from_file_location("darkos_mail_tested", Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin/darkos-mail.py")
mail = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository, "darkos_shell.app_kit": kit, spec.name: mail}):
    spec.loader.exec_module(mail)

ACCOUNT = mail.Account("imap.example.com", 993, "smtp.example.com", 465, "tester", "tester@example.com", "session-secret")


class MailTests(unittest.TestCase):
    def imap(self, count=b"1"):
        connection = Mock()
        connection.login.return_value = ("OK", [])
        connection.select.return_value = ("OK", [count])
        connection.response.return_value = ("UIDVALIDITY", [b"123"])
        connection.fetch.return_value = ("OK", [(b"1 (UID 7 RFC822.SIZE 100)", b"From: sender@example.com\r\nSubject: Hello\r\n\r\n")])
        return connection

    def test_tls_verifies_host_and_certificates(self):
        context = mail.tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_header_injection_and_invalid_recipient_rejected(self):
        for recipient in ("a@example.com\r\nBcc: b@example.com", "", "Name <a@example.com>", "a@", "a@example.com," ):
            with self.subTest(recipient=recipient):
                with self.assertRaises(mail.MailError):
                    mail.prepare_draft(ACCOUNT.sender, recipient, "Subject", "Body")
        with self.assertRaises(mail.MailError):
            mail.prepare_draft(ACCOUNT.sender, "a@example.com", "Hi\nBcc: b@example.com", "Body")

    def test_account_validation_and_password_repr(self):
        self.assertNotIn(ACCOUNT.password, repr(ACCOUNT))
        self.assertEqual(ACCOUNT.validate(), ACCOUNT)
        for host in ("https://imap.example.com", "host/path", "host\nname"):
            with self.assertRaises(mail.MailError):
                mail.validate_host(host)
        with self.assertRaises(mail.MailError):
            mail.Account(ACCOUNT.imap_host, True, ACCOUNT.smtp_host, 465, "u", ACCOUNT.sender, "p").validate()

    def test_readonly_inbox_and_header_peek(self):
        connection = self.imap(b"100")
        with patch.object(mail, "BoundedIMAPSSL", return_value=connection) as factory:
            generation, summaries = mail.fetch_inbox(ACCOUNT, mail.MailOperation())
        self.assertEqual(generation, 123)
        self.assertEqual(summaries[0].uid, 7)
        connection.select.assert_called_once_with("INBOX", readonly=True)
        self.assertEqual(connection.fetch.call_args.args[0], "76:100")
        self.assertIn("BODY.PEEK", connection.fetch.call_args.args[1])
        self.assertTrue(factory.call_args.kwargs["ssl_context"].check_hostname)
        connection.shutdown.assert_called_once()
        connection.close.assert_not_called()

    def test_empty_inbox_does_not_fetch(self):
        connection = self.imap(b"0")
        with patch.object(mail, "BoundedIMAPSSL", return_value=connection):
            self.assertEqual(mail.fetch_inbox(ACCOUNT, mail.MailOperation()), (123, []))
        connection.fetch.assert_not_called()

    def test_uidvalidity_change_blocks_stale_message(self):
        connection = self.imap()
        with patch.object(mail, "BoundedIMAPSSL", return_value=connection):
            with self.assertRaises(mail.MailError):
                mail.fetch_message(ACCOUNT, 124, 7, mail.MailOperation())
        connection.uid.assert_not_called()

    def test_body_fetch_uses_uid_and_peek(self):
        connection = self.imap()
        connection.uid.return_value = ("OK", [(b"1 (UID 7 BODY[] {100})", b"Content-Type: text/plain\r\n\r\nHello")])
        with patch.object(mail, "BoundedIMAPSSL", return_value=connection):
            text = mail.fetch_message(ACCOUNT, 123, 7, mail.MailOperation())
        self.assertIn("Hello", text)
        self.assertEqual(connection.uid.call_args.args[:2], ("fetch", "7"))
        self.assertIn("BODY.PEEK[]", connection.uid.call_args.args[2])

    def test_size_limits_and_html_are_not_rendered(self):
        with self.assertRaises(mail.MailError):
            mail.message_text(b"x" * (mail.MESSAGE_LIMIT + 1))
        result = mail.message_text(b"Content-Type: text/html\r\n\r\n<script>remote content</script>")
        self.assertNotIn("<script>", result)
        connection = object.__new__(mail.BoundedIMAPSSL)
        connection._received = 0
        with self.assertRaises(mail.MailError):
            connection.read(mail.MESSAGE_LIMIT + 2)

    def test_cancelled_operation_never_connects(self):
        operation = mail.MailOperation()
        operation.cancel()
        with patch.object(mail, "BoundedIMAPSSL") as factory:
            with self.assertRaises(TimeoutError):
                mail.fetch_inbox(ACCOUNT, operation)
        factory.assert_not_called()

    def test_send_uses_validated_envelope_and_tls(self):
        draft = mail.prepare_draft(ACCOUNT.sender, "one@example.com,two@example.com", "Test", "Body")
        connection = Mock()
        connection.send_message.return_value = {}
        with patch.object(mail.smtplib, "SMTP_SSL", return_value=connection) as factory:
            result = mail.send_draft(ACCOUNT, draft, mail.MailOperation())
        self.assertIn("Delivery is not yet confirmed", result)
        self.assertEqual(connection.send_message.call_args.kwargs["to_addrs"], list(draft.recipients))
        self.assertTrue(factory.call_args.kwargs["context"].check_hostname)
        connection.close.assert_called_once()

    def test_partial_refusal_and_uncertain_send_do_not_claim_delivery(self):
        draft = mail.prepare_draft(ACCOUNT.sender, "one@example.com,two@example.com", "Test", "Body")
        connection = Mock()
        connection.send_message.return_value = {"two@example.com": (550, b"secret server diagnostic")}
        with patch.object(mail.smtplib, "SMTP_SSL", return_value=connection):
            result = mail.send_draft(ACCOUNT, draft, mail.MailOperation())
        self.assertIn("1 of 2", result)
        self.assertNotIn("secret server diagnostic", result)
        operation = mail.MailOperation()
        operation.submission_started = True
        self.assertIn("uncertain", mail.error_message(TimeoutError(ACCOUNT.password), operation))

    def test_server_errors_never_echo_credentials(self):
        result = mail.error_message(mail.imaplib.IMAP4.error(ACCOUNT.password), mail.MailOperation())
        self.assertNotIn(ACCOUNT.password, result)

    def test_stale_and_closed_callbacks_are_dropped(self):
        window = types.SimpleNamespace(_closed=False, _generation=2)
        callback = Mock()
        mail.deliver_current(window, 1, callback, "old")
        window._closed = True
        mail.deliver_current(window, 2, callback, "new")
        callback.assert_not_called()

    def test_oversized_selection_cancels_previous_preview(self):
        window = types.SimpleNamespace(_validity=123, _cancel=Mock(), _set_busy=Mock(), reader=Mock())
        row = types.SimpleNamespace(summary=types.SimpleNamespace(size=mail.MESSAGE_LIMIT + 1))
        mail.MailWindow._read_selected(window, None, row)
        window._cancel.assert_called_once()
        window._set_busy.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
