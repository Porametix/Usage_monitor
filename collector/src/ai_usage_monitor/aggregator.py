from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import ProviderUsage, UsageSnapshot, UsageSource, UsageStatus, utc_now_iso


@dataclass(frozen=True)
class Totals:
    connected_providers: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    actual_cost_usd: float | None
    estimated_cost_usd: float | None
    budget_usd: float | None
    remaining_budget_usd: float | None


def aggregate(snapshot: UsageSnapshot) -> Totals:
    providers = snapshot.providers
    token_providers = [p for p in providers if p.status == UsageStatus.OK]
    input_total = sum(p.input_tokens or 0 for p in token_providers)
    output_total = sum(p.output_tokens or 0 for p in token_providers)
    actual_items = [p.actual_cost_usd for p in providers if p.actual_cost_usd is not None]
    estimate_items = [p.estimated_cost_usd for p in providers if p.estimated_cost_usd is not None and p.actual_cost_usd is None]
    actual = sum(actual_items) if actual_items else None
    estimated = sum(estimate_items) if estimate_items else None
    budget = snapshot.budget_usd
    spent = (actual or 0.0) + (estimated or 0.0)
    remaining = max(0.0, budget - spent) if budget is not None else None
    return Totals(
        connected_providers=sum(p.status == UsageStatus.OK for p in providers),
        input_tokens=input_total,
        output_tokens=output_total,
        total_tokens=sum((p.total_tokens if p.total_tokens is not None else (p.input_tokens or 0) + (p.output_tokens or 0)) for p in token_providers),
        actual_cost_usd=actual,
        estimated_cost_usd=estimated,
        budget_usd=budget,
        remaining_budget_usd=remaining,
    )


def unavailable_providers(now: str | None = None) -> list[ProviderUsage]:
    updated = now or utc_now_iso()
    return [
        ProviderUsage(id="openai_api", name="OpenAI Completions", status=UsageStatus.UNAVAILABLE, source=UsageSource.PROVIDER_REPORTED, last_updated=updated, message="Enable the optional organization adapter"),
        ProviderUsage(id="anthropic_api", name="Anthropic API", status=UsageStatus.UNSUPPORTED, source=UsageSource.PROVIDER_REPORTED, last_updated=updated, message="Admin report adapter not implemented"),
        ProviderUsage(id="gemini_api", name="Gemini API", status=UsageStatus.UNSUPPORTED, source=UsageSource.PROVIDER_REPORTED, last_updated=updated, message="Only per-request metrics are documented here"),
        ProviderUsage(id="ollama_local", name="Ollama", status=UsageStatus.UNSUPPORTED, source=UsageSource.LOCALLY_TRACKED, last_updated=updated, message="No account-wide usage source"),
        ProviderUsage(id="chatgpt_subscription", name="ChatGPT / Codex", status=UsageStatus.UNSUPPORTED, source=UsageSource.PROVIDER_REPORTED, last_updated=updated, message="Subscription usage API unavailable"),
        ProviderUsage(id="claude_subscription", name="Claude plan", status=UsageStatus.UNSUPPORTED, source=UsageSource.PROVIDER_REPORTED, last_updated=updated, message="Subscription usage API unavailable"),
        ProviderUsage(id="gemini_subscription", name="Gemini plan", status=UsageStatus.UNSUPPORTED, source=UsageSource.PROVIDER_REPORTED, last_updated=updated, message="Subscription usage API unavailable"),
    ]


def demo_snapshot(*, snapshot_id: int | None = None, budget_usd: float = 10.0) -> UsageSnapshot:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    providers = [
        ProviderUsage(id="openai_api", name="OpenAI API", status=UsageStatus.OK, source=UsageSource.DEMO, input_tokens=12000, output_tokens=3500, total_tokens=15500, actual_cost_usd=None, estimated_cost_usd=0.12, budget_usd=budget_usd, last_updated=now, message="Demo data"),
        ProviderUsage(id="chatgpt_subscription", name="ChatGPT / Codex", status=UsageStatus.UNSUPPORTED, source=UsageSource.DEMO, last_updated=now, message="Demo: unsupported"),
        ProviderUsage(id="claude_subscription", name="Claude plan", status=UsageStatus.UNSUPPORTED, source=UsageSource.DEMO, last_updated=now, message="Demo: unsupported"),
        ProviderUsage(id="gemini_subscription", name="Gemini plan", status=UsageStatus.UNSUPPORTED, source=UsageSource.DEMO, last_updated=now, message="Demo: unsupported"),
    ]
    if snapshot_id is None:
        snapshot_id = int(datetime.now(timezone.utc).timestamp() * 1000)
    return UsageSnapshot(schema_version=1, type="usage_snapshot", snapshot_id=snapshot_id, generated_at=now, budget_usd=budget_usd, providers=providers)
