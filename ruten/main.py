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
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from audit_log import audit_event, configure_audit_logger_from_env


OTP_KEYWORD_PATTERN = re.compile(
    r"(?:驗證碼|動態密碼|一次性密碼|OTP|verification\s*code|security\s*code)"
    r"(?:\s*(?:為|是|is|[:：#=\-])\s*){0,3}([0-9]{4,8})(?![0-9])",
    re.IGNORECASE,
)
SIX_DIGIT_PATTERN = re.compile(r"(?<![0-9])([0-9]{6})(?![0-9])")
GENERIC_CODE_PATTERN = re.compile(r"(?<![0-9])([0-9]{4,8})(?![0-9])")
ESUN_REQUIRED_SMS_MARKERS = ("玉山卡網路消費", "網頁識別碼", "交易驗證碼")
ESUN_AMOUNT_PATTERN = re.compile(
    r"新台幣\s*TWD\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元",
    re.IGNORECASE,
)
ESUN_IDENTIFIER_PATTERN = re.compile(r"網頁識別碼\s*([A-Za-z]{4})(?![A-Za-z])")
ESUN_OTP_PATTERN = re.compile(r"交易驗證碼\s*([0-9]{6})(?![0-9])")


@dataclass(frozen=True)
class ParsedOTPEvent:
    code: str
    identifier: Optional[str] = None
    amount: Optional[str] = None


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


def extract_otp_event(message: str) -> Optional[ParsedOTPEvent]:
    """Extract an OTP plus strict E.Sun correlation metadata when present."""
    if any(marker in message for marker in ESUN_REQUIRED_SMS_MARKERS):
        if not all(marker in message for marker in ESUN_REQUIRED_SMS_MARKERS):
            return None
        amount_matches = ESUN_AMOUNT_PATTERN.findall(message)
        identifier_matches = ESUN_IDENTIFIER_PATTERN.findall(message)
        code_matches = ESUN_OTP_PATTERN.findall(message)
        if not (
            len(amount_matches) == 1
            and len(identifier_matches) == 1
            and len(code_matches) == 1
        ):
            return None
        try:
            amount = Decimal(amount_matches[0].replace(",", ""))
        except InvalidOperation:
            return None
        if not amount.is_finite() or amount <= 0:
            return None
        normalized_amount = format(amount.normalize(), "f")
        return ParsedOTPEvent(
            code=code_matches[0],
            identifier=identifier_matches[0].upper(),
            amount=normalized_amount,
        )

    code = extract_otp(message)
    return ParsedOTPEvent(code=code) if code is not None else None


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


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _sender_audit_fields(sender: str) -> Dict[str, object]:
    return {
        "sender_fingerprint": _fingerprint(sender),
        "sender_length": len(sender),
    }


def _store_rejection_reason(exc: ValueError) -> str:
    message = str(exc)
    if "older" in message:
        return "sms_too_old"
    if "future" in message:
        return "sms_timestamp_in_future"
    if "No unambiguous" in message:
        return "otp_not_unambiguous"
    return "invalid_sms"


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
    identifier: Optional[str] = None
    amount: Optional[str] = None


