import json
import tempfile
import unittest
from pathlib import Path

from audit_log import audit_event, configure_audit_logger


class AuditLogTests(unittest.TestCase):
    def test_writes_taipei_jsonl_and_redacts_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "audit.jsonl"
            logger = configure_audit_logger(path)

            audit_event(
                logger,
                "smsforwarder.rejected",
                status_code=422,
                reason="sender_not_allowed",
                otp="246810",
                sms_body="銀行驗證碼 246810",
                token="consumer-secret",
            )

            record = json.loads(path.read_text(encoding="utf-8").strip())
            configure_audit_logger(None)

        self.assertEqual(record["event"], "smsforwarder.rejected")
        self.assertEqual(record["status_code"], 422)
        self.assertEqual(record["reason"], "sender_not_allowed")
        self.assertEqual(record["otp"], "[REDACTED]")
        self.assertEqual(record["sms_body"], "[REDACTED]")
        self.assertEqual(record["token"], "[REDACTED]")
        self.assertRegex(record["timestamp"], r"\+08:00$")

    def test_redacts_unknown_field_aliases_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "audit.jsonl"
            logger = configure_audit_logger(path)
            audit_event(
                logger,
                "test.unknown_fields",
                status_code=200,
                full_sender="OTHER",
                sms_content="驗證碼 135790",
                message_body="驗證碼 135790",
                card_data="4111111111111111",
            )
            log_text = path.read_text(encoding="utf-8")
            configure_audit_logger(None)

        record = json.loads(log_text.strip())
        self.assertEqual(record["status_code"], 200)
        self.assertEqual(record["full_sender"], "[REDACTED]")
        self.assertEqual(record["sms_content"], "[REDACTED]")
        self.assertEqual(record["message_body"], "[REDACTED]")
        self.assertEqual(record["card_data"], "[REDACTED]")
        for secret in ("OTHER", "135790", "4111111111111111"):
            self.assertNotIn(secret, log_text)

    def test_rotates_audit_files_at_configured_size(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "audit.jsonl"
            logger = configure_audit_logger(path, backup_count=2, max_bytes=256)
            for index in range(20):
                audit_event(logger, "test.rotation", status_code=200, sequence=index)
            configure_audit_logger(None)
            log_files = sorted(path.parent.glob("audit.jsonl*"))
            total_size = sum(file.stat().st_size for file in log_files)

        self.assertLessEqual(len(log_files), 3)
        self.assertTrue(any(file.name != "audit.jsonl" for file in log_files))
        self.assertLessEqual(total_size, 768)


if __name__ == "__main__":
    unittest.main()
