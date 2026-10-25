from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from .models import MAX_FRAME_BYTES, UsageSnapshot


class ProtocolError(ValueError):
    """A frame was malformed or outside the version 1 bounds."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ProtocolError("non-finite JSON number")


def parse_snapshot(frame: bytes | str) -> UsageSnapshot:
    if isinstance(frame, bytes):
        if len(frame) > MAX_FRAME_BYTES:
            raise ProtocolError("frame exceeds 4096 bytes")
        try:
            text = frame.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ProtocolError("frame is not valid UTF-8") from exc
    else:
        try:
            encoded = frame.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProtocolError("frame is not valid UTF-8") from exc
        if len(encoded) > MAX_FRAME_BYTES:
            raise ProtocolError("frame exceeds 4096 bytes")
        text = frame
    if "\x00" in text:
        raise ProtocolError("NUL byte is not permitted")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ProtocolError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("malformed JSON") from exc
    try:
        snapshot = UsageSnapshot.model_validate(payload)
    except (ValidationError, TypeError) as exc:
        raise ProtocolError("snapshot does not match schema version 1") from exc
    return snapshot


def serialize_snapshot(snapshot: UsageSnapshot) -> bytes:
    payload = snapshot.model_dump(mode="json")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise ProtocolError("snapshot cannot be encoded as JSON") from exc
    if len(encoded) > MAX_FRAME_BYTES:
        raise ProtocolError("serialized snapshot exceeds 4096 bytes")
    return encoded


def is_stale(snapshot: UsageSnapshot, *, now: datetime | None = None, max_age: timedelta = timedelta(minutes=5)) -> bool:
    reference = now or datetime.now(timezone.utc)
    generated = datetime.fromisoformat(snapshot.generated_at.replace("Z", "+00:00"))
    age = reference - generated
    return age > max_age or age < timedelta(minutes=-2)


class SnapshotSequenceGuard:
    """Small host-side contract helper mirroring firmware duplicate-ID behavior."""

    def __init__(self) -> None:
        self._last_snapshot_id: int | None = None

    def accept(self, snapshot: UsageSnapshot) -> None:
        if self._last_snapshot_id == snapshot.snapshot_id:
            raise ProtocolError("duplicate snapshot")
        self._last_snapshot_id = snapshot.snapshot_id
