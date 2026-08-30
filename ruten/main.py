"""One-time password relay used by pppscn/SmsForwarder and fee.py.

Run with:
    uvicorn main:app --host 127.0.0.1 --port 8000

Set SMSFORWARDER_SECRET and OTP_CONSUMER_TOKEN before exposing the service, and
put it behind HTTPS. The legacy JSON upload endpoint additionally supports
OTP_UPLOAD_TOKEN for manual integrations.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator


OTP_KEYWORD_PATTERN = re.compile(
    r"(?:驗證碼|動態密碼|一次性密碼|OTP|verification\s*code|security\s*code)"
    r"(?:\s*(?:為|是|is|[:：#=\-])\s*){0,3}([0-9]{4,8})(?![0-9])",
    re.IGNORECASE,
)
SIX_DIGIT_PATTERN = re.compile(r"(?<![0-9])([0-9]{6})(?![0-9])")
GENERIC_CODE_PATTERN = re.compile(r"(?<![0-9])([0-9]{4,8})(?![0-9])")


def extract_otp(message: str) -> Optional[str]:
    """Extract an OTP while avoiding arbitrary numbers where possible."""
    keyword_match = OTP_KEYWORD_PATTERN.search(message)
    if keyword_match:
        return keyword_match.group(1)

    six_digit_codes = SIX_DIGIT_PATTERN.findall(message)
    if len(six_digit_codes) == 1:
        return six_digit_codes[0]

    generic_codes = GENERIC_CODE_PATTERN.findall(message)
    if len(generic_codes) == 1:
        return generic_codes[0]
    return None


def generate_smsforwarder_signature(timestamp_ms: str, secret: str) -> str:
    """Return the Base64 HMAC value defined by the SmsForwarder Wiki.

    SmsForwarder URL-encodes this value on the wire. Request parsing may already
    have decoded it, so verification compares the normalized Base64 value.
    """
    message = f"{timestamp_ms}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_smsforwarder_signature(timestamp_ms: str, signature: str, secret: str) -> bool:
    if not secret or not timestamp_ms or not signature:
        return False
    expected = generate_smsforwarder_signature(timestamp_ms, secret)
    candidates = {
        signature,
        unquote(signature),
        signature.replace(" ", "+"),
        unquote(signature).replace(" ", "+"),
    }
    return any(secrets.compare_digest(candidate, expected) for candidate in candidates)


@dataclass(frozen=True)
class ServerSettings:
    upload_token: str
    consumer_token: str
    smsforwarder_secret: str = ""
    otp_ttl_seconds: int = 300
    max_long_poll_seconds: int = 30
    smsforwarder_max_skew_seconds: int = 300
    allowed_sender_pattern: str = ""

    @classmethod
    def from_env(cls) -> "ServerSettings":
        return cls(
            upload_token=os.environ.get("OTP_UPLOAD_TOKEN", ""),
            consumer_token=os.environ.get("OTP_CONSUMER_TOKEN", ""),
            smsforwarder_secret=os.environ.get("SMSFORWARDER_SECRET", ""),
            otp_ttl_seconds=int(os.environ.get("OTP_TTL_SECONDS", "300")),
            max_long_poll_seconds=int(os.environ.get("OTP_MAX_LONG_POLL_SECONDS", "30")),
            smsforwarder_max_skew_seconds=int(
                os.environ.get("SMSFORWARDER_MAX_SKEW_SECONDS", "300")
            ),
            allowed_sender_pattern=os.environ.get("OTP_ALLOWED_SENDER_PATTERN", ""),
        )


class SMSPayload(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    sender: str = Field(default="", max_length=100)
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=128)
    received_at: Optional[float] = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class SMSAccepted(BaseModel):
    accepted: bool
    request_id: str
    expires_at: float
    duplicate: bool = False


class OTPResponse(BaseModel):
    code: str
    sender: str
    received_at: float


@dataclass
class OTPRecord:
    code: str
    sender: str
    request_id: str
    received_at: float
    created_at: float
    expires_at: float


class OTPStore:
    """Thread-safe in-memory OTP queue with expiry, deduplication, and consume-on-read."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self._records: List[OTPRecord] = []
        self._seen_requests: Dict[str, float] = {}
        self._condition = threading.Condition()

    def _purge(self, now: float) -> None:
        self._records = [record for record in self._records if record.expires_at > now]
        self._seen_requests = {
            request_id: expires_at
            for request_id, expires_at in self._seen_requests.items()
            if expires_at > now
        }

    def put(self, payload: SMSPayload, now: Optional[float] = None) -> OTPRecord:
        current_time = time.time() if now is None else now
        received_at = payload.received_at if payload.received_at is not None else current_time
        if received_at < current_time - self.ttl_seconds:
            raise ValueError("SMS is older than the configured OTP lifetime")
        if received_at > current_time + 60:
            raise ValueError("SMS received_at is too far in the future")

        code = extract_otp(payload.message)
        if code is None:
            raise ValueError("No unambiguous 4-8 digit OTP found in SMS")

        with self._condition:
            self._purge(current_time)
            if payload.request_id in self._seen_requests:
                raise KeyError("request_id has already been accepted")
            record = OTPRecord(
                code=code,
                sender=payload.sender,
                request_id=payload.request_id,
                received_at=received_at,
                created_at=current_time,
                expires_at=current_time + self.ttl_seconds,
            )
            self._records.append(record)
            self._seen_requests[payload.request_id] = record.expires_at
            self._condition.notify_all()
            return record

    def consume(self, not_before: float = 0, timeout: float = 0) -> Optional[OTPRecord]:
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            while True:
                self._purge(time.time())
                for index, record in enumerate(self._records):
                    # Freshness is based on relay ingestion time. Phone clocks are only
                    # used for rejecting clearly stale/future uploads in put().
                    if record.created_at >= not_before:
                        return self._records.pop(index)

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)


