import base64
import hashlib
import hmac
import os
import re
import socket
import threading
import time
import unittest
from urllib.parse import quote_plus
from unittest.mock import patch

import requests
import uvicorn

os.environ.setdefault("OTP_ALLOWED_SENDER_PATTERN", r"^BANK$")

from main import (
    OTPStore,
    SMSPayload,
    ServerSettings,
    create_app,
    extract_otp,
    generate_smsforwarder_signature,
    validate_sms_allowlist,
    verify_smsforwarder_signature,
)


class OTPStoreTests(unittest.TestCase):
    def test_extract_prefers_keyword_code_over_amount(self):
        self.assertEqual(extract_otp("消費金額 1234 元，您的 OTP 是 654321"), "654321")
        self.assertEqual(extract_otp("動態密碼：9876，請勿告知他人"), "9876")
        self.assertIsNone(extract_otp("交易 1234，卡末四碼 5678"))
        self.assertIsNone(extract_otp("OTP for transaction 1234, amount 5678"))
        self.assertEqual(extract_otp("交易序號 123456，驗證碼：654321"), "654321")

    def test_extracts_esun_correlation_metadata(self):
        now = time.time()
        store = OTPStore(ttl_seconds=300)

        record = store.put(
            SMSPayload(
                message=(
                    "玉山卡網路消費，新台幣 TWD 1,234 元，"
                    "網頁識別碼 test，交易驗證碼 246810"
                ),
                sender="BANK",
                request_id="request-esun-metadata",
            ),
            now=now,
        )

        self.assertEqual(record.code, "246810")
        self.assertEqual(getattr(record, "identifier", None), "TEST")
        self.assertEqual(getattr(record, "amount", None), "1234")

    def test_consume_is_fresh_and_one_time(self):
        now = time.time()
        store = OTPStore(ttl_seconds=300)
        store.put(
            SMSPayload(message="驗證碼 123456", sender="BANK", request_id="request-fresh"),
            now=now,
        )
        self.assertIsNone(store.consume(not_before=now + 1))
        record = store.consume(not_before=now - 1)
        self.assertEqual(record.code, "123456")
        self.assertIsNone(store.consume(not_before=now - 1))

    def test_relay_ingestion_time_avoids_phone_clock_skew(self):
        now = time.time()
        store = OTPStore(ttl_seconds=300)
        store.put(
            SMSPayload(
                message="OTP 112233",
                sender="BANK",
                request_id="request-clock-skew",
                received_at=now - 30,
            ),
            now=now,
        )
        self.assertEqual(store.consume(not_before=now - 1).code, "112233")

    def test_rejects_expired_future_and_duplicate_messages(self):
        now = time.time()
        store = OTPStore(ttl_seconds=10)
        with self.assertRaises(ValueError):
            store.put(
                SMSPayload(
                    message="OTP 123456",
                    request_id="request-old",
                    received_at=now - 11,
                ),
                now=now,
            )
        with self.assertRaises(ValueError):
            store.put(
                SMSPayload(
                    message="OTP 123456",
                    request_id="request-future",
                    received_at=now + 61,
                ),
                now=now,
            )
        payload = SMSPayload(message="OTP 123456", request_id="request-duplicate")
        store.put(payload, now=now)
        with self.assertRaises(KeyError):
            store.put(payload, now=now)


class SmsForwarderSignatureTests(unittest.TestCase):
    def test_matches_official_hmac_sha256_base64_formula(self):
        timestamp = "1700000000123"
        secret = "official-wiki-secret"
        independent = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                f"{timestamp}\n{secret}".encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        self.assertEqual(generate_smsforwarder_signature(timestamp, secret), independent)
        self.assertTrue(verify_smsforwarder_signature(timestamp, independent, secret))
        self.assertTrue(
            verify_smsforwarder_signature(timestamp, quote_plus(independent), secret)
        )
        self.assertFalse(verify_smsforwarder_signature(timestamp, "wrong", secret))


