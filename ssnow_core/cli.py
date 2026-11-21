"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from .config import ensure_dirs
from .logging_config import setup_logging
from .scheduler import run_due
from .sources.registry import build_adapter
from .sim import list_scenarios, get_scenario
from .store import Store


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ssnow", description="Solar System Now")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Run one ingestion cycle for due sources")
    p_ingest.add_argument("--source", help="Ingest only this source (bypasses due check)")
    p_ingest.add_argument("--data-dir", help="Override data directory")

    p_stats = sub.add_parser("stats", help="Show storage statistics")
    p_stats.add_argument("--data-dir", help="Override data directory")

    p_prune = sub.add_parser("prune", help="Prune historical snapshots and observations")
    p_prune.add_argument("--days", type=int, default=None, help="Retention days (default: from settings or 90)")
    p_prune.add_argument("--data-dir", help="Override data directory")

    p_export = sub.add_parser("export", help="Export SQLite + assets backup archive")
    p_export.add_argument("dest", help="Destination .tar.gz path")
    p_export.add_argument("--data-dir", help="Override data directory")

    p_gui = sub.add_parser("gui", help="Launch the desktop GUI")
    p_gui.add_argument("--data-dir", help="Override data directory")

    p_sim = sub.add_parser("sim", help="Run deterministic simulation scenarios")
    p_sim.add_argument("--data-dir", help="Override data directory")
    sim_sub = p_sim.add_subparsers(dest="sim_command", required=True)

    p_sim_list = sim_sub.add_parser("list", help="List available simulations")
    p_sim_list.add_argument("--data-dir", help="Override data directory")

    p_sim_run = sim_sub.add_parser("run", help="Run a simulation scenario")
    p_sim_run.add_argument("id", help="Scenario id (see `ssnow sim list`)")
    p_sim_run.add_argument(
        "--param",
        action="append",
        default=[],
        help="Parameter as key=value (repeatable)",
    )
    p_sim_run.add_argument("--data-dir", help="Override data directory")
    return parser


def _parse_params(pairs: list[str]) -> dict:
    params: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"invalid --param '{pair}': expected key=value")
        key, value = pair.split("=", 1)
        try:
            value = float(value)
        except ValueError:
            pass
        params[key] = value
    return params


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    setup_logging(level=getattr(args, "log_level", "INFO"))
    if getattr(args, "data_dir", None):
        import os

        os.environ["SSNOW_DATA_DIR"] = args.data_dir
    ensure_dirs()
    store = Store()

    try:
        if args.command in ("ingest", "gui"):
            from .seed import seed_if_empty

            seed_if_empty(store)

        if args.command == "ingest":
            import httpx

            with httpx.Client() as client:
                if args.source:
                    adapter = build_adapter(args.source)
                    if adapter is None:
                        print(f"unknown source: {args.source}")
                        return 1
                    reports = [adapter.ingest(store, client)]
                else:
                    reports = run_due(store, client)
            for report in reports:
                status = "ok" if report.ok else f"FAIL: {report.error}"
                print(
                    f"{report.source_id}: {status} "
                    f"({len(report.events)} events, {len(report.observations)} observations, {report.assets} assets)"
                )
            return 0
        if args.command == "stats":
            for key, value in store.stats().items():
                print(f"{key}: {value}")
            return 0
        if args.command == "prune":
            days = args.days if args.days is not None else int(store.get_setting("retention_days") or 90)
            n_snaps = store.prune_snapshots(days)
            n_obs = store.prune_observations(days)
            n_assets = store.prune_assets_for_source("sun", keep_latest=14, prefix=True)
            print(f"Pruned {n_snaps} snapshots, {n_obs} observations, {n_assets} old assets (retention: {days} days)")
            return 0
        if args.command == "export":
            from pathlib import Path

            path = store.export_backup(Path(args.dest))
            print(f"backup written to {path}")
            return 0
        if args.command == "gui":
            from ssnow_desktop.app import run

            return run()
        if args.command == "sim":
            if args.sim_command == "list":
                for meta in list_scenarios():
                    print(f"{meta.id}: {meta.title} — {meta.description}")
                    print(f"    citation: {meta.citation}")
                    for p in meta.params:
                        print(f"    --param {p.id}={p.default}  ({p.label}, {p.unit or ''})")
                return 0
            if args.sim_command == "run":
                cls = get_scenario(args.id)
                if cls is None:
                    print(f"unknown simulation id: {args.id}")
                    print("run `ssnow sim list` for available ids")
                    return 1
                scenario = cls()
                params = _parse_params(args.param)
                for p in cls.meta.params:
                    params.setdefault(p.id, p.default)
                result = scenario.run(params)
                print(json.dumps({"scenario": args.id, "result": result}, indent=2))
                return 0
    finally:
        store.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
