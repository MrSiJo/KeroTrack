"""`python -m kerotrack.cli` — break-glass operator commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from kerotrack.bootstrap import get_bootstrap, reset_bootstrap_cache
from kerotrack.db import init_engine, session_factory
from kerotrack.db_migrate import ensure_schema
from kerotrack.migration.v1_to_v2 import migrate
from kerotrack.settings.seeds import seed_defaults
from kerotrack.settings.service import SettingsService


async def _migrate_v1(args: argparse.Namespace) -> int:
    boot = get_bootstrap()
    engine = init_engine(boot.database_url)
    await ensure_schema(engine)
    sf = session_factory(engine)
    async with sf() as session:
        await seed_defaults(session)
    svc = SettingsService(sf)
    try:
        report = await migrate(
            src_db=Path(args.src_db),
            src_config=Path(args.src_config),
            sf=sf,
            settings_service=svc,
            dry_run=args.dry_run,
            force=args.force,
            report_path=Path(args.report) if args.report else None,
        )
    finally:
        await engine.dispose()

    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0 if not report.errors else 2


async def _dump_settings(_: argparse.Namespace) -> int:
    boot = get_bootstrap()
    engine = init_engine(boot.database_url)
    await ensure_schema(engine)
    sf = session_factory(engine)
    async with sf() as session:
        await seed_defaults(session)
    svc = SettingsService(sf)
    try:
        rows = await svc.all()
    finally:
        await engine.dispose()
    print(json.dumps(rows, indent=2, default=str))
    return 0


async def _set_setting(args: argparse.Namespace) -> int:
    boot = get_bootstrap()
    engine = init_engine(boot.database_url)
    await ensure_schema(engine)
    sf = session_factory(engine)
    async with sf() as session:
        await seed_defaults(session)
    svc = SettingsService(sf)
    try:
        # Try parsing as JSON for typed values; fall back to raw string.
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        await svc.set(args.key, value, source="cli")
    finally:
        await engine.dispose()
    print(f"set {args.key} = {value!r}")
    return 0


async def _run_job(args: argparse.Namespace) -> int:
    """Manual job trigger: `kerotrack run-job analysis|cost-analysis|notifier`."""
    from kerotrack.notifier.apprise_notifier import run as run_notifier
    from kerotrack.publish.mqtt_publisher import MqttPublisher
    from kerotrack.analysis.consumption import run_analysis
    from kerotrack.analysis.cost import run_cost_analysis

    boot = get_bootstrap()
    engine = init_engine(boot.database_url)
    await ensure_schema(engine)
    sf = session_factory(engine)
    async with sf() as session:
        await seed_defaults(session)
    svc = SettingsService(sf)

    class _NoopClient:
        async def publish(self, topic, payload, *, qos=0, retain=False):
            return None

    publisher = MqttPublisher(client=_NoopClient())
    try:
        if args.name == "analysis":
            payload = await run_analysis(
                sf=sf, settings_service=svc, publisher=publisher
            )
        elif args.name == "cost-analysis":
            payload = await run_cost_analysis(
                sf=sf, settings_service=svc, publisher=publisher
            )
        elif args.name == "notifier":
            res = await run_notifier(
                sf=sf, settings_service=svc, test_mode=args.test
            )
            payload = {
                "sent": res.sent,
                "channels": res.channels,
                "skipped_reason": res.skipped_reason,
            }
        else:
            print(f"unknown job: {args.name}", file=sys.stderr)
            return 2
    finally:
        await engine.dispose()
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kerotrack")
    sub = parser.add_subparsers(dest="cmd", required=True)

    mig = sub.add_parser("migrate-v1", help="Migrate a v1 deployment into v2")
    mig.add_argument("--src-db", required=True)
    mig.add_argument("--src-config", required=True)
    mig.add_argument("--dry-run", action="store_true")
    mig.add_argument("--force", action="store_true")
    mig.add_argument("--report")
    mig.set_defaults(func=_migrate_v1)

    dump = sub.add_parser("dump-settings", help="Print every setting as JSON")
    dump.set_defaults(func=_dump_settings)

    sset = sub.add_parser("set-setting", help="Override a single setting")
    sset.add_argument("key")
    sset.add_argument("value")
    sset.set_defaults(func=_set_setting)

    runj = sub.add_parser("run-job", help="Manually trigger a scheduled job")
    runj.add_argument("name", choices=["analysis", "cost-analysis", "notifier"])
    runj.add_argument("--test", action="store_true")
    runj.set_defaults(func=_run_job)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Most CLI commands hit the DB which needs APP_SECRET_KEY *or* an empty
    # one (we don't actually instantiate the app, so the middleware
    # constraint doesn't apply). Make missing-key tolerable here.
    os.environ.setdefault("APP_SECRET_KEY", "0" * 64)
    reset_bootstrap_cache()

    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
