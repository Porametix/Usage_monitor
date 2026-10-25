from ai_usage_monitor.aggregator import aggregate
from ai_usage_monitor.models import ProviderUsage, UsageSnapshot, UsageSource, UsageStatus


def test_actual_and_estimated_costs_do_not_double_count_one_provider():
    now = "2026-01-01T00:00:00Z"
    providers = [
        ProviderUsage(id="reported", name="Reported", status=UsageStatus.OK, source=UsageSource.PROVIDER_REPORTED, input_tokens=3, output_tokens=2, total_tokens=5, actual_cost_usd=2.0, estimated_cost_usd=9.0, last_updated=now),
        ProviderUsage(id="estimate", name="Estimate", status=UsageStatus.OK, source=UsageSource.ESTIMATED, total_tokens=4, estimated_cost_usd=1.0, last_updated=now),
    ]
    snapshot = UsageSnapshot(schema_version=1, type="usage_snapshot", snapshot_id=1, generated_at=now, budget_usd=10.0, providers=providers)
    totals = aggregate(snapshot)
    assert totals.total_tokens == 9
    assert totals.actual_cost_usd == 2.0
    assert totals.estimated_cost_usd == 1.0
    assert totals.remaining_budget_usd == 7.0
