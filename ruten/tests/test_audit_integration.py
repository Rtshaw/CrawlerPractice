import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import requests
import uvicorn

from audit_log import configure_audit_logger
from main import (
    ServerSettings,
    create_app,
    generate_smsforwarder_signature,
)


class AuditApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audit_path = Path(self.temp.name) / "audit.jsonl"
        self.audit_logger = configure_audit_logger(self.audit_path)
        settings = ServerSettings(
            upload_token="upload-secret-token",
            consumer_token="consumer-secret-token",
            smsforwarder_secret="smsforwarder-official-secret",
            otp_ttl_seconds=300,
            max_long_poll_seconds=2,
            smsforwarder_max_skew_seconds=300,
            allowed_sender_pattern=r"^BANK$",
        )
        self.app = create_app(settings=settings, audit_logger=self.audit_logger)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="critical")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if requests.get(self.base_url + "/health", timeout=0.2).status_code == 200:
                    return
            except requests.RequestException:
                time.sleep(0.05)
        self.fail("test API server did not start")

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        configure_audit_logger(None)
        self.temp.cleanup()

    def test_audit_records_accept_delivery_and_empty_poll_without_otp(self):
        timestamp = str(int(time.time() * 1000))
        signature = generate_smsforwarder_signature(
            timestamp, "smsforwarder-official-secret"
        )
        accepted = requests.post(
            self.base_url + "/api/v1/smsforwarder",
            data={
                "from": "BANK",
                "content": "銀行 OTP 246810",
                "timestamp": timestamp,
                "sign": signature,
            },
            timeout=2,
        )
        self.assertEqual(accepted.status_code, 202, accepted.text)

        consumed = requests.get(
            self.base_url + "/api/v1/otp/next",
            params={"not_before": time.time() - 1, "timeout": 0},
            headers={"X-OTP-Token": "consumer-secret-token"},
            timeout=2,
        )
        self.assertEqual(consumed.status_code, 200)

        empty = requests.get(
            self.base_url + "/api/v1/otp/next",
            params={"not_before": time.time() - 1, "timeout": 0},
            headers={"X-OTP-Token": "consumer-secret-token"},
            timeout=2,
        )
        self.assertEqual(empty.status_code, 204)

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("relay.initialized", [record["event"] for record in records])
        self.assertIn("smsforwarder.accepted", [record["event"] for record in records])
        self.assertIn("otp.consume", [record["event"] for record in records])
        self.assertIn(
            {"event": "otp.consume", "outcome": "empty"},
            [
                {"event": record["event"], "outcome": record.get("outcome")}
                for record in records
                if record["event"] == "otp.consume"
            ],
        )
        log_text = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("246810", log_text)

    def test_audit_records_sender_rejection_without_sender_value(self):
        timestamp = str(int(time.time() * 1000))
        signature = generate_smsforwarder_signature(
            timestamp, "smsforwarder-official-secret"
        )
        response = requests.post(
            self.base_url + "/api/v1/smsforwarder",
            data={
                "from": "OTHER",
                "content": "銀行 OTP 135790",
                "timestamp": timestamp,
                "sign": signature,
            },
            timeout=2,
        )
        self.assertEqual(response.status_code, 422)

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
        ]
        rejection = next(
            record
            for record in records
            if record["event"] == "smsforwarder.rejected"
        )
        self.assertEqual(rejection["reason"], "sender_not_allowed")
        self.assertEqual(rejection["status_code"], 422)
        log_text = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("OTHER", log_text)
        self.assertNotIn("135790", log_text)


if __name__ == "__main__":
    unittest.main()
