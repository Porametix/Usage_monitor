# Security Notes

## Data flow

AI provider read-only HTTPS APIs -> Windows collector -> USB Serial -> ESP32 TFT. No cloud service is used by this project. The ESP32 contains no API client or credential storage and does not enable Wi-Fi, Bluetooth, shell access, network services, or serial commands.

## Secrets

Only the optional OpenAI organization Admin key is supported. It is stored through Python keyring's Windows Credential Manager backend, never in source, config, JSON, SQLite, logs, or serial frames. The key is not needed for the demo. The Admin key is disabled until the user passes --enable-openai-admin. Use a dedicated organization and, where available, a custom role limited to Usage read; if the reporting permission is too broad, leave the adapter off. Windows Credential Manager does not protect against every form of malware, an unlocked account, or account compromise.

Rotate/revoke a key in the provider console, then remove the local entry with the credential delete command. The app never creates keys or changes provider billing settings.

## Network behavior

The adapter uses a fixed provider URL, HTTPS, hostname and certificate verification, finite timeouts, no redirects, bounded retries for idempotent GETs, and bounded report pagination. It discards response bodies from HTTP errors and only reports status codes. It never logs authorization headers or request bodies.

## Serial input

Treat serial bytes as untrusted. Firmware caps each line at 4096 bytes, validates UTF-8 and schema version, rejects unknown keys and bad types, bounds provider count and numeric ranges, rejects duplicate snapshot IDs, and never executes received data. USB Serial is not encrypted; physical access to the notebook or display may expose the aggregate metrics being shown.

## Reporting a vulnerability

Do not include API keys, prompts, or personal data in reports. Contact the repository owner through the private reporting channel configured for the GitHub repository.
