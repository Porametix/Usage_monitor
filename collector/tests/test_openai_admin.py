import json
import httpx
import pytest

from ai_usage_monitor.aggregator import aggregate
from ai_usage_monitor.providers.openai_admin import OpenAIAdminAdapter, ProviderError


def _page(data, *, has_more=False, next_page=None):
    return {"object": "page", "data": data, "has_more": has_more, "next_page": next_page}


def _usage_bucket(input_tokens=1000, output_tokens=500):
    return {"object": "bucket", "start_time": 1, "end_time": 86400, "results": [{"object": "organization.usage.completions.result", "input_tokens": input_tokens, "output_tokens": output_tokens}]}


def _cost_bucket(value=0.25):
    return {"object": "bucket", "start_time": 1, "end_time": 86400, "results": [{"object": "organization.costs.result", "amount": {"value": value, "currency": "usd"}}]}


def test_collects_provider_tokens_and_actual_cost_and_aggregates_budget():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/completions"):
            return httpx.Response(200, json=_page([_usage_bucket()]))
        return httpx.Response(200, json=_page([_cost_bucket(1.25)]))
    adapter = OpenAIAdminAdapter("test-admin-key", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    try:
        record = adapter.collect(budget_usd=10.0)
    finally:
        adapter.close()
    assert calls == ["/v1/organization/usage/completions", "/v1/organization/costs"]
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.total_tokens == 1500
    assert record.actual_cost_usd == 1.25
    totals = aggregate(type("S", (), {"providers": [record], "budget_usd": 10.0})())
    assert totals.remaining_budget_usd == 8.75


def test_authentication_failure_is_not_retried_or_echoed():
    attempts = []
    secret = "private-test-value"
    def handler(request):
        attempts.append(request)
        return httpx.Response(401, json={"error": {"message": secret}})
    adapter = OpenAIAdminAdapter(secret, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert record.status.value == "error"
    assert len(attempts) == 2  # One call each for usage and costs; neither is retried.
    assert secret not in (record.message or "")
    assert all("Authorization" in request.headers for request in attempts)


def test_rate_limit_honors_bounded_retry_after():
    statuses = [429, 200, 200]
    delays = []
    def handler(request):
        status = statuses.pop(0)
        if status == 429:
            return httpx.Response(status, headers={"Retry-After": "0"}, json={})
        if request.url.path.endswith("/completions"):
            return httpx.Response(200, json=_page([_usage_bucket(2, 3)]))
        return httpx.Response(200, json=_page([_cost_bucket(0.1)]))
    adapter = OpenAIAdminAdapter("key", transport=httpx.MockTransport(handler), sleep=delays.append)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert record.status.value == "ok"
    assert delays == [0.0]


def test_provider_outage_and_timeout_are_reported_safely():
    def outage(request):
        return httpx.Response(503, json={"detail": "private provider payload"})
    adapter = OpenAIAdminAdapter("secret", transport=httpx.MockTransport(outage), sleep=lambda _: None)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert record.status.value == "error"
    assert record.input_tokens is None
    assert "HTTP 503" in (record.message or "")
    assert "private provider payload" not in (record.message or "")

    def timeout(request):
        raise httpx.ConnectError("certificate verify failed", request=request)
    adapter = OpenAIAdminAdapter("secret", transport=httpx.MockTransport(timeout), sleep=lambda _: None)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert record.status.value == "error"
    assert "network/timeout" in (record.message or "")


def test_bad_response_schema_and_redirect_are_rejected():
    def bad_json(request):
        return httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})
    adapter = OpenAIAdminAdapter("key", transport=httpx.MockTransport(bad_json), sleep=lambda _: None)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert record.status.value == "error"
    assert "malformed JSON" in (record.message or "")

    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://attacker.invalid/"})
    adapter = OpenAIAdminAdapter("key", transport=httpx.MockTransport(redirect), sleep=lambda _: None)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert "redirect" in (record.message or "")


def test_cost_and_token_values_are_validated():
    def invalid(request):
        if request.url.path.endswith("/completions"):
            return httpx.Response(200, json=_page([_usage_bucket(-1, 2)]))
        return httpx.Response(200, content=json.dumps(_page([_cost_bucket(float("nan"))]), allow_nan=True).encode("utf-8"), headers={"Content-Type": "application/json"})
    adapter = OpenAIAdminAdapter("key", transport=httpx.MockTransport(invalid), sleep=lambda _: None)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert record.status.value == "error"
    assert record.input_tokens is None
    assert record.actual_cost_usd is None


def test_admin_adapter_uses_secure_http_defaults(monkeypatch):
    import ai_usage_monitor.providers.openai_admin as module
    captured = {}
    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def close(self):
            pass
    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    adapter = OpenAIAdminAdapter("key")
    adapter.close()
    assert captured["verify"] is True
    assert captured["follow_redirects"] is False
    assert captured["base_url"] == "https://api.openai.com/v1"


def test_oversized_provider_response_is_bounded():
    def oversized(request):
        return httpx.Response(200, content=b"{" + b" " * 1_000_001, headers={"Content-Type": "application/json"})
    adapter = OpenAIAdminAdapter("key", transport=httpx.MockTransport(oversized), sleep=lambda _: None)
    try:
        record = adapter.collect()
    finally:
        adapter.close()
    assert record.status.value == "error"
    assert "safe response size" in (record.message or "")
