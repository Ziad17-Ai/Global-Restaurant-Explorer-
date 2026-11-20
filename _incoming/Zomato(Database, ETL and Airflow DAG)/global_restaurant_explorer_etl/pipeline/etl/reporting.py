"""Execution and Data Quality report generator (JSON + Markdown)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple


def write_execution_reports(reports_dir: Path, batch_id: str, report_data: Dict[str, Any]) -> Tuple[Path, Path]:
    """Persist structured JSON execution report and human-readable Markdown DQ report."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"etl_report_{batch_id}.json"
    md_path = reports_dir / f"dq_report_{batch_id}.md"

    json_path.write_text(json.dumps(report_data, indent=2, default=str), encoding="utf-8")

    dq = report_data.get("data_quality", {})
    sev = dq.get("issues_by_severity", {})
    by_type = dq.get("issues_by_type", {})
    silver = report_data.get("silver_load", {})
    gold = report_data.get("gold_layer", {})
    timings = report_data.get("timings_ms", {})

    lines = [
        f"# ETL Data Quality & Execution Report — Batch `{batch_id}`",
        "",
        f"**Status:** `{report_data.get('status')}`  ",
        f"**Mode:** `{report_data.get('mode')}` | **Dry Run:** `{report_data.get('dry_run')}`  ",
        f"**Source File:** `{report_data.get('source_file_name')}` (`{report_data.get('source_file_hash')}`)  ",
        f"**Database Dialect:** `{report_data.get('db_dialect')}` | **Storage Backend:** `{report_data.get('storage_backend')}`",
        "",
        "## 1. Record Processing Summary",
        "",
        "| Metric | Count |",
        "| :--- | ---: |",
        f"| Extracted Rows | {report_data.get('extracted_rows', 0):,} |",
        f"| Accepted Rows | {report_data.get('accepted_rows', 0):,} |",
        f"| Quarantined (Rejected) Rows | {report_data.get('rejected_rows', 0):,} |",
        f"| Silver Restaurants Inserted | {silver.get('restaurants_inserted', 0):,} |",
        f"| Silver Restaurants Updated | {silver.get('restaurants_updated', 0):,} |",
        f"| Silver Restaurants Unchanged | {silver.get('restaurants_unchanged', 0):,} |",
        "",
        "## 2. Data Quality Findings",
        "",
        "| Severity | Count |",
        "| :--- | ---: |",
        f"| CRITICAL | {sev.get('CRITICAL', 0):,} |",
        f"| ERROR | {sev.get('ERROR', 0):,} |",
        f"| WARNING | {sev.get('WARNING', 0):,} |",
        f"| INFO | {sev.get('INFO', 0):,} |",
        "",
    ]

    if by_type:
        lines.extend([
            "### Issues by Type",
            "",
            "| Issue Type | Count |",
            "| :--- | ---: |",
        ])
        for itype, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"| `{itype}` | {cnt:,} |")
        lines.append("")

    if gold.get("views_verified"):
        lines.extend([
            "## 3. Gold Layer Verification",
            "",
            "| View Name | Row Count | Query Latency (ms) |",
            "| :--- | ---: | ---: |",
        ])
        for vname, vcnt in gold["views_verified"].items():
            lat = gold.get("query_timings_ms", {}).get(vname, 0.0)
            lines.append(f"| `{vname}` | {vcnt:,} | {lat:.2f} |")
        lines.append("")

    if timings:
        lines.extend([
            "## 4. Stage Execution Timings",
            "",
            "| Stage | Duration (ms) |",
            "| :--- | ---: |",
        ])
        for stage_k, dur in timings.items():
            lines.append(f"| `{stage_k}` | {dur:.2f} |")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