class OTPAllowlistTests(unittest.TestCase):
    def test_message_only_accepts_matching_body_from_any_sender(self):
        message_regex = re.compile(r"玉山卡網路消費")

        self.assertIsNone(
            validate_sms_allowlist(
                "玉山卡網路消費，交易驗證碼 338228",
                "0911111111",
                message_regex,
                None,
            )
        )

    def test_sender_only_accepts_matching_sender_regardless_of_body(self):
        sender_regex = re.compile(r"^BANK$")

        self.assertIsNone(
            validate_sms_allowlist("unrelated body", "BANK", None, sender_regex)
        )

    def test_both_filters_require_both_matches(self):
        message_regex = re.compile(r"玉山卡網路消費")
        sender_regex = re.compile(r"^BANK$")

        self.assertEqual(
            validate_sms_allowlist(
                "玉山卡網路消費，交易驗證碼 338228",
                "OTHER",
                message_regex,
                sender_regex,
            ),
            "sender_not_allowed",
        )

    def test_message_failure_returns_message_rejection_reason(self):
        self.assertEqual(
            validate_sms_allowlist(
                "一般通知",
                "BANK",
                re.compile(r"玉山卡網路消費"),
                re.compile(r"^BANK$"),
            ),
            "message_not_allowed",
        )


class OTPConfigurationTests(unittest.TestCase):
    def _settings(self, **overrides):
        values = {
            "upload_token": "upload-token",
            "consumer_token": "consumer-token",
            "smsforwarder_secret": "smsforwarder-secret",
        }
        values.update(overrides)
        return ServerSettings(**values)

    def test_from_env_loads_message_allowlist_pattern(self):
        with patch.dict(
            os.environ,
            {
                "OTP_ALLOWED_MESSAGE_PATTERN": r"玉山卡網路消費",
                "OTP_ALLOWED_SENDER_PATTERN": "",
            },
            clear=False,
        ):
            settings = ServerSettings.from_env()

        self.assertEqual(settings.allowed_message_pattern, r"玉山卡網路消費")
        self.assertEqual(settings.allowed_sender_pattern, "")

    def test_create_app_requires_at_least_one_sms_allowlist(self):
        with self.assertRaisesRegex(
            ValueError,
            r"At least one SMS allowlist must be configured: "
            r"OTP_ALLOWED_MESSAGE_PATTERN or OTP_ALLOWED_SENDER_PATTERN",
        ):
            create_app(self._settings())

    def test_create_app_rejects_invalid_message_regex(self):
        with self.assertRaisesRegex(ValueError, "OTP_ALLOWED_MESSAGE_PATTERN"):
            create_app(
                self._settings(
                    allowed_message_pattern="[",
                    allowed_sender_pattern="",
                )
            )

    def test_create_app_rejects_invalid_sender_regex(self):
        with self.assertRaisesRegex(ValueError, "OTP_ALLOWED_SENDER_PATTERN"):
            create_app(
                self._settings(
                    allowed_message_pattern="",
                    allowed_sender_pattern="[",
                )
            )