@dataclass
class OTPRecord:
    code: str
    sender: str
    request_id: str
    received_at: float
    created_at: float
    expires_at: float
    identifier: Optional[str] = None
    amount: Optional[str] = None


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

        event = extract_otp_event(payload.message)
        if event is None:
            raise ValueError("No unambiguous 4-8 digit OTP found in SMS")

        with self._condition:
            self._purge(current_time)
            if payload.request_id in self._seen_requests:
                raise KeyError("request_id has already been accepted")
            record = OTPRecord(
                code=event.code,
                sender=payload.sender,
                request_id=payload.request_id,
                received_at=received_at,
                created_at=current_time,
                expires_at=current_time + self.ttl_seconds,
                identifier=event.identifier,
                amount=event.amount,
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
    audit_logger: Optional[logging.Logger] = None,
) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    store = store or OTPStore(settings.otp_ttl_seconds)
    auth = TokenAuthorizer(settings)
    sender_regex = re.compile(settings.allowed_sender_pattern, re.IGNORECASE) if settings.allowed_sender_pattern else None
    audit_logger = audit_logger or configure_audit_logger_from_env()

    application = FastAPI(title="Ruten OTP Relay", version="1.0.0")
    application.state.settings = settings
    application.state.otp_store = store
    application.state.audit_logger = audit_logger
    audit_event(
        audit_logger,
        "relay.initialized",
        otp_ttl_seconds=settings.otp_ttl_seconds,
        max_long_poll_seconds=settings.max_long_poll_seconds,
        smsforwarder_max_skew_seconds=settings.smsforwarder_max_skew_seconds,
        sender_filter_configured=sender_regex is not None,
        consumer_configured=bool(settings.consumer_token),
    )

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
        request_started = time.monotonic()
        content_type = request.headers.get("content-type", "").lower()
        audit_event(
            audit_logger,
            "smsforwarder.request",
            content_type=content_type.split(";", 1)[0] or "missing",
        )
        if not settings.smsforwarder_secret:
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason="secret_not_configured",
                status_code=503,
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SmsForwarder secret is not configured on server",
            )

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
                audit_event(
                    audit_logger,
                    "smsforwarder.rejected",
                    reason="unsupported_content_type",
                    status_code=415,
                    processing_ms=round((time.monotonic() - request_started) * 1000, 2),
                )
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="SmsForwarder must send JSON or application/x-www-form-urlencoded",
                )
        except HTTPException:
            raise
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason="invalid_body",
                status_code=400,
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook body") from exc

        sender = data.get("from", "")
        message = data.get("org_content") or data.get("content") or data.get("msg") or ""
        timestamp_ms = data.get("timestamp", "")
        signature = data.get("sign", "")
        if not sender or not message or not timestamp_ms or not signature:
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason="missing_fields",
                status_code=422,
                has_sender=bool(sender),
                has_message=bool(message),
                has_timestamp=bool(timestamp_ms),
                has_signature=bool(signature),
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Required fields: from, content or org_content, timestamp, sign",
            )
        try:
            timestamp_value = int(timestamp_ms)
        except ValueError as exc:
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason="timestamp_invalid",
                status_code=422,
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="timestamp must be Unix epoch milliseconds",
            ) from exc

        now = time.time()
        skew_seconds = abs(now - timestamp_value / 1000.0)
        if skew_seconds > settings.smsforwarder_max_skew_seconds:
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason="timestamp_expired",
                status_code=401,
                skew_seconds=round(skew_seconds, 3),
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook timestamp expired")
        if not verify_smsforwarder_signature(
            timestamp_ms, signature, settings.smsforwarder_secret
        ):
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason="signature_invalid",
                status_code=401,
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
        if sender_regex and not sender_regex.search(sender):
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason="sender_not_allowed",
                status_code=422,
                **_sender_audit_fields(sender),
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
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
            audit_event(
                audit_logger,
                "smsforwarder.duplicate",
                status_code=202,
                request_fingerprint=_fingerprint(request_id),
                **_sender_audit_fields(sender),
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            return SMSAccepted(
                accepted=True,
                request_id=request_id,
                expires_at=now + settings.otp_ttl_seconds,
                duplicate=True,
            )
        except ValueError as exc:
            audit_event(
                audit_logger,
                "smsforwarder.rejected",
                reason=_store_rejection_reason(exc),
                status_code=422,
                request_fingerprint=_fingerprint(request_id),
                **_sender_audit_fields(sender),
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        audit_event(
            audit_logger,
            "smsforwarder.accepted",
            status_code=202,
            request_fingerprint=_fingerprint(request_id),
            **_sender_audit_fields(sender),
            correlated=record.identifier is not None and record.amount is not None,
            received_age_seconds=round(now - record.received_at, 3),
            processing_ms=round((time.monotonic() - request_started) * 1000, 2),
        )
        return SMSAccepted(
            accepted=True,
            request_id=record.request_id,
            expires_at=record.expires_at,
        )

    @application.get("/api/v1/time")
    def get_server_time(x_otp_token: Optional[str] = Header(default=None)) -> dict:
        auth.consume(x_otp_token)
        audit_event(audit_logger, "otp.server_time", status_code=200)
        return {"server_time": time.time()}

    @application.get("/api/v1/otp/next", response_model=OTPResponse)
    def consume_otp(
        x_otp_token: Optional[str] = Header(default=None),
        not_before: float = Query(default=0, ge=0),
        timeout: int = Query(default=0, ge=0),
    ):
        request_started = time.monotonic()
        try:
            auth.consume(x_otp_token)
        except HTTPException as exc:
            audit_event(
                audit_logger,
                "otp.consume.rejected",
                status_code=exc.status_code,
                reason="consumer_auth",
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            raise
        record = store.consume(
            not_before=not_before,
            timeout=min(timeout, settings.max_long_poll_seconds),
        )
        if record is None:
            audit_event(
                audit_logger,
                "otp.consume",
                status_code=204,
                outcome="empty",
                wait_seconds=min(timeout, settings.max_long_poll_seconds),
                not_before_age_seconds=round(time.time() - not_before, 3),
                processing_ms=round((time.monotonic() - request_started) * 1000, 2),
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        audit_event(
            audit_logger,
            "otp.consume",
            status_code=200,
            outcome="delivered",
            correlated=record.identifier is not None and record.amount is not None,
            record_age_seconds=round(time.time() - record.created_at, 3),
            processing_ms=round((time.monotonic() - request_started) * 1000, 2),
        )
        return OTPResponse(
            code=record.code,
            sender=record.sender,
            received_at=record.received_at,
            identifier=record.identifier,
            amount=record.amount,
        )

    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("OTP_HOST", "127.0.0.1"), port=int(os.environ.get("OTP_PORT", "8000")))
