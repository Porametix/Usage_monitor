from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from .aggregator import demo_snapshot, unavailable_providers
from .credentials import delete_secret, get_secret, set_secret_interactive
from .models import ProviderUsage, UsageSnapshot, UsageSource, UsageStatus
from .providers.openai_admin import OpenAIAdminAdapter
from .serial_protocol import serialize_snapshot
from .serial_sink import SerialSink

LOG = logging.getLogger("ai_usage_monitor")


def _replace_provider(providers: list[ProviderUsage], replacement: ProviderUsage) -> list[ProviderUsage]:
    return [replacement if p.id == replacement.id else p for p in providers]


def collect_snapshot(*, enable_openai_admin: bool, budget_usd: float | None) -> UsageSnapshot:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    providers = unavailable_providers(now)
    if enable_openai_admin:
        try:
            secret = get_secret("openai_admin")
        except Exception:
            secret = None
        if not secret:
            record = ProviderUsage(id="openai_api", name="OpenAI Completions", status=UsageStatus.UNAVAILABLE, source=UsageSource.PROVIDER_REPORTED, last_updated=now, message="Admin key unavailable in Credential Manager")
        else:
            adapter = OpenAIAdminAdapter(secret)
            try:
                record = adapter.collect(budget_usd=budget_usd)
            except Exception:
                record = ProviderUsage(id="openai_api", name="OpenAI Completions", status=UsageStatus.ERROR, source=UsageSource.PROVIDER_REPORTED, last_updated=now, message="OpenAI collector failed safely")
            finally:
                adapter.close()
            del secret
        providers = _replace_provider(providers, record)
    return UsageSnapshot(
        schema_version=1,
        type="usage_snapshot",
        snapshot_id=int(time.time() * 1000),
        generated_at=now,
        budget_usd=budget_usd,
        providers=providers,
    )


def _run(args: argparse.Namespace, *, demo: bool) -> int:
    if demo:
        def build() -> UsageSnapshot:
            return demo_snapshot(budget_usd=args.budget_usd if args.budget_usd is not None else 10.0)
        enable_openai = False
    else:
        def build() -> UsageSnapshot:
            return collect_snapshot(enable_openai_admin=args.enable_openai_admin, budget_usd=args.budget_usd)
        enable_openai = args.enable_openai_admin
    if not args.port:
        snapshot = build()
        sys.stdout.buffer.write(serialize_snapshot(snapshot))
        return 0
    sink = SerialSink(args.port)
    try:
        if args.once:
            if not sink.connect():
                LOG.error("Serial port is unavailable; provider polling was skipped")
                return 2
            snapshot = build()
            if sink.send(snapshot):
                LOG.info("Snapshot sent%s", " (Demo)" if demo else "")
                return 0
            LOG.error("Snapshot was not sent; check the serial port and retry")
            return 2
        LOG.info("Collector started; interval=%ss%s", args.interval, " (Demo)" if demo else "")
        if enable_openai:
            LOG.info("OpenAI organization reports enabled; Admin key stays on this notebook")
        while True:
            if not sink.connect():
                LOG.warning("Serial port is unavailable; provider polling was skipped")
                time.sleep(args.interval)
                continue
            snapshot = build()
            if sink.send(snapshot):
                LOG.info("Snapshot sent%s", " (Demo)" if demo else "")
            else:
                LOG.warning("Snapshot is ready; waiting for the serial device")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        LOG.info("Collector stopped")
        return 0
    finally:
        sink.close()


def _positive_interval(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("interval must be an integer number of seconds") from exc
    if parsed < 1 or parsed > 86400:
        raise argparse.ArgumentTypeError("interval must be between 1 and 86400 seconds")
    return parsed


def _collect_interval(value: str) -> int:
    parsed = _positive_interval(value)
    if parsed < 60:
        raise argparse.ArgumentTypeError("live provider polling interval must be at least 60 seconds")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-usage-monitor", description="Local AI usage collector; demo mode needs no credentials")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="send clearly labelled synthetic data")
    demo.add_argument("--port", help="USB Serial port, for example COM3")
    demo.add_argument("--interval", type=_positive_interval, default=5)
    demo.add_argument("--budget-usd", type=float, default=10.0)
    demo.add_argument("--once", action="store_true", help="send one snapshot and exit")

    collect = subparsers.add_parser("collect", help="collect supported provider reports")
    collect.add_argument("--port", required=True, help="USB Serial port, for example COM3")
    collect.add_argument("--interval", type=_collect_interval, default=900)
    collect.add_argument("--budget-usd", type=float)
    collect.add_argument("--enable-openai-admin", action="store_true", help="opt in to organization Admin API reporting")
    collect.add_argument("--once", action="store_true", help="collect one snapshot and exit")

    credential = subparsers.add_parser("credential", help="manage the optional OpenAI Admin key")
    credential_sub = credential.add_subparsers(dest="credential_action", required=True)
    store = credential_sub.add_parser("set", help="store an OpenAI organization Admin key")
    store.add_argument("name", choices=["openai_admin"])
    remove = credential_sub.add_parser("delete", help="remove a stored OpenAI Admin key")
    remove.add_argument("name", choices=["openai_admin"])
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "demo":
        return _run(args, demo=True)
    if args.command == "collect":
        return _run(args, demo=False)
    if args.command == "credential":
        try:
            if args.credential_action == "set":
                set_secret_interactive(args.name)
                LOG.info("Credential stored in Windows Credential Manager")
            else:
                removed = delete_secret(args.name)
                LOG.info("Credential removed" if removed else "No stored credential was found")
            return 0
        except Exception:
            LOG.error("Credential operation failed; check Windows Credential Manager availability")
            return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