class OTPApiIntegrationTests(unittest.TestCase):
    smsforwarder_secret = "smsforwarder-official-secret"
    timestamp_sequence = 0

    @classmethod
    def setUpClass(cls):
        settings = ServerSettings(
            upload_token="upload-secret-token",
            consumer_token="consumer-secret-token",
            smsforwarder_secret=cls.smsforwarder_secret,
            otp_ttl_seconds=300,
            max_long_poll_seconds=2,
            smsforwarder_max_skew_seconds=300,
            allowed_sender_pattern=r"^BANK$",
        )
        app = create_app(settings=settings)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="critical")
        )
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                response = requests.get(cls.base_url + "/health", timeout=0.2)
                if response.status_code == 200:
                    assert response.json()["smsforwarder_configured"] is True
                    return
            except requests.RequestException:
                time.sleep(0.05)
        raise RuntimeError("test API server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    @classmethod
    def fresh_timestamp_ms(cls):
        cls.timestamp_sequence += 1
        return str(int(time.time() * 1000) + cls.timestamp_sequence)

    def post_sms(self, request_id, **overrides):
        payload = {
            "message": "銀行 OTP 246810",
            "sender": "BANK",
            "request_id": request_id,
            "received_at": time.time(),
        }
        payload.update(overrides)
        return requests.post(
            self.base_url + "/api/v1/otp",
            json=payload,
            headers={"X-OTP-Token": "upload-secret-token"},
            timeout=2,
        )

    def post_smsforwarder(
        self,
        *,
        timestamp_ms=None,
        sender="BANK",
        content="銀行 OTP 246810",
        org_content=None,
        signature=None,
        as_json=False,
    ):
        timestamp_ms = timestamp_ms or self.fresh_timestamp_ms()
        signature = signature or generate_smsforwarder_signature(
            timestamp_ms, self.smsforwarder_secret
        )
        payload = {
            "from": sender,
            "content": content,
            "timestamp": timestamp_ms,
            "sign": quote_plus(signature) if as_json else signature,
        }
        if org_content is not None:
            payload["org_content"] = org_content
        kwargs = {"json": payload} if as_json else {"data": payload}
        return requests.post(
            self.base_url + "/api/v1/smsforwarder",
            timeout=2,
            **kwargs,
        )

    def consume(self, not_before, token="consumer-secret-token", timeout=0):
        return requests.get(
            self.base_url + "/api/v1/otp/next",
            params={"not_before": not_before, "timeout": timeout},
            headers={"X-OTP-Token": token},
            timeout=timeout + 2,
        )

    def test_server_time_requires_consumer_token(self):
        unauthorized = requests.get(self.base_url + "/api/v1/time", timeout=2)
        self.assertEqual(unauthorized.status_code, 401)
        response = requests.get(
            self.base_url + "/api/v1/time",
            headers={"X-OTP-Token": "consumer-secret-token"},
            timeout=2,
        )
        self.assertEqual(response.status_code, 200)
        self.assertLess(abs(response.json()["server_time"] - time.time()), 2)

    def test_auth_sender_dedup_and_consume_once(self):
        unauthorized = requests.post(
            self.base_url + "/api/v1/otp",
            json={"message": "OTP 111111", "request_id": "request-no-auth"},
            timeout=2,
        )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(self.consume(time.time(), token="wrong").status_code, 401)

        sender_rejected = self.post_sms("request-bad-sender", sender="OTHER")
        self.assertEqual(sender_rejected.status_code, 422)

        not_before = time.time() - 1
        accepted = self.post_sms("request-api-once")
        self.assertEqual(accepted.status_code, 202)
        self.assertNotIn("code", accepted.json())
        self.assertEqual(self.post_sms("request-api-once").status_code, 409)

        consumed = self.consume(not_before)
        self.assertEqual(consumed.status_code, 200)
        self.assertEqual(consumed.json()["code"], "246810")
        self.assertEqual(self.consume(not_before).status_code, 204)

    def test_smsforwarder_default_form_is_signed_and_consumed_once(self):
        not_before = time.time() - 1
        timestamp = self.fresh_timestamp_ms()
        first = self.post_smsforwarder(timestamp_ms=timestamp)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertFalse(first.json()["duplicate"])
        self.assertNotIn("code", first.json())

        replay = self.post_smsforwarder(timestamp_ms=timestamp)
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertTrue(replay.json()["duplicate"])

        consumed = self.consume(not_before)
        self.assertEqual(consumed.status_code, 200)
        self.assertEqual(consumed.json()["code"], "246810")
        self.assertEqual(consumed.json()["sender"], "BANK")
        self.assertEqual(self.consume(not_before).status_code, 204)

    def test_smsforwarder_custom_json_prefers_original_content_and_encoded_sign(self):
        not_before = time.time() - 1
        response = self.post_smsforwarder(
            content="模板加工內容：交易 1234，卡末四碼 5678",
            org_content="您的驗證碼：975310，請勿告知他人",
            as_json=True,
        )
        self.assertEqual(response.status_code, 202, response.text)
        consumed = self.consume(not_before)
        self.assertEqual(consumed.status_code, 200)
        self.assertEqual(consumed.json()["code"], "975310")

    def test_smsforwarder_returns_esun_correlation_metadata(self):
        not_before = time.time() - 1
        response = self.post_smsforwarder(
            content=(
                "玉山卡網路消費，新台幣 TWD 1,234 元，"
                "網頁識別碼 test，交易驗證碼 246810"
            )
        )
        self.assertEqual(response.status_code, 202, response.text)

        consumed = self.consume(not_before)

        self.assertEqual(consumed.status_code, 200)
        self.assertEqual(consumed.json()["code"], "246810")
        self.assertEqual(consumed.json().get("identifier"), "TEST")
        self.assertEqual(consumed.json().get("amount"), "1234")

    def test_smsforwarder_rejects_bad_signature_expired_time_and_sender(self):
        bad_signature = self.post_smsforwarder(signature="not-a-valid-signature")
        self.assertEqual(bad_signature.status_code, 401)

        old_timestamp = str(int((time.time() - 301) * 1000))
        expired = self.post_smsforwarder(timestamp_ms=old_timestamp)
        self.assertEqual(expired.status_code, 401)

        wrong_sender = self.post_smsforwarder(sender="OTHER")
        self.assertEqual(wrong_sender.status_code, 422)

    def test_long_poll_wakes_when_sms_arrives(self):
        not_before = time.time()
        result = {}

        def wait_for_otp():
            result["response"] = self.consume(not_before, timeout=2)

        waiter = threading.Thread(target=wait_for_otp)
        waiter.start()
        time.sleep(0.2)
        self.assertEqual(self.post_smsforwarder().status_code, 202)
        waiter.join(timeout=4)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(result["response"].status_code, 200)
        self.assertEqual(result["response"].json()["code"], "246810")


class MessageAllowlistApiIntegrationTests(unittest.TestCase):
    smsforwarder_secret = "message-filter-secret"
    message_pattern = (
        r"(?s)(?=.*?玉山卡網路消費)(?=.*網頁識別碼)"
        r"(?=.*交易驗證碼\s*[:：]?\s*\d{6})"
    )
    valid_message = (
        "玉山卡網路消費，新台幣 TWD 137 元，"
        "網頁識別碼 WDCT，交易驗證碼 338228"
    )
    timestamp_sequence = 0

    @classmethod
    def setUpClass(cls):
        settings = ServerSettings(
            upload_token="upload-secret-token",
            consumer_token="consumer-secret-token",
            smsforwarder_secret=cls.smsforwarder_secret,
            otp_ttl_seconds=300,
            max_long_poll_seconds=2,
            smsforwarder_max_skew_seconds=300,
            allowed_message_pattern=cls.message_pattern,
            allowed_sender_pattern="",
        )
        app = create_app(settings=settings)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="critical")
        )
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if requests.get(cls.base_url + "/health", timeout=0.2).status_code == 200:
                    return
            except requests.RequestException:
                time.sleep(0.05)
        raise RuntimeError("message allowlist test API server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    @classmethod
    def fresh_timestamp_ms(cls):
        cls.timestamp_sequence += 1
        return str(int(time.time() * 1000) + cls.timestamp_sequence)

    def post_smsforwarder(
        self,
        *,
        timestamp_ms=None,
        sender="0911111111",
        content=None,
        org_content=None,
        signature=None,
        as_json=False,
    ):
        timestamp_ms = timestamp_ms or self.fresh_timestamp_ms()
        signature = signature or generate_smsforwarder_signature(
            timestamp_ms, self.smsforwarder_secret
        )
        payload = {
            "from": sender,
            "content": content if content is not None else self.valid_message,
            "timestamp": timestamp_ms,
            "sign": quote_plus(signature) if as_json else signature,
        }
        if org_content is not None:
            payload["org_content"] = org_content
        kwargs = {"json": payload} if as_json else {"data": payload}
        return requests.post(
            self.base_url + "/api/v1/smsforwarder", timeout=2, **kwargs
        )

    def consume(self, not_before, timeout=0):
        return requests.get(
            self.base_url + "/api/v1/otp/next",
            params={"not_before": not_before, "timeout": timeout},
            headers={"X-OTP-Token": "consumer-secret-token"},
            timeout=timeout + 2,
        )

    def test_valid_esun_message_accepts_different_senders(self):
        not_before = time.time() - 1

        first = self.post_smsforwarder(sender="0911111111")
        second = self.post_smsforwarder(sender="0922222222")

        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        consumed = [self.consume(not_before), self.consume(not_before)]
        self.assertEqual([response.status_code for response in consumed], [200, 200])
        self.assertEqual({response.json()["code"] for response in consumed}, {"338228"})
        self.assertEqual(
            {response.json()["identifier"] for response in consumed}, {"WDCT"}
        )
        self.assertEqual({response.json()["amount"] for response in consumed}, {"137"})

    def test_org_content_is_the_message_used_for_allowlist_and_parser(self):
        response = self.post_smsforwarder(
            content="模板加工內容：一般通知 123456",
            org_content=self.valid_message,
            as_json=True,
        )

        self.assertEqual(response.status_code, 202, response.text)
        consumed = self.consume(time.time() - 1)
        self.assertEqual(consumed.status_code, 200)
        self.assertEqual(consumed.json()["code"], "338228")

    def test_unrelated_sms_is_rejected_by_message_allowlist(self):
        response = self.post_smsforwarder(content="一般通知 123456")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "SMS content is not allowed")

    def test_generic_otp_sms_is_rejected_by_message_allowlist(self):
        response = self.post_smsforwarder(content="OTP 246810")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "SMS content is not allowed")

    def test_invalid_signature_is_rejected_before_message_allowlist(self):
        response = self.post_smsforwarder(
            content=self.valid_message,
            signature="invalid-signature",
        )

        self.assertEqual(response.status_code, 401)

    def test_expired_timestamp_is_rejected_before_message_allowlist(self):
        timestamp_ms = str(int((time.time() - 301) * 1000))
        response = self.post_smsforwarder(
            timestamp_ms=timestamp_ms,
            content=self.valid_message,
        )

        self.assertEqual(response.status_code, 401)


