from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_FRAME_BYTES = 4096
MAX_PROVIDERS = 16
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-(?:ant-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"(?i)(?:api[-_ ]?key|authorization|token|password)\s*[:=]\s*\S+"),
)


class UsageStatus(str, Enum):
    OK = "ok"
    UNSUPPORTED = "unsupported"
    MANUAL = "manual"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    STALE = "stale"


class UsageSource(str, Enum):
    PROVIDER_REPORTED = "provider_reported"
    LOCALLY_TRACKED = "locally_tracked"
    ESTIMATED = "estimated"
    MANUAL = "manual"
    DEMO = "demo"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


def _valid_datetime(value: str) -> str:
    if len(value) > 40:
        raise ValueError("timestamp too long")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value


def _finite_nonnegative(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value < 0 or value > 1_000_000_000:
        raise ValueError("amount must be finite and between 0 and 1000000000")
    return value


class ProviderUsage(StrictModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=32)
    status: UsageStatus
    source: UsageSource
    input_tokens: int | None = Field(default=None, ge=0, le=MAX_SAFE_INTEGER)
    output_tokens: int | None = Field(default=None, ge=0, le=MAX_SAFE_INTEGER)
    total_tokens: int | None = Field(default=None, ge=0, le=MAX_SAFE_INTEGER)
    actual_cost_usd: float | None = None
    estimated_cost_usd: float | None = None
    budget_usd: float | None = None
    quota_remaining_percent: float | None = Field(default=None, ge=0, le=100)
    last_updated: str
    reset_at: str | None = None
    message: str | None = Field(default=None, max_length=120, pattern=r"^[^\r\n]*$")

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: UsageStatus | str) -> UsageStatus:
        return value if isinstance(value, UsageStatus) else UsageStatus(value)

    @field_validator("source", mode="before")
    @classmethod
    def parse_source(cls, value: UsageSource | str) -> UsageSource:
        return value if isinstance(value, UsageSource) else UsageSource(value)

    @field_validator("last_updated", "reset_at")
    @classmethod
    def timestamp_has_offset(cls, value: str | None) -> str | None:
        return None if value is None else _valid_datetime(value)

    @field_validator("actual_cost_usd", "estimated_cost_usd", "budget_usd")
    @classmethod
    def costs_are_finite(cls, value: float | None) -> float | None:
        return _finite_nonnegative(value)

    @field_validator("name")
    @classmethod
    def name_is_single_line(cls, value: str) -> str:
        if any(ord(ch) < 0x20 for ch in value):
            raise ValueError("name must not contain control characters")
        return value

    @field_validator("message")
    @classmethod
    def message_is_safe_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(ch) < 0x20 for ch in value):
            raise ValueError("message must be a single safe line")
        if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            return "Sensitive details redacted"
        return value

    @model_validator(mode="after")
    def totals_match_parts(self) -> ProviderUsage:
        if self.input_tokens is not None and self.output_tokens is not None:
            expected = self.input_tokens + self.output_tokens
            if expected > MAX_SAFE_INTEGER:
                raise ValueError("total token count exceeds safe integer bound")
            if self.total_tokens is not None and self.total_tokens != expected:
                raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self


class UsageSnapshot(StrictModel):
    schema_version: Literal[1]
    type: Literal["usage_snapshot"]
    snapshot_id: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    generated_at: str
    budget_usd: float | None = None
    providers: list[ProviderUsage] = Field(max_length=MAX_PROVIDERS)

    @field_validator("generated_at")
    @classmethod
    def snapshot_time_has_offset(cls, value: str) -> str:
        return _valid_datetime(value)

    @field_validator("budget_usd")
    @classmethod
    def budget_is_finite(cls, value: float | None) -> float | None:
        return _finite_nonnegative(value)

    @model_validator(mode="after")
    def provider_ids_are_unique(self) -> UsageSnapshot:
        ids = [provider.id for provider in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError("provider IDs must be unique")
        return self


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
