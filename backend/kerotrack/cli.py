"""`python -m kerotrack.cli` — break-glass operator commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import delete, desc, select

from kerotrack.bootstrap import get_bootstrap, reset_bootstrap_cache
from kerotrack.db import init_engine, session_factory
from kerotrack.db_migrate import ensure_schema
from kerotrack.migration.v1_to_v2 import migrate
from kerotrack.models.refill import ActualRefillCost
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


async def _with_session(callback):
    boot = get_bootstrap()
    engine = init_engine(boot.database_url)
    await ensure_schema(engine)
    sf = session_factory(engine)
    async with sf() as session:
        await seed_defaults(session)
    try:
        return await callback(sf)
    finally:
        await engine.dispose()


def _refill_to_dict(row: ActualRefillCost) -> dict:
    return {c: getattr(row, c) for c in row.__table__.columns.keys()}


async def _refill_add(args: argparse.Namespace) -> int:
    async def _do(sf):
        async with sf() as session:
            existing = (
                await session.execute(
                    select(ActualRefillCost).where(
                        ActualRefillCost.refill_date == args.refill_date
                    )
                )
            ).scalar_one_or_none()
            if existing is not None and not args.force:
                print(
                    f"refill at {args.refill_date} already exists — use --force to overwrite",
                    file=sys.stderr,
                )
                return 2
            payload = {
                "refill_date": args.refill_date,
                "actual_volume_litres": args.volume,
                "actual_ppl": args.ppl,
                "total_cost": args.total_cost,
                "invoice_ref": args.invoice,
                "notes": args.notes,
                "order_date": args.order_date,
                "order_ref": args.order_ref,
            }
            if existing is not None:
                for k, v in payload.items():
                    setattr(existing, k, v)
            else:
                session.add(ActualRefillCost(**payload))
            await session.commit()
        print(json.dumps(payload, default=str))
        return 0

    return await _with_session(_do)


async def _refill_list(_: argparse.Namespace) -> int:
    async def _do(sf):
        async with sf() as session:
            rows = (
                (
                    await session.execute(
                        select(ActualRefillCost).order_by(
                            desc(ActualRefillCost.refill_date)
                        )
                    )
                )
                .scalars()
                .all()
            )
        items = [_refill_to_dict(r) for r in rows]
        print(json.dumps({"items": items, "count": len(items)}, indent=2, default=str))
        return 0

    return await _with_session(_do)


async def _refill_delete(args: argparse.Namespace) -> int:
    async def _do(sf):
        async with sf() as session:
            result = await session.execute(
                delete(ActualRefillCost).where(
                    ActualRefillCost.refill_date == args.refill_date
                )
            )
            await session.commit()
        if result.rowcount == 0:
            print(f"no refill at {args.refill_date}", file=sys.stderr)
            return 1
        print(f"deleted refill at {args.refill_date}")
        return 0

    return await _with_session(_do)


async def _refill_clear(args: argparse.Namespace) -> int:
    if not args.yes:
        print("refusing to clear without --yes", file=sys.stderr)
        return 2

    async def _do(sf):
        async with sf() as session:
            result = await session.execute(delete(ActualRefillCost))
            await session.commit()
        print(f"cleared {result.rowcount} actual_refill_costs row(s)")
        return 0

    return await _with_session(_do)


def _parse_historical_deliveries(path: Path) -> list[dict]:
    """Parse the v1 ``historical_deliveries.txt`` format.

    Lines are ``Product - Quantity - Service - DeliveryBy - ppl - OrderTotal``
    with a one-line header. Date format is ``DD/MM/YYYY``.
    """
    if not path.exists():
        return []
    deliveries: list[dict] = []
    lines = path.read_text().splitlines()
    if not lines:
        return []
    # Skip header (matches v1 behaviour).
    for raw in lines[1:]:
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(" - ")]
        if len(parts) < 6:
            continue
        try:
            quantity = float(parts[1])
            ppl = float(parts[4])
            total_cost = float(parts[5])
            day, month, year = parts[3].split("/")
            delivery_date = f"{year}-{month}-{day} 12:00:00"
        except (ValueError, IndexError):
            continue
        deliveries.append(
            {
                "refill_date": delivery_date,
                "actual_volume_litres": quantity,
                "actual_ppl": ppl,
                "total_cost": total_cost,
                "invoice_ref": parts[0],
                "notes": parts[2],
            }
        )
    return deliveries


async def _refill_import_historical(args: argparse.Namespace) -> int:
    src = Path(args.path)
    deliveries = _parse_historical_deliveries(src)
    if not deliveries:
        print(f"no deliveries parsed from {src}", file=sys.stderr)
        return 1

    async def _do(sf):
        added = 0
        skipped = 0
        async with sf() as session:
            for d in deliveries:
                existing = (
                    await session.execute(
                        select(ActualRefillCost).where(
                            ActualRefillCost.refill_date == d["refill_date"]
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None and not args.force:
                    skipped += 1
                    continue
                if existing is not None:
                    for k, v in d.items():
                        setattr(existing, k, v)
                else:
                    session.add(ActualRefillCost(**d))
                added += 1
            await session.commit()
        print(
            json.dumps(
                {"added_or_updated": added, "skipped": skipped, "total": len(deliveries)},
                indent=2,
            )
        )
        return 0

    return await _with_session(_do)


# ----- ONS / cost rebuild (one-shot historical correction) ------------


async def _import_ons_prices(args: argparse.Namespace) -> int:
    from kerotrack.analysis.cost_rebuild import import_ons_csv

    async def _do(sf):
        count = await import_ons_csv(sf, csv_path=Path(args.csv))
        print(json.dumps({"imported": count, "csv": args.csv}, indent=2))
        return 0

    return await _with_session(_do)


async def _rebuild_costs(args: argparse.Namespace) -> int:
    """Rebuild refill_periods using the PPL resolver. Default is dry-run.

    Pass ``--apply`` to actually mutate the DB. ``--src-db PATH`` lets
    you point at a snapshot copy so you can validate offline first.
    """
    from kerotrack.analysis.cost_rebuild import rebuild_periods

    async def _do(sf):
        svc = SettingsService(sf)
        report = await rebuild_periods(sf, svc, apply=args.apply)
        if args.brief:
            slim = {k: v for k, v in report.items() if k not in ("before", "after")}
            slim["before_summary"] = [
                {
                    "start": p["start_date"],
                    "end": p["end_date"],
                    "days": p["days"],
                    "total_cost": p["total_cost"],
                    "avg_ppl": p["average_ppl"],
                }
                for p in report["before"]
            ]
            slim["after_summary"] = [
                {
                    "start": p["start_date"],
                    "end": p["end_date"],
                    "days": p["days"],
                    "total_cost": p["total_cost"],
                    "avg_ppl": p["average_ppl"],
                    "used_actual": p["used_actual_cost"],
                }
                for p in report["after"]
            ]
            print(json.dumps(slim, indent=2, default=str))
        else:
            print(json.dumps(report, indent=2, default=str))
        return 0

    if args.src_db:
        # Spin up an isolated engine against the alternative DB. Used
        # for validating the rebuild against a snapshot before touching
        # the live volume.
        boot = get_bootstrap()
        src_path = Path(args.src_db).resolve()
        url = f"sqlite+aiosqlite:///{src_path.as_posix()}"
        engine = init_engine(url)
        await ensure_schema(engine)
        sf = session_factory(engine)
        async with sf() as session:
            await seed_defaults(session)
        try:
            return await _do(sf)
        finally:
            await engine.dispose()
        return 0
    return await _with_session(_do)


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

    # ----- refill management (A7) -----------------------------------------
    add_refill = sub.add_parser(
        "add-refill", help="Insert a manual actual_refill_costs row"
    )
    add_refill.add_argument(
        "--refill-date", required=True, help="YYYY-MM-DD HH:MM:SS"
    )
    add_refill.add_argument("--volume", type=float, help="Litres delivered")
    add_refill.add_argument("--ppl", type=float, help="Pence per litre")
    add_refill.add_argument("--total-cost", type=float, help="Invoice total in pounds")
    add_refill.add_argument("--invoice", help="Invoice reference")
    add_refill.add_argument("--notes")
    add_refill.add_argument("--order-date")
    add_refill.add_argument("--order-ref")
    add_refill.add_argument(
        "--force", action="store_true", help="Overwrite an existing entry"
    )
    add_refill.set_defaults(func=_refill_add)

    list_refills = sub.add_parser(
        "list-refills", help="List manual actual_refill_costs rows as JSON"
    )
    list_refills.set_defaults(func=_refill_list)

    del_refill = sub.add_parser(
        "delete-refill", help="Delete a single actual_refill_costs row"
    )
    del_refill.add_argument(
        "--refill-date", required=True, help="YYYY-MM-DD HH:MM:SS"
    )
    del_refill.set_defaults(func=_refill_delete)

    clear_refills = sub.add_parser(
        "clear-refills", help="Delete every actual_refill_costs row (--yes required)"
    )
    clear_refills.add_argument("--yes", action="store_true", help="Confirm deletion")
    clear_refills.set_defaults(func=_refill_clear)

    import_hist = sub.add_parser(
        "import-historical",
        help="Bulk-import deliveries from a historical_deliveries.txt file",
    )
    import_hist.add_argument(
        "--path",
        required=True,
        help="Path to historical_deliveries.txt (v1 format)",
    )
    import_hist.add_argument(
        "--force", action="store_true", help="Overwrite existing rows"
    )
    import_hist.set_defaults(func=_refill_import_historical)

    # ----- one-shot historical PPL correction (this instance only) ------
    ons = sub.add_parser(
        "import-ons-prices",
        help="Import ONS RPI heating-oil monthly averages into monthly_avg_ppl",
    )
    ons.add_argument(
        "--csv", required=True, help="Path to series-XXXXX.csv from ONS"
    )
    ons.set_defaults(func=_import_ons_prices)

    rebuild = sub.add_parser(
        "rebuild-costs",
        help=(
            "Re-detect refill_periods using ONS + actual_refill_costs + "
            "first-reliable-sensor anchors. Read-only by default; pass "
            "--apply to write."
        ),
    )
    rebuild.add_argument(
        "--src-db",
        help=(
            "Run against an alternative DB path (e.g. a snapshot copy). "
            "When omitted, uses the live DATABASE_URL."
        ),
    )
    rebuild.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this, prints a dry-run report only.",
    )
    rebuild.add_argument(
        "--brief",
        action="store_true",
        help="Print a slim before/after summary instead of full payloads",
    )
    rebuild.set_defaults(func=_rebuild_costs)

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
