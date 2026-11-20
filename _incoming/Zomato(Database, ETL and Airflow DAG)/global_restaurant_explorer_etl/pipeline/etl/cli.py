"""Command-line interface for the Global Restaurant Explorer ETL pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from pipeline.etl.config import ETLConfig
from pipeline.etl.runner import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.etl",
        description="Global Restaurant Explorer Platform — Bronze/Silver/Gold ETL Pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="Execute the ETL pipeline")
    run_cmd.add_argument("--source", type=Path, default=None, help="Path to source CSV file (e.g., data/zomato_cleaned.csv)")
    run_cmd.add_argument(
        "--mode",
        choices=["full", "bronze", "silver", "gold", "validate"],
        default="full",
        help="Execution mode (default: full)",
    )
    run_cmd.add_argument("--dry-run", action="store_true", help="Run extract/validate/transform without modifying the database")
    run_cmd.add_argument("--force", action="store_true", help="Force reprocessing even if source SHA-256 hash was already ingested")
    run_cmd.add_argument("--batch-id", type=str, default=None, help="Optional explicit batch UUID for deterministic/Airflow runs")
    run_cmd.add_argument("--env-file", type=Path, default=None, help="Optional path to .env file")
    run_cmd.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        config = ETLConfig.from_env(env_file=args.env_file)
        result = run_pipeline(
            config=config,
            source_path=args.source,
            mode=args.mode,
            dry_run=args.dry_run,
            force=args.force,
            batch_id=args.batch_id,
            verbose=args.verbose,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") in ("SUCCESS", "PARTIAL_SUCCESS") else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
