from ai_usage_monitor.aggregator import demo_snapshot
from ai_usage_monitor.cli import collect_snapshot
from ai_usage_monitor.models import UsageSource, UsageStatus


def test_live_collection_is_disabled_without_explicit_opt_in():
    snapshot = collect_snapshot(enable_openai_admin=False, budget_usd=None)
    openai = next(p for p in snapshot.providers if p.id == "openai_api")
    assert openai.status == UsageStatus.UNAVAILABLE
    assert openai.input_tokens is None


def test_demo_snapshot_marks_every_record_as_demo():
    snapshot = demo_snapshot(snapshot_id=99)
    assert all(provider.source == UsageSource.DEMO for provider in snapshot.providers)
    assert next(p for p in snapshot.providers if p.id == "chatgpt_subscription").status == UsageStatus.UNSUPPORTED
