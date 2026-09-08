"""Persistent, sanitized audit logging for the Ruten OTP relay."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, Union
from zoneinfo import ZoneInfo


AUDIT_LOGGER_NAME = "ruten.otp.audit"
REDACTED = "[REDACTED]"
TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_ALLOWED_FIELD_NAMES = {
    "status_code",
    "reason",
    "content_type",
    "processing_ms",
    "has_sender",
    "has_message",
    "has_timestamp",
    "has_signature",
    "skew_seconds",
    "request_fingerprint",
    "sender_fingerprint",
    "sender_length",
    "correlated",
    "received_age_seconds",
    "record_age_seconds",
    "wait_seconds",
    "not_before_age_seconds",
    "outcome",
    "otp_ttl_seconds",
    "max_long_poll_seconds",
    "smsforwarder_max_skew_seconds",
    "sender_filter_configured",
    "consumer_configured",
}
_SENSITIVE_FIELD_NAMES = {
    "otp",
    "code",
    "token",
    "secret",
    "cookie",
    "password",
    "cvv",
    "card",
    "cardnumber",
    "message",
    "content",
    "orgcontent",
    "smsbody",
    "sender",
    "amount",
    "identifier",
    "signature",
}


def _field_is_sensitive(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    return normalized in _SENSITIVE_FIELD_NAMES


def _sanitize_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {}
    for name, value in fields.items():
        if (
            name not in _ALLOWED_FIELD_NAMES
            or _field_is_sensitive(name)
            or isinstance(value, (dict, list, tuple, set))
        ):
            sanitized[name] = REDACTED
        elif value is None or isinstance(value, (bool, int, float, str)):
            sanitized[name] = value
        else:
            sanitized[name] = REDACTED
    return sanitized


class _JsonAuditFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "audit_fields", {})
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(TAIPEI).isoformat(timespec="milliseconds"),
            "event": str(getattr(record, "audit_event", "log")),
            "level": record.levelname,
        }
        if isinstance(fields, dict):
            payload.update(_sanitize_fields(fields))
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )


def configure_audit_logger(
    path: Optional[Union[str, Path]],
    *,
    backup_count: int = 30,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> logging.Logger:
    """Configure the process-wide audit logger and return it.

    An empty path disables file output. Reconfiguration closes handlers from
    this module so tests and app factories do not duplicate log lines.
    """

    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, "_ruten_audit_handler", False):
            logger.removeHandler(handler)
            handler.close()

    if path:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            log_path,
            maxBytes=int(max_bytes),
            backupCount=max(0, int(backup_count)),
            encoding="utf-8",
            delay=False,
        )
    else:
        handler = logging.NullHandler()

    handler._ruten_audit_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(_JsonAuditFormatter())
    logger.addHandler(handler)
    return logger


def configure_audit_logger_from_env() -> logging.Logger:
    path = os.environ.get("OTP_AUDIT_LOG_PATH", "").strip() or None
    backup_count = int(os.environ.get("OTP_AUDIT_LOG_BACKUP_COUNT", "30"))
    max_bytes = int(os.environ.get("OTP_AUDIT_LOG_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    return configure_audit_logger(
        path,
        backup_count=backup_count,
        max_bytes=max_bytes,
    )


def audit_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(
        "",
        extra={
            "audit_event": event,
            "audit_fields": fields,
        },
    )
