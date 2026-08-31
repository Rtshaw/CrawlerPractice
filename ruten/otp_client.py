"""Client for consuming a fresh one-time code from the OTP relay."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import requests


class OTPRelayError(RuntimeError):
    """Raised when the OTP relay is unavailable or returns invalid data."""


class OTPTimeoutError(TimeoutError):
    """Raised when no fresh OTP arrives before the deadline."""


@dataclass(frozen=True)
class OTPEvent:
    code: str
    identifier: Optional[str] = None
    amount: Optional[Decimal] = None
    sender: str = ""
    received_at: float = 0.0


class OTPRelayClient:
    def __init__(
        self,
        server_url: str,
        consumer_token: str,
        *,
        session: Optional[Any] = None,
        long_poll_seconds: int = 20,
    ) -> None:
        if not server_url.strip():
            raise ValueError("OTP server URL is required")
        if not consumer_token:
            raise ValueError("OTP consumer token is required")
        base_url = server_url.rstrip("/")
        self.endpoint = base_url + "/api/v1/otp/next"
        self.time_endpoint = base_url + "/api/v1/time"
        self.consumer_token = consumer_token
        self.session = session or requests.Session()
        self.long_poll_seconds = max(1, min(int(long_poll_seconds), 30))

    def get_server_time(self) -> float:
        try:
            response = self.session.get(
                self.time_endpoint,
                headers={"X-OTP-Token": self.consumer_token},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise OTPRelayError(f"Cannot obtain relay server time: {exc}") from exc
        if response.status_code != 200:
            raise OTPRelayError(
                f"Cannot obtain relay server time (HTTP {response.status_code}); payment was not submitted"
            )
        try:
            server_time = float(response.json()["server_time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OTPRelayError("Relay returned an invalid server time") from exc
        if server_time <= 0:
            raise OTPRelayError("Relay returned an invalid server time")
        return server_time


    @staticmethod
    def _parse_event(payload: Any) -> OTPEvent:
        if not isinstance(payload, dict):
            raise OTPRelayError("OTP relay returned an invalid response")
        try:
            code = str(payload["code"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OTPRelayError("OTP relay returned an invalid response") from exc
        if not code.isdigit() or not 4 <= len(code) <= 8:
            raise OTPRelayError("OTP relay returned an invalid code format")

        identifier_value = payload.get("identifier")
        amount_value = payload.get("amount")
        if (identifier_value is None) != (amount_value is None):
            raise OTPRelayError("OTP relay returned incomplete correlation metadata")

        identifier: Optional[str] = None
        amount: Optional[Decimal] = None
        if identifier_value is not None:
            identifier = str(identifier_value).upper()
            if len(identifier) != 4 or not identifier.isascii() or not identifier.isalpha():
                raise OTPRelayError("OTP relay returned an invalid webpage identifier")
            try:
                amount = Decimal(str(amount_value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise OTPRelayError("OTP relay returned an invalid transaction amount") from exc
            if not amount.is_finite() or amount <= 0:
                raise OTPRelayError("OTP relay returned an invalid transaction amount")

        sender_value = payload.get("sender", "")
        if not isinstance(sender_value, str):
            raise OTPRelayError("OTP relay returned an invalid sender")
        try:
            received_at = float(payload.get("received_at", 0))
        except (TypeError, ValueError) as exc:
            raise OTPRelayError("OTP relay returned an invalid received_at") from exc
        if received_at < 0:
            raise OTPRelayError("OTP relay returned an invalid received_at")
        return OTPEvent(
            code=code,
            identifier=identifier,
            amount=amount,
            sender=sender_value,
            received_at=received_at,
        )

    def wait_for_event(
        self,
        *,
        not_before: float,
        timeout_seconds: int = 180,
        require_correlation: bool = False,
    ) -> OTPEvent:
        deadline = time.monotonic() + timeout_seconds
        last_error: Optional[Exception] = None
        if require_correlation:
            print("[INFO] OTP relay 開始等待簡訊轉發事件")

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            long_poll = max(0, min(self.long_poll_seconds, int(remaining)))
            if long_poll == 0 and remaining > 0:
                long_poll = 1
            try:
                response = self.session.get(
                    self.endpoint,
                    headers={"X-OTP-Token": self.consumer_token},
                    params={"not_before": f"{not_before:.6f}", "timeout": long_poll},
                    timeout=long_poll + 5,
                )
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(2, max(0, deadline - time.monotonic())))
                continue

            if response.status_code == 204:
                if require_correlation:
                    print("[INFO] OTP relay 尚未收到新的簡訊轉發，繼續等待")
                continue
            if response.status_code in (401, 403, 503):
                raise OTPRelayError(
                    f"OTP relay rejected the consumer (HTTP {response.status_code}); check server token configuration"
                )
            if response.status_code != 200:
                last_error = OTPRelayError(f"OTP relay returned HTTP {response.status_code}")
                time.sleep(min(1, max(0, deadline - time.monotonic())))
                continue

            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise OTPRelayError("OTP relay returned an invalid response") from exc
            event = self._parse_event(payload)
            if require_correlation and (
                event.identifier is None or event.amount is None
            ):
                print(
                    "[INFO] OTP relay 已收到簡訊轉發，"
                    "但缺少交易關聯資料，已忽略並繼續等待"
                )
                last_error = OTPRelayError(
                    "OTP relay returned an event without correlation metadata"
                )
                continue
            if require_correlation:
                print("[INFO] OTP relay 已收到包含交易關聯資料的簡訊轉發")
            return event

        detail = f": {last_error}" if last_error else ""
        raise OTPTimeoutError(f"No fresh OTP received within {timeout_seconds} seconds{detail}")

    def wait_for_code(self, *, not_before: float, timeout_seconds: int = 180) -> str:
        """Backward-compatible code-only API for non-correlated consumers."""
        return self.wait_for_event(
            not_before=not_before,
            timeout_seconds=timeout_seconds,
        ).code
