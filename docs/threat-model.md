# Threat model

## Assets

Provider API key, organization usage and cost totals, monthly budget, serial link, and integrity of displayed values.

## Trust boundaries

- Provider API -> collector: authenticated HTTPS. The collector uses an allow-listed fixed host, verifies TLS, times out, bounds retries, validates schemas, and never interprets provider text as commands.
- Notebook -> ESP32: USB serial is unauthenticated and unencrypted. The board validates length, UTF-8, schema, types, field sets, and ranges. Physical access can read the aggregate display and can inject serial bytes; injection can corrupt the display until a valid new snapshot arrives, but cannot execute code or expose provider keys because none are sent.
- Local user -> Credential Manager: only the user runs the collector or stores/removes a key. Admin keys pose organization-wide reporting risk and are opt-in.

## In scope mitigations

No browser scraping, OAuth/cookie extraction, provider prompts, arbitrary URLs, request bodies in logs, hidden caches, firmware update commands, SQL history, network listeners, startup persistence, or security-setting changes. Local error messages include only sanitized categories/status codes.

## Residual risks

A compromised Windows account/process can use a stored Credential Manager secret. A malicious USB device or physically accessible cable can inject data. Serial metrics are visible in clear text to host software. Provider reports may be delayed or corrected, so a provider-reported cost is not necessarily the final invoice. The display/controller configuration is unverified until the exact hardware is identified and tested.
