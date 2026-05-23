#!/usr/bin/env python3
"""Aggregate run_experiments_v1 summary jsonls into a Markdown comparison report.

Scans research/experiments_v1/run_summaries/*.jsonl, filters records whose
``timestamp`` is >= --since, and writes a Markdown table comparing each
(agent, model) pair task by task.

Schema of each summary record (see scripts/run_experiments_v1.py):
    timestamp, mode, chain, task_id, domain, agent, model,
    status, duration_sec, runs_dir, trajectories
Status values: success, failed, timeout, skipped_existing, reset_or_furnish_failed.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SUMMARY_DIR = ROOT_DIR / "research" / "experiments_v1" / "run_summaries"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default="",
        help="UTC timestamp YYYYMMDDTHHMMSSZ; only records at or after this are included.",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Markdown output path.",
    )
    parser.add_argument(
        "--summary-dir",
        default=SUMMARY_DIR,
        type=Path,
        help="Directory of *.jsonl summary files (default: research/experiments_v1/run_summaries).",
    )
    return parser.parse_args()


def load_records(summary_dir: Path, since: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not summary_dir.exists():
        return records
    for path in sorted(summary_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since and rec.get("timestamp", "") < since:
                    continue
                records.append(rec)
    return records


def pair_key(rec: dict[str, Any]) -> tuple[str, str]:
    return (rec.get("agent") or "?", rec.get("model") or "?")


def task_key(rec: dict[str, Any]) -> tuple[str, str | None]:
    return (rec.get("task_id") or "?", rec.get("chain"))


def status_cell(rec: dict[str, Any]) -> str:
    status = rec.get("status", "?")
    dur = rec.get("duration_sec")
    if status == "success":
        return f"OK {dur:.0f}s" if isinstance(dur, (int, float)) else "OK"
    if status == "failed":
        return f"FAIL {dur:.0f}s" if isinstance(dur, (int, float)) else "FAIL"
    if status == "timeout":
        return f"T/O {dur:.0f}s" if isinstance(dur, (int, float)) else "T/O"
    if status == "skipped_existing":
        return "skip"
    if status == "reset_or_furnish_failed":
        return "RESET"
    return status


def build_overview(records: list[dict[str, Any]]) -> list[str]:
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "ok": 0, "fail": 0, "timeout": 0, "skip": 0, "reset": 0, "runtime": 0.0}
    )
    for rec in records:
        b = buckets[pair_key(rec)]
        status = rec.get("status", "")
        b["total"] += 1
        if status == "success":
            b["ok"] += 1
        elif status == "failed":
            b["fail"] += 1
        elif status == "timeout":
            b["timeout"] += 1
        elif status == "skipped_existing":
            b["skip"] += 1
        elif status == "reset_or_furnish_failed":
            b["reset"] += 1
        dur = rec.get("duration_sec")
        if isinstance(dur, (int, float)):
            b["runtime"] += float(dur)

    if not buckets:
        return ["_(no records)_"]
    lines = [
        "| Agent | Model | Total | OK | FAIL | T/O | Skip | Reset-fail | Runtime |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for (agent, model), b in sorted(buckets.items()):
        lines.append(
            f"| {agent} | {model} | {b['total']} | {b['ok']} | {b['fail']} | "
            f"{b['timeout']} | {b['skip']} | {b['reset']} | {b['runtime']:.0f}s |"
        )
    return lines


def build_matrix(records: list[dict[str, Any]]) -> list[str]:
    pairs: list[tuple[str, str]] = sorted({pair_key(r) for r in records})
    if not pairs:
        return ["_(no records)_"]

    by_task: dict[tuple[str, str | None], dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
    for rec in records:
        by_task[task_key(rec)][pair_key(rec)] = rec

    def task_sort_key(item: tuple[str, str | None]) -> tuple[int, str, str]:
        task_id, chain = item
        return (0 if chain is None else 1, chain or "", task_id)

    header_cells = [f"{a}/{m}" for a, m in pairs]
    lines = [
        "| Task | Chain | " + " | ".join(header_cells) + " |",
        "|---|---|" + "|".join(["---"] * len(pairs)) + "|",
    ]
    for key in sorted(by_task.keys(), key=task_sort_key):
        task_id, chain = key
        cells = []
        for pair in pairs:
            rec = by_task[key].get(pair)
            cells.append(status_cell(rec) if rec else "—")
        lines.append(f"| {task_id} | {chain or '-'} | " + " | ".join(cells) + " |")
    return lines


def build_failures(records: list[dict[str, Any]]) -> list[str]:
    fails = [
        r
        for r in records
        if r.get("status") in {"failed", "timeout", "reset_or_furnish_failed"}
    ]
    if not fails:
        return ["_(no failures)_"]
    fails.sort(key=lambda r: (pair_key(r), r.get("chain") or "", r.get("task_id") or ""))
    lines = []
    current_pair: tuple[str, str] | None = None
    for rec in fails:
        pair = pair_key(rec)
        if pair != current_pair:
            current_pair = pair
            lines.append("")
            lines.append(f"### {pair[0]} / {pair[1]}")
        chain = rec.get("chain")
        chain_str = f" (chain={chain})" if chain else ""
        dur = rec.get("duration_sec")
        dur_str = f", {dur:.0f}s" if isinstance(dur, (int, float)) else ""
        trajectories = rec.get("trajectories") or []
        traj_str = f" — last traj: `{trajectories[-1]}`" if trajectories else ""
        lines.append(
            f"- **{rec.get('task_id')}**{chain_str}: {rec.get('status')}{dur_str}{traj_str}"
        )
    return lines


def main() -> int:
    args = parse_args()
    records = load_records(args.summary_dir, args.since)

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sections: list[str] = [
        f"# Sweep summary ({now_iso})",
        "",
        f"- Summary dir: `{args.summary_dir}`",
        f"- Since: `{args.since or '(all records)'}`",
        f"- Records: {len(records)}",
        "",
        "## Overview by agent/model",
        "",
        *build_overview(records),
        "",
        "## Per-task comparison",
        "",
        *build_matrix(records),
        "",
        "## Failures",
        "",
        "Error logs live in `research/experiments_v1/run_summaries/logs/`.",
        *build_failures(records),
        "",
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {args.out} ({len(records)} records).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
