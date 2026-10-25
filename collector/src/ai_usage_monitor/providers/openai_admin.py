from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from ..models import MAX_SAFE_INTEGER, ProviderUsage, UsageSource, UsageStatus, utc_now_iso

BASE_URL = "https://api.openai.com/v1"
MAX_ATTEMPTS = 3
MAX_PAGES = 4
MAX_RESPONSE_BYTES = 1_000_000
MAX_COST_USD = 1_000_000_000.0


class ProviderError(RuntimeError):
    def __init__(self, safe_message: str, *, status_code: int | None = None):
        super().__init__(safe_message)
        self.status_code = status_code
        self.safe_message = safe_message


class OpenAIAdminAdapter:
    """Read-only organization reports. Requires a user-provided Admin API key."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if not api_key or "\r" in api_key or "\n" in api_key:
            raise ValueError("invalid Admin API key")
        self._api_key = api_key
        self._sleep = sleep
        self._random = random_value
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            verify=True,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not path.startswith("/organization/"):
            raise ValueError("provider path is not allow-listed")
        for attempt in range(MAX_ATTEMPTS):
            try:
                with self._client.stream(
                    "GET",
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                ) as response:
                    status = response.status_code
                    if status == 429 or 500 <= status <= 599:
                        if attempt + 1 < MAX_ATTEMPTS:
                            self._sleep(self._retry_delay(response, attempt))
                            continue
                        raise ProviderError(f"OpenAI report unavailable (HTTP {status})", status_code=status)
                    if status == 401:
                        raise ProviderError("OpenAI Admin key rejected (HTTP 401)", status_code=status)
                    if status == 403:
                        raise ProviderError("OpenAI Admin report permission denied (HTTP 403)", status_code=status)
                    if 300 <= status <= 399:
                        raise ProviderError("OpenAI returned a redirect; request blocked", status_code=status)
                    if status >= 400:
                        raise ProviderError(f"OpenAI report request failed (HTTP {status})", status_code=status)
                    content_length = response.headers.get("Content-Length")
                    if content_length is not None:
                        try:
                            if int(content_length) > MAX_RESPONSE_BYTES:
                                raise ProviderError("OpenAI report exceeded safe response size")
                        except ValueError as exc:
                            raise ProviderError("OpenAI response length header invalid") from exc
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" not in content_type.lower():
                        raise ProviderError("OpenAI returned an unexpected content type")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ProviderError("OpenAI report exceeded safe response size")
                        body.extend(chunk)
                    try:
                        payload = json.loads(body)
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise ProviderError("OpenAI returned malformed JSON") from exc
                    if not isinstance(payload, dict):
                        raise ProviderError("OpenAI returned an unexpected response")
                    return payload
            except httpx.RequestError as exc:
                if attempt + 1 < MAX_ATTEMPTS:
                    self._sleep(self._backoff(attempt))
                    continue
                raise ProviderError("OpenAI request failed (network/timeout)") from exc
        raise ProviderError("OpenAI report unavailable")

    def _backoff(self, attempt: int) -> float:
        ceiling = min(2 ** attempt, 8)
        return min(8.0, ceiling * (0.5 + self._random()))

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "")
        try:
            return min(30.0, max(0.0, float(raw)))
        except ValueError:
            return self._backoff(attempt)

    def _report(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        buckets: list[dict[str, Any]] = []
        page: str | None = None
        seen_pages: set[str] = set()
        for _ in range(MAX_PAGES):
            query = dict(params)
            if page:
                query["page"] = page
            payload = self._get_json(path, query)
            data = payload.get("data")
            if payload.get("object") != "page" or not isinstance(data, list) or len(data) > 64:
                raise ProviderError("OpenAI report schema invalid")
            if "has_more" not in payload or not isinstance(payload.get("has_more"), bool):
                raise ProviderError("OpenAI report pagination invalid")
            next_page_value = payload.get("next_page")
            if "next_page" not in payload or (next_page_value is not None and not isinstance(next_page_value, str)):
                raise ProviderError("OpenAI report pagination invalid")
            for bucket in data:
                if not isinstance(bucket, dict) or bucket.get("object") != "bucket":
                    raise ProviderError("OpenAI report schema invalid")
                start_time = bucket.get("start_time")
                end_time = bucket.get("end_time")
                results = bucket.get("results")
                if isinstance(start_time, bool) or not isinstance(start_time, int) or start_time < 0 or isinstance(end_time, bool) or not isinstance(end_time, int) or end_time < start_time or not isinstance(results, list):
                    raise ProviderError("OpenAI report schema invalid")
                if len(results) > 4096:
                    raise ProviderError("OpenAI report exceeds safe result bounds")
                buckets.append(bucket)
            has_more = payload["has_more"]
            if not has_more:
                return buckets
            next_page = next_page_value
            if not isinstance(next_page, str) or not next_page or next_page in seen_pages:
                raise ProviderError("OpenAI report pagination invalid")
            seen_pages.add(next_page)
            page = next_page
        raise ProviderError("OpenAI report exceeded pagination limit")

    @staticmethod
    def _counter(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_SAFE_INTEGER:
            raise ProviderError("OpenAI report token value invalid")
        return value

    def collect(self, *, budget_usd: float | None = None) -> ProviderUsage:
        now_dt = datetime.now(timezone.utc)
        start = datetime(now_dt.year, now_dt.month, 1, tzinfo=timezone.utc)
        common = {"start_time": int(start.timestamp()), "end_time": int(now_dt.timestamp()), "bucket_width": "1d", "limit": 31}
        input_total: int | None = None
        output_total: int | None = None
        actual_cost: float | None = None
        errors: list[str] = []
        try:
            usage = self._report("/organization/usage/completions", common)
            input_total = 0
            output_total = 0
            for bucket in usage:
                for item in bucket.get("results", []):
                    if not isinstance(item, dict) or item.get("object") != "organization.usage.completions.result" or "input_tokens" not in item or "output_tokens" not in item:
                        raise ProviderError("OpenAI report schema invalid")
                    input_total += self._counter(item["input_tokens"])
                    output_total += self._counter(item["output_tokens"])
                    if input_total > MAX_SAFE_INTEGER or output_total > MAX_SAFE_INTEGER:
                        raise ProviderError("OpenAI report token total exceeded safe bounds")
        except ProviderError as exc:
            input_total = None
            output_total = None
            errors.append(exc.safe_message)
        try:
            costs = self._report("/organization/costs", common)
            total = 0.0
            for bucket in costs:
                for item in bucket.get("results", []):
                    if not isinstance(item, dict) or item.get("object") != "organization.costs.result":
                        raise ProviderError("OpenAI cost report schema invalid")
                    amount = item.get("amount")
                    if amount is None:
                        continue
                    if not isinstance(amount, dict) or str(amount.get("currency", "usd")).lower() != "usd":
                        raise ProviderError("OpenAI cost report currency is not USD")
                    value = amount.get("value")
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > MAX_COST_USD:
                        raise ProviderError("OpenAI cost report value invalid")
                    total += float(value)
                    if total > MAX_COST_USD:
                        raise ProviderError("OpenAI cost report total exceeded safe bounds")
            actual_cost = round(total, 6)
        except ProviderError as exc:
            errors.append(exc.safe_message)
        now = utc_now_iso()
        total_tokens = input_total + output_total if input_total is not None and output_total is not None else None
        return ProviderUsage(
            id="openai_api",
            name="OpenAI Completions",
            status=UsageStatus.ERROR if errors else UsageStatus.OK,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=input_total,
            output_tokens=output_total,
            total_tokens=total_tokens,
            actual_cost_usd=actual_cost,
            budget_usd=budget_usd,
            last_updated=now,
            message="; ".join(errors)[:120] if errors else "Tokens: completions only; cost: org-wide",
        )
