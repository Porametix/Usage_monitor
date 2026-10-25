import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ai_usage_monitor.aggregator import demo_snapshot
from ai_usage_monitor.models import MAX_SAFE_INTEGER, ProviderUsage, UsageSnapshot, UsageSource, UsageStatus
from ai_usage_monitor.serial_protocol import ProtocolError, SnapshotSequenceGuard, is_stale, parse_snapshot, serialize_snapshot


def test_demo_snapshot_round_trips_and_is_labeled_demo():
    source = demo_snapshot(snapshot_id=1)
    parsed = parse_snapshot(serialize_snapshot(source))
    assert parsed.snapshot_id == 1
    assert parsed.providers[0].source == UsageSource.DEMO
    assert parsed.providers[0].total_tokens == 15500
    assert len(serialize_snapshot(parsed)) <= 4096


def test_oversized_frame_is_rejected():
    with pytest.raises(ProtocolError, match="4096"):
        parse_snapshot(b" " * 4097)


def test_invalid_utf8_is_rejected():
    with pytest.raises(ProtocolError, match="UTF-8"):
        parse_snapshot(b"\xff")


def test_missing_field_wrong_type_and_unknown_field_are_rejected():
    valid = json.loads(serialize_snapshot(demo_snapshot(snapshot_id=2)))
    missing = dict(valid)
    del missing["generated_at"]
    wrong = dict(valid, snapshot_id="2")
    extra = dict(valid, execute="no")
    for payload in (missing, wrong, extra):
        with pytest.raises(ProtocolError):
            parse_snapshot(json.dumps(payload))


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ProtocolError, match="duplicate"):
        parse_snapshot('{"schema_version":1,"schema_version":1}')


def test_duplicate_provider_ids_and_mismatched_totals_are_rejected():
    valid = demo_snapshot(snapshot_id=3).model_dump(mode="json")
    valid["providers"].append(valid["providers"][0])
    with pytest.raises(ProtocolError):
        parse_snapshot(json.dumps(valid))
    valid = demo_snapshot(snapshot_id=4).model_dump(mode="json")
    valid["providers"][0]["total_tokens"] = 1
    with pytest.raises(ProtocolError):
        parse_snapshot(json.dumps(valid))


def test_numeric_bounds_and_nan_are_rejected():
    valid = demo_snapshot(snapshot_id=5).model_dump(mode="json")
    valid["providers"][0]["input_tokens"] = MAX_SAFE_INTEGER + 1
    with pytest.raises(ProtocolError):
        parse_snapshot(json.dumps(valid))
    with pytest.raises(ProtocolError):
        parse_snapshot('{"schema_version":NaN}')


def test_stale_and_future_timestamps_are_detected():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = demo_snapshot(snapshot_id=6).model_copy(update={"generated_at": "2025-12-31T23:00:00Z"})
    future = demo_snapshot(snapshot_id=7).model_copy(update={"generated_at": "2026-01-01T01:00:00Z"})
    assert is_stale(old, now=now)
    assert is_stale(future, now=now)
    assert not is_stale(demo_snapshot(snapshot_id=8).model_copy(update={"generated_at": now.isoformat()}), now=now)


def test_snapshot_rejects_naive_timestamp_and_too_many_providers():
    with pytest.raises(ValidationError):
        UsageSnapshot(schema_version=1, type="usage_snapshot", snapshot_id=1, generated_at="2026-01-01T00:00:00", providers=[])
    record = ProviderUsage(id="x", name="X", status=UsageStatus.OK, source=UsageSource.DEMO, last_updated="2026-01-01T00:00:00Z")
    with pytest.raises(ValidationError):
        UsageSnapshot(schema_version=1, type="usage_snapshot", snapshot_id=1, generated_at="2026-01-01T00:00:00Z", providers=[record] * 17)


def test_provider_message_redacts_credential_like_text():
    provider = ProviderUsage(id="safe", name="Safe", status=UsageStatus.ERROR, source=UsageSource.PROVIDER_REPORTED, last_updated="2026-01-01T00:00:00Z", message="request failed Bearer secret-value")
    assert provider.message == "Sensitive details redacted"


def test_duplicate_snapshots_are_rejected_without_refreshing_sequence():
    guard = SnapshotSequenceGuard()
    first = demo_snapshot(snapshot_id=20)
    guard.accept(first)
    with pytest.raises(ProtocolError, match="duplicate"):
        guard.accept(first)
    guard.accept(demo_snapshot(snapshot_id=21))
