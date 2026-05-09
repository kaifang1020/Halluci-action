"""
Post-processing script to convert step-centric trajectory data to action-centric format.

Usage:
    python -m research.post_process --trajectory-id <id>
    python -m research.post_process --json-file <path>
    python -m research.post_process --latest
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import psycopg2
from psycopg2.extras import RealDictCursor

from research.config import ExperimentConfig, PostgresConfig

RUNS_DIR = ExperimentConfig().runs_dir


def trajectory_dirs() -> list[Path]:
    dirs = [RUNS_DIR / "trajectories"]
    if RUNS_DIR not in dirs:
        dirs.append(RUNS_DIR)
    return [path for path in dirs if path.exists()]


def is_main_trajectory_path(path: Path) -> bool:
    return (
        path.suffix == ".json"
        and not path.name.endswith("__audit.json")
        and not path.name.endswith("_action_centric.json")
    )


@dataclass
class ActionCentricUnit:
    """One tool call = one action unit."""
    action_id: str
    trajectory_id: str
    step_id: int
    action_index: int
    timestamp: float

    raw_response: dict[str, Any]
    cot_text: str  # For now: full assistant_text (manual segmentation later)
    claim_pre: str | None
    claim_post: str | None

    tool_name: str
    tool_params: dict[str, Any]
    tool_result: dict[str, Any]

    state_before: dict[str, Any]
    state_after: dict[str, Any]
    state_delta: dict[str, Any]


def load_trajectory_json(json_path: Path) -> dict[str, Any]:
    """Load a trajectory JSON file from runs directory."""
    return json.loads(json_path.read_text(encoding="utf-8"))


def load_audit_sidecar(json_path: Path, trajectory_json: dict[str, Any]) -> list[dict[str, Any]]:
    audit_file = trajectory_json.get("audit_file")
    if not audit_file:
        return []
    audit_path = (json_path.parent / audit_file).resolve()
    if not audit_path.exists():
        return []
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    records = audit_payload.get("records") or []
    return records if isinstance(records, list) else []


def find_latest_trajectory() -> Path:
    """Find the most recent trajectory JSON file."""
    if not RUNS_DIR.exists():
        raise FileNotFoundError(f"Runs directory not found: {RUNS_DIR}")
    json_files = sorted(
        (
            path
            for directory in trajectory_dirs()
            for path in directory.glob("*.json")
            if is_main_trajectory_path(path)
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not json_files:
        raise FileNotFoundError(f"No trajectory JSON files found in {RUNS_DIR}")
    return json_files[0]


def query_audit_records(
    pg_config: PostgresConfig,
    trajectory_id: str,
) -> list[dict[str, Any]]:
    """Query halluci_audit table for all records matching trajectory_id."""
    conn = psycopg2.connect(
        host=pg_config.host,
        port=pg_config.port,
        dbname=pg_config.dbname,
        user=pg_config.user,
        password=pg_config.password,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, step_id, trajectory_id, timestamp, tool_name,
                       parameters, return_value, state_before, state_after,
                       state_delta, claim_pre, claim_post, duration_ms
                FROM halluci_audit
                WHERE trajectory_id = %s
                ORDER BY step_id, id
                """,
                (trajectory_id,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def convert_to_action_centric(
    trajectory_json: dict[str, Any],
    audit_records: list[dict[str, Any]] | None = None,
) -> list[ActionCentricUnit]:
    """
    Convert step-centric trajectory to action-centric units.

    If audit_records is provided (from DB), use those for state snapshots.
    Otherwise, extract from the JSON tool_results (which contain state data from gateway).
    """
    trajectory_id = trajectory_json["trajectory_id"]
    steps = trajectory_json["steps"]

    # Index audit records by explicit sidecar index and by (step_id, order).
    audit_by_record_index: dict[int, dict[str, Any]] = {}
    audit_index: dict[tuple[int, int], dict[str, Any]] = {}
    if audit_records:
        step_counters: dict[int, int] = {}
        for record_index, record in enumerate(audit_records):
            audit_by_record_index[record_index] = record
            step_id = record["step_id"]
            idx = step_counters.get(step_id, 0)
            audit_index[(step_id, idx)] = record
            step_counters[step_id] = idx + 1

    action_units: list[ActionCentricUnit] = []

    for step in steps:
        step_id = step["step_id"]
        assistant_text = step.get("assistant_text", "")
        raw_response = step.get("raw_response", {})
        step_claim_pre = step.get("claim_pre")
        step_claim_post = step.get("claim_post")
        tool_results = step.get("tool_results", [])

        for action_index, tool_result in enumerate(tool_results):
            # Generate action_id
            action_id = f"{trajectory_id}_step{step_id}_action{action_index}"

            # Try to get audit record from DB for richer state data
            audit_record_index = tool_result.get("audit_record_index")
            audit_record = (
                audit_by_record_index.get(audit_record_index)
                if isinstance(audit_record_index, int)
                else None
            )
            audit_record = audit_record or audit_index.get((step_id, action_index))

            if audit_record:
                # Use DB record (has full state snapshots)
                full_gateway_result = audit_record.get("gateway_result", {})
                state_before = audit_record.get("state_before") or full_gateway_result.get("state_before", {})
                state_after = audit_record.get("state_after") or full_gateway_result.get("state_after", {})
                state_delta = audit_record.get("state_delta") or full_gateway_result.get("state_delta", {})
                audit_timestamp = audit_record.get("timestamp")
                timestamp = (
                    audit_timestamp.timestamp()
                    if hasattr(audit_timestamp, "timestamp")
                    else float(audit_timestamp)
                    if audit_timestamp
                    else datetime.now(timezone.utc).timestamp()
                )
                # DB may have more accurate claim_pre/post
                claim_pre = audit_record.get("claim_pre") or step_claim_pre
                claim_post = audit_record.get("claim_post") or step_claim_post
            else:
                # Fall back to JSON data (gateway returns state in tool_result)
                gateway_result = tool_result.get("gateway_result", {})
                state_before = gateway_result.get("state_before", {})
                state_after = gateway_result.get("state_after", {})
                state_delta = gateway_result.get("state_delta", {})
                timestamp = datetime.now(timezone.utc).timestamp()
                claim_pre = step_claim_pre
                claim_post = step_claim_post

            # Extract tool execution data
            tool_name = tool_result.get("tool_name", "")
            tool_params = tool_result.get("parameters", {})

            gateway_result = tool_result.get("result") or tool_result.get("gateway_result", {})
            # Remove state fields from tool_result to keep it clean
            tool_result_clean = {
                "status": gateway_result.get("status"),
                "data": gateway_result.get("data"),
            }
            if gateway_result.get("message"):
                tool_result_clean["message"] = gateway_result["message"]

            unit = ActionCentricUnit(
                action_id=action_id,
                trajectory_id=trajectory_id,
                step_id=step_id,
                action_index=action_index,
                timestamp=timestamp,
                raw_response=raw_response,
                cot_text=assistant_text,  # Full text for now; manual segmentation later
                claim_pre=claim_pre,
                claim_post=claim_post,
                tool_name=tool_name,
                tool_params=tool_params,
                tool_result=tool_result_clean,
                state_before=state_before,
                state_after=state_after,
                state_delta=state_delta,
            )
            action_units.append(unit)

    return action_units


def export_action_centric(
    units: list[ActionCentricUnit],
    output_path: Path,
) -> None:
    """Export action-centric units to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(unit) for unit in units]
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


@click.command()
@click.option("--trajectory-id", help="Trajectory ID to process (queries DB)")
@click.option("--json-file", type=click.Path(exists=True, path_type=Path), help="Path to trajectory JSON file")
@click.option("--latest", is_flag=True, help="Process the most recent trajectory")
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Output file path")
@click.option("--use-db/--no-db", default=True, help="Whether to query halluci_audit for state data")
@click.option("--pg-host", default=None)
@click.option("--pg-port", default=None, type=int)
@click.option("--pg-database", default=None)
@click.option("--pg-user", default=None)
@click.option("--pg-password", default=None)
def main(
    trajectory_id: str | None,
    json_file: Path | None,
    latest: bool,
    output: Path | None,
    use_db: bool,
    pg_host: str | None,
    pg_port: int | None,
    pg_database: str | None,
    pg_user: str | None,
    pg_password: str | None,
) -> None:
    """Convert step-centric trajectory to action-centric format."""
    # Determine input source
    if json_file:
        input_path = json_file
    elif latest:
        input_path = find_latest_trajectory()
        click.echo(f"Using latest trajectory: {input_path.name}")
    elif trajectory_id:
        # Try to find JSON file matching trajectory_id
        candidates = [
            path
            for directory in trajectory_dirs()
            for path in directory.glob(f"*{trajectory_id}*.json")
            if is_main_trajectory_path(path)
        ]
        if not candidates:
            raise click.ClickException(f"No JSON file found for trajectory_id: {trajectory_id}")
        input_path = candidates[0]
    else:
        raise click.ClickException("Provide --json-file, --latest, or --trajectory-id")

    # Load trajectory JSON
    trajectory_json = load_trajectory_json(input_path)
    traj_id = trajectory_json["trajectory_id"]
    click.echo(f"Processing trajectory: {traj_id}")

    # Prefer sidecar audit JSON when present; fall back to DB.
    audit_records = load_audit_sidecar(input_path, trajectory_json)
    if audit_records:
        click.echo(f"Found {len(audit_records)} audit records in sidecar JSON")
    if use_db:
        default_pg = PostgresConfig()
        pg_config = PostgresConfig(
            host=pg_host or default_pg.host,
            port=pg_port or default_pg.port,
            dbname=pg_database or default_pg.dbname,
            user=pg_user or default_pg.user,
            password=pg_password or default_pg.password,
        )
        try:
            db_audit_records = query_audit_records(pg_config, traj_id)
            if db_audit_records:
                audit_records = db_audit_records
            click.echo(f"Found {len(db_audit_records)} audit records in DB")
        except Exception as exc:
            click.echo(f"Warning: Could not query DB ({exc}), using JSON data only")

    # Convert to action-centric
    units = convert_to_action_centric(trajectory_json, audit_records)
    click.echo(f"Generated {len(units)} action-centric units")

    # Determine output path
    if output is None:
        output = input_path.parent / f"{input_path.stem}_action_centric.json"

    # Export
    export_action_centric(units, output)
    click.echo(f"Saved to: {output}")

    # Print summary
    if units:
        click.echo("\n--- Sample Action Unit ---")
        sample = asdict(units[0])
        # Truncate long fields for display
        if len(str(sample.get("raw_response", ""))) > 200:
            sample["raw_response"] = "... (truncated)"
        if len(str(sample.get("cot_text", ""))) > 200:
            sample["cot_text"] = sample["cot_text"][:200] + "..."
        click.echo(json.dumps(sample, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
