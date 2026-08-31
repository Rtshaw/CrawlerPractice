import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO

from otp_client import OTPRelayClient, OTPRelayError


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class OTPRelayClientTests(unittest.TestCase):
    def test_returns_structured_esun_event(self):
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "code": "135790",
                        "identifier": "TEST",
                        "amount": "1234",
                        "sender": "BANK",
                        "received_at": 1700000000.25,
                    },
                )
            ]
        )
        client = OTPRelayClient(
            "https://otp.example.com/",
            "consumer-token",
            session=session,
            long_poll_seconds=1,
        )

        event = client.wait_for_event(not_before=1234.5, timeout_seconds=3)

        self.assertEqual(event.code, "135790")
        self.assertEqual(event.identifier, "TEST")
        self.assertEqual(event.amount, Decimal("1234"))
        self.assertEqual(event.sender, "BANK")
        self.assertEqual(event.received_at, 1700000000.25)

    def test_reports_sanitized_status_while_waiting_for_correlated_event(self):
        session = FakeSession(
            [
                FakeResponse(204),
                FakeResponse(
                    200,
                    {
                        "code": "111222",
                        "sender": "BANK",
                        "received_at": 1700000000.0,
                    },
                ),
                FakeResponse(
                    200,
                    {
                        "code": "135790",
                        "identifier": "TEST",
                        "amount": "1234",
                        "sender": "BANK",
                        "received_at": 1700000000.25,
                    },
                ),
            ]
        )
        client = OTPRelayClient(
            "https://otp.example.com/",
            "consumer-token",
            session=session,
            long_poll_seconds=1,
        )

        output = StringIO()
        with redirect_stdout(output):
            event = client.wait_for_event(
                not_before=1234.5,
                timeout_seconds=3,
                require_correlation=True,
            )

        self.assertEqual(event.code, "135790")
        self.assertEqual(event.identifier, "TEST")
        self.assertEqual(event.amount, Decimal("1234"))
        self.assertEqual(len(session.calls), 3)
        log_output = output.getvalue()
        self.assertIn("OTP relay 開始等待簡訊轉發事件", log_output)
        self.assertIn("OTP relay 尚未收到新的簡訊轉發", log_output)
        self.assertIn("OTP relay 已收到簡訊轉發，但缺少交易關聯資料", log_output)
        self.assertIn("OTP relay 已收到包含交易關聯資料的簡訊轉發", log_output)
        for sensitive_value in ("111222", "135790", "TEST", "1234"):
            self.assertNotIn(sensitive_value, log_output)

    def test_waits_through_no_content_and_returns_valid_code(self):
        session = FakeSession([FakeResponse(204), FakeResponse(200, {"code": "135790"})])
        client = OTPRelayClient(
            "https://otp.example.com/",
            "consumer-token",
            session=session,
            long_poll_seconds=1,
        )
        code = client.wait_for_code(not_before=1234.5, timeout_seconds=3)
        self.assertEqual(code, "135790")
        self.assertEqual(len(session.calls), 2)
        url, options = session.calls[0]
        self.assertEqual(url, "https://otp.example.com/api/v1/otp/next")
        self.assertEqual(options["headers"]["X-OTP-Token"], "consumer-token")
        self.assertEqual(options["params"]["not_before"], "1234.500000")

    def test_gets_authenticated_relay_server_time(self):
        session = FakeSession([FakeResponse(200, {"server_time": 1700000000.25})])
        client = OTPRelayClient("https://otp.example.com", "consumer-token", session=session)
        self.assertEqual(client.get_server_time(), 1700000000.25)
        url, options = session.calls[0]
        self.assertEqual(url, "https://otp.example.com/api/v1/time")
        self.assertEqual(options["headers"]["X-OTP-Token"], "consumer-token")

    def test_rejects_auth_failure_and_invalid_code(self):
        client = OTPRelayClient(
            "https://otp.example.com", "token", session=FakeSession([FakeResponse(401)])
        )
        with self.assertRaises(OTPRelayError):
            client.wait_for_code(not_before=0, timeout_seconds=1)

        client = OTPRelayClient(
            "https://otp.example.com",
            "token",
            session=FakeSession([FakeResponse(200, {"code": "12ab"})]),
        )
        with self.assertRaises(OTPRelayError):
            client.wait_for_code(not_before=0, timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()