class BothAllowlistApiIntegrationTests(unittest.TestCase):
    smsforwarder_secret = "both-filter-secret"
    message = (
        "玉山卡網路消費，新台幣 TWD 137 元，"
        "網頁識別碼 WDCT，交易驗證碼 338228"
    )

    @classmethod
    def setUpClass(cls):
        settings = ServerSettings(
            upload_token="upload-secret-token",
            consumer_token="consumer-secret-token",
            smsforwarder_secret=cls.smsforwarder_secret,
            otp_ttl_seconds=300,
            max_long_poll_seconds=2,
            smsforwarder_max_skew_seconds=300,
            allowed_message_pattern=r"玉山卡網路消費",
            allowed_sender_pattern=r"^BANK$",
        )
        app = create_app(settings=settings)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="critical")
        )
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if requests.get(cls.base_url + "/health", timeout=0.2).status_code == 200:
                    return
            except requests.RequestException:
                time.sleep(0.05)
        raise RuntimeError("both allowlists test API server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def test_sender_filter_rejects_other_sender_when_message_matches(self):
        timestamp_ms = str(int(time.time() * 1000))
        signature = generate_smsforwarder_signature(timestamp_ms, self.smsforwarder_secret)
        response = requests.post(
            self.base_url + "/api/v1/smsforwarder",
            data={
                "from": "OTHER",
                "content": self.message,
                "timestamp": timestamp_ms,
                "sign": signature,
            },
            timeout=2,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Sender is not allowed")


if __name__ == "__main__":
    unittest.main()
