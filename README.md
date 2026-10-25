# Usage_monitor

A local Windows collector and USB-Serial dashboard for AI usage. The ESP32 is display-only: provider requests and credentials stay on the notebook. Version 1 has no cloud backend and no Wi-Fi feature.

## MVP status

The repository contains a demo collector, a bounded versioned serial protocol, an optional OpenAI organization usage adapter, an ESP32 TFT dashboard, and automated tests. Demo values are always marked Demo. The OpenAI adapter is off unless explicitly enabled and uses an organization Admin key; subscription-plan usage is not scraped or inferred. No physical hardware was available in this workspace, so the display controller, wiring, firmware build, and hardware behavior remain unverified.

## Start the collector in demo mode

From Windows PowerShell, in the repository root:

    py -3 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -e .\collector
    python -m ai_usage_monitor.cli demo --port COM3 --interval 5

Replace COM3 with the serial port shown by Device Manager. Demo mode sends only synthetic values labelled Demo. Use --once to send one snapshot and exit, or omit --port to print a validated JSON line. The collector runs only while this command is open; it installs no service or startup task.

## Optional OpenAI API reporting

The OpenAI organization usage and costs endpoints require an organization Admin API key. This requires an Admin API key with Organization Usage read permission; prefer a custom role limited to that read access. The adapter is disabled by default. Review docs/provider-capability-matrix.md and SECURITY.md first. If you have accepted that risk, store the key in Windows Credential Manager using the hidden prompt:

    python -m ai_usage_monitor.cli credential set openai_admin

Then explicitly enable the adapter:

    python -m ai_usage_monitor.cli collect --port COM3 --enable-openai-admin --interval 900

The collector sends read-only HTTPS GET requests to the fixed OpenAI API host. It reports current-month completion token counts (not all OpenAI API token categories) and organization-wide provider-reported costs. Costs can include services beyond the completion-token report, so those totals have different coverage. It does not report ChatGPT/Codex subscription allowance. To revoke access, revoke the key at OpenAI and remove the local copy:

    python -m ai_usage_monitor.cli credential delete openai_admin

No credentials are needed for demo mode or tests.

## Tests

    python -m pip install -e ".\collector[dev]"
    python -m pytest .\collector\tests

Tests use local mocks and never call provider APIs. Hardware tests require the actual ESP32 and display and have not been performed here.

## Firmware

Install PlatformIO Core and connect a compatible ESP32 DevKit by USB. Confirm the module variant and TFT controller before wiring or flashing. Open firmware/esp32_tft in PlatformIO and build the esp32dev environment. The default TFT_eSPI setup selects ILI9341 because it is common on 240x320 modules; this is an unverified default. If the display marking or datasheet identifies another controller, change the driver macro in platformio.ini before building. Uploading firmware is a separate manual action.

See docs/wiring.md for a provisional GPIO map and the information still needed to make it final. The firmware cycles through Overview, Subscriptions, and API Details automatically; touch is not required.

## Protocol and data limits

The notebook sends one newline-delimited JSON snapshot, capped at 4096 UTF-8 bytes. Schema version 1 allows at most 16 providers, bounded integers, finite non-negative costs, strict fields, and no credentials, prompts, chat text, or commands. The ESP32 ignores malformed, oversized, duplicate, stale, or unsupported-version frames. Serial is not encrypted; keep physical access to the USB cable and device in mind.

## Limitations

- Only OpenAI organization API usage/costs has an implemented live adapter, and it requires an Admin key. Use an appropriately scoped organization and key.
- ChatGPT/Codex, Claude/Claude Code, and Gemini subscription meters are Unsupported unless the provider publishes a suitable documented local API. The monitor will not inspect browser cookies, app databases, hidden CLI state, or private endpoints.
- Anthropic's documented organization reports are a possible future adapter but require Admin API access and are currently beta; no Anthropic key is accepted by this MVP.
- Gemini API responses report per-request usage, but this monitor does not make AI requests or intercept unrelated applications. It cannot turn those response metrics into account-wide usage.
- Ollama exposes per-request usage fields, not account-wide dashboard history. A future local adapter would need to observe requests without storing prompt or response content.
- No aggregate history database, touchscreen, exact board detection, or automatic startup behavior is included.
- The notebook must remain awake and the collector running for fresh updates. The ESP32 shows stale/waiting status after snapshots stop.
