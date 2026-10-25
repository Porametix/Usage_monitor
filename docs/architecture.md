# Architecture

## Components

1. The Python collector is started by the user. It may request OpenAI organization Completions usage and Costs reports over HTTPS when the optional Admin-key adapter is explicitly enabled. Token counts cover the Completions report; costs are organization-wide and may include other services. It validates provider results and creates a small normalized snapshot.
2. A serial sink sends snapshots as UTF-8 JSON followed by LF at 115200 baud. It sends no credentials, request bodies, prompts, model output, or commands.
3. ESP32 firmware parses bounded frames and redraws a 240x320 portrait TFT. It performs no provider/network requests and stores no snapshot history.

## Snapshot schema v1

Required top-level fields: schema_version (literal 1), type (usage_snapshot), snapshot_id (safe non-negative integer), generated_at (ISO 8601 with UTC offset), and providers (0..16 items). budget_usd may be null or a finite non-negative number.

Each provider has id, name, status, source, and last_updated. Optional metrics are input_tokens, output_tokens, total_tokens, actual_cost_usd, estimated_cost_usd, budget_usd, quota_remaining_percent, and reset_at. Optional message is a short sanitized status only. Unknown fields are rejected. Numeric tokens are integers from 0 through 9007199254740991; costs are finite, non-negative USD values. If both input and output are present, total must equal their sum. Null means the source did not provide that metric. A missing metric is not zero.

Status values: ok, unsupported, manual, unavailable, error, stale. Source values: provider_reported, locally_tracked, estimated, manual, demo. The source describes provenance, while status describes availability. Demo snapshots use source demo for every generated value.

The complete serialized line including LF is limited to 4096 bytes. Empty provider arrays are valid. Provider IDs are unique. Firmware rejects duplicate snapshot_id values, malformed JSON, invalid UTF-8, unknown keys, numeric overflow, unsupported versions, too many providers, and incomplete required fields. ESP32 freshness is based on time since the last accepted snapshot because the initial hardware has no trusted wall clock; after five minutes without a new snapshot it displays Stale.

## Failure behavior

A provider failure becomes an error/unavailable provider card. It does not stop unrelated adapters or serial transmission. Serial disconnects are retried on the next interval. A duplicate/invalid line does not refresh the display freshness timer. API pagination is capped and retries are bounded. No background persistence or automatic launch is used.

## Dashboard pages

Overview shows connection freshness, healthy provider count, aggregate tokens, actual and estimated costs separately, and configured monthly budget. Subscriptions shows only verified percentage/reset values and explicit Unsupported/Manual/Unavailable states. API Details shows input/output/total and cost provenance. Pages rotate automatically; startup shows a waiting screen.
