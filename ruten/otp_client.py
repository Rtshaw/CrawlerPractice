"""Client for consuming a fresh one-time code from the OTP relay."""

from __future__ import annotations

import time
from typing import Any, Optional

import requests


class OTPRelayError(RuntimeError):
    """Raised when the OTP relay is unavailable or returns invalid data."""


class OTPTimeoutError(TimeoutError):
    """Raised when no fresh OTP arrives before the deadline."""


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


    def wait_for_code(self, *, not_before: float, timeout_seconds: int = 180) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_error: Optional[Exception] = None

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
                code = str(response.json()["code"])
            except (KeyError, TypeError, ValueError) as exc:
                raise OTPRelayError("OTP relay returned an invalid response") from exc
            if not code.isdigit() or not 4 <= len(code) <= 8:
                raise OTPRelayError("OTP relay returned an invalid code format")
            return code

        detail = f": {last_error}" if last_error else ""
        raise OTPTimeoutError(f"No fresh OTP received within {timeout_seconds} seconds{detail}")