class TokenAuthorizer:
    def __init__(self, settings: ServerSettings) -> None:
        self.settings = settings

    @staticmethod
    def _check(actual: Optional[str], expected: str, purpose: str) -> None:
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{purpose} token is not configured on server",
            )
        if actual is None or not secrets.compare_digest(actual, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    def upload(self, token: Optional[str]) -> None:
        self._check(token, self.settings.upload_token, "Upload")

    def consume(self, token: Optional[str]) -> None:
        self._check(token, self.settings.consumer_token, "Consumer")


def create_app(
    settings: Optional[ServerSettings] = None,
    store: Optional[OTPStore] = None,
) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    store = store or OTPStore(settings.otp_ttl_seconds)
    auth = TokenAuthorizer(settings)
    sender_regex = re.compile(settings.allowed_sender_pattern, re.IGNORECASE) if settings.allowed_sender_pattern else None

    application = FastAPI(title="Ruten OTP Relay", version="1.0.0")
    application.state.settings = settings
    application.state.otp_store = store

    @application.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "upload_configured": bool(settings.upload_token),
            "smsforwarder_configured": bool(settings.smsforwarder_secret),
            "consumer_configured": bool(settings.consumer_token),
        }

    @application.post(
        "/api/v1/otp",
        response_model=SMSAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def receive_sms(
        payload: SMSPayload,
        x_otp_token: Optional[str] = Header(default=None),
    ) -> SMSAccepted:
        auth.upload(x_otp_token)
        if sender_regex and not sender_regex.search(payload.sender):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Sender is not allowed")
        try:
            record = store.put(payload)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return SMSAccepted(accepted=True, request_id=record.request_id, expires_at=record.expires_at)

    @application.post(
        "/api/v1/smsforwarder",
        response_model=SMSAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def receive_smsforwarder(request: Request) -> SMSAccepted:
        if not settings.smsforwarder_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SmsForwarder secret is not configured on server",
            )

        content_type = request.headers.get("content-type", "").lower()
        try:
            if "application/json" in content_type:
                raw_data = await request.json()
                if not isinstance(raw_data, dict):
                    raise ValueError("JSON payload must be an object")
                data = {str(key): str(value) for key, value in raw_data.items() if value is not None}
            elif "application/x-www-form-urlencoded" in content_type or not content_type:
                body = (await request.body()).decode("utf-8")
                parsed = parse_qs(body, keep_blank_values=True, strict_parsing=False)
                data = {key: values[-1] for key, values in parsed.items() if values}
            else:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="SmsForwarder must send JSON or application/x-www-form-urlencoded",
                )
        except HTTPException:
            raise
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook body") from exc

        sender = data.get("from", "")
        message = data.get("org_content") or data.get("content") or data.get("msg") or ""
        timestamp_ms = data.get("timestamp", "")
        signature = data.get("sign", "")
        if not sender or not message or not timestamp_ms or not signature:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Required fields: from, content or org_content, timestamp, sign",
            )
        try:
            timestamp_value = int(timestamp_ms)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="timestamp must be Unix epoch milliseconds",
            ) from exc

        now = time.time()
        if abs(now - timestamp_value / 1000.0) > settings.smsforwarder_max_skew_seconds:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook timestamp expired")
        if not verify_smsforwarder_signature(
            timestamp_ms, signature, settings.smsforwarder_secret
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
        if sender_regex and not sender_regex.search(sender):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Sender is not allowed",
            )

        expected_signature = generate_smsforwarder_signature(
            timestamp_ms, settings.smsforwarder_secret
        )
        request_id = "smsf-" + hashlib.sha256(
            f"{timestamp_ms}\n{expected_signature}".encode("utf-8")
        ).hexdigest()
        try:
            payload = SMSPayload(
                message=message,
                sender=sender,
                request_id=request_id,
                received_at=timestamp_value / 1000.0,
            )
            record = store.put(payload, now=now)
        except KeyError:
            # SmsForwarder may retry on network uncertainty. A signed replay of
            # the same timestamp is idempotently acknowledged to stop retries.
            return SMSAccepted(
                accepted=True,
                request_id=request_id,
                expires_at=now + settings.otp_ttl_seconds,
                duplicate=True,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        return SMSAccepted(
            accepted=True,
            request_id=record.request_id,
            expires_at=record.expires_at,
        )

    @application.get("/api/v1/time")
    def get_server_time(x_otp_token: Optional[str] = Header(default=None)) -> dict:
        auth.consume(x_otp_token)
        return {"server_time": time.time()}

    @application.get("/api/v1/otp/next", response_model=OTPResponse)
    def consume_otp(
        x_otp_token: Optional[str] = Header(default=None),
        not_before: float = Query(default=0, ge=0),
        timeout: int = Query(default=0, ge=0),
    ):
        auth.consume(x_otp_token)
        record = store.consume(
            not_before=not_before,
            timeout=min(timeout, settings.max_long_poll_seconds),
        )
        if record is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return OTPResponse(code=record.code, sender=record.sender, received_at=record.received_at)

    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("OTP_HOST", "127.0.0.1"), port=int(os.environ.get("OTP_PORT", "8000")))
