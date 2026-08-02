"""
Halluci-Action Evaluator — Pass 2

Rule-based action extraction from trajectory JSON.

Pass 2 reads the existing step-centric trajectory format and emits one row per
tool call/action. It intentionally does not use an LLM: tool names, parameters,
status, and result data are already structured in the trajectory JSON.

Output schema per action:
{
    "action_id":          int,   # 1-indexed across the whole trajectory
    "trajectory_id":      str,
    "step_id":            int,
    "action_index":       int,   # 1-indexed within the step
    "call_id":            str | None,
    "tool_name":          str,
    "parameters":         dict,
    "parameters_summary": str,
    "status":             str,
    "result_summary":     str,
    "result_data":        dict | list | None,
}
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import click


# ---------------------------------------------------------------------------
# Loading and small formatting helpers
# ---------------------------------------------------------------------------

def load_trajectory(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _format_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    return str(value)


def format_parameters(parameters: dict[str, Any] | None) -> str:
    if not parameters:
        return "(empty)"
    return ", ".join(f"{key}={_format_scalar(value)}" for key, value in parameters.items())


def _first_item(data: dict[str, Any], list_key: str) -> Any:
    values = data.get(list_key)
    if isinstance(values, list) and values:
        return values[0]
    return None


def _nameish(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("name", "display_name", "default_code"):
            if value.get(key):
                return str(value[key])
        if value.get("id") is not None:
            return f"id={value['id']}"
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return str(value[1])
    if isinstance(value, str):
        return value
    return None


def _join_parts(*parts: str | None) -> str:
    return ", ".join(part for part in parts if part)


def _summarize_record(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "id",
        "name",
        "state",
        "status",
        "email",
        "phone",
        "credit_limit",
        "amount_total",
        "amount_residual",
        "list_price",
        "old_price",
        "new_price",
        "invoice_status",
        "payment_state",
        "on_hand",
        "reserved",
        "available",
        "qty_available",
        "virtual_available",
        "success",
    ):
        if key in data:
            parts.append(f"{key}={_format_scalar(data[key])}")
    stock = data.get("stock")
    if isinstance(stock, dict):
        for key in ("on_hand", "reserved", "available"):
            if key in stock:
                parts.append(f"stock.{key}={_format_scalar(stock[key])}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Tool-result summarization
# ---------------------------------------------------------------------------

def summarize_result(tool_name: str, status: str, data: Any, message: str | None = None) -> str:
    if status and status != "success":
        return _join_parts(f"status={_format_scalar(status)}", message) or status

    if data in ({}, [], None):
        return "(empty)"

    if not isinstance(data, dict):
        if isinstance(data, list):
            return f"items_count={len(data)}"
        return _format_scalar(data)

    if tool_name == "search_customers":
        count = data.get("count", len(data.get("customers", [])) if isinstance(data.get("customers"), list) else None)
        first = _first_item(data, "customers")
        first_bits = _summarize_record(first) if isinstance(first, dict) else ""
        return _join_parts(f"customers_count={count}", f"first: {first_bits}" if first_bits else None)

    if tool_name == "search_sale_orders":
        count = data.get("count", len(data.get("orders", [])) if isinstance(data.get("orders"), list) else None)
        first = _first_item(data, "orders")
        first_bits = _summarize_record(first) if isinstance(first, dict) else ""
        return _join_parts(f"orders_count={count}", f"first: {first_bits}" if first_bits else None)

    if tool_name == "search_products":
        count = data.get("count", len(data.get("products", [])) if isinstance(data.get("products"), list) else None)
        first = _first_item(data, "products")
        first_bits = _summarize_record(first) if isinstance(first, dict) else ""
        return _join_parts(f"products_count={count}", f"first: {first_bits}" if first_bits else None)

    if tool_name == "search_invoices":
        count = data.get("count", len(data.get("invoices", [])) if isinstance(data.get("invoices"), list) else None)
        first = _first_item(data, "invoices")
        first_bits = _summarize_record(first) if isinstance(first, dict) else ""
        return _join_parts(f"invoices_count={count}", f"first: {first_bits}" if first_bits else None)

    if tool_name in {"get_sale_order", "confirm_sale_order", "create_sale_order"}:
        return _summarize_record(data) or "(empty)"

    if tool_name in {"get_customer", "create_customer"}:
        return _summarize_record(data) or "(empty)"

    if tool_name in {"get_product", "check_stock", "update_product_price", "update_inventory"}:
        product = _nameish(data.get("product")) or _nameish(data.get("product_id"))
        base = _summarize_record(data)
        return _join_parts(base, f"product={_format_scalar(product)}" if product else None) or "(empty)"

    if tool_name == "log_interaction":
        return _summarize_record(data) or _join_parts(
            f"message_id={_format_scalar(data.get('message_id'))}" if data.get("message_id") is not None else None,
            f"success={_format_scalar(data.get('success'))}" if data.get("success") is not None else None,
        ) or "(empty)"

    # Generic fallback: count common list payloads and show a few scalar fields.
    for key, value in data.items():
        if isinstance(value, list):
            first_bits = _summarize_record(value[0]) if value and isinstance(value[0], dict) else ""
            label = key[:-1] if key.endswith("s") else key
            return _join_parts(
                f"{key}_count={len(value)}",
                f"first_{label}: {first_bits}" if first_bits else None,
            )

    return _summarize_record(data) or "(empty)"


# ---------------------------------------------------------------------------
# PASS 2 extraction
# ---------------------------------------------------------------------------

def _index_results_by_call_id(tool_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for result in tool_results:
        call_id = result.get("call_id")
        if call_id:
            indexed[call_id] = result
    return indexed


def _result_for_call(
    tool_call: dict[str, Any],
    tool_results: list[dict[str, Any]],
    results_by_call_id: dict[str, dict[str, Any]],
    action_index: int,
) -> dict[str, Any] | None:
    call_id = tool_call.get("call_id")
    if call_id and call_id in results_by_call_id:
        return results_by_call_id[call_id]
    if action_index < len(tool_results):
        return tool_results[action_index]
    return None


def extract_actions(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    trajectory_id = trajectory.get("trajectory_id", "")

    for step in trajectory.get("steps", []):
        step_id = step.get("step_id")
        tool_calls = step.get("tool_calls") or []
        tool_results = step.get("tool_results") or []
        results_by_call_id = _index_results_by_call_id(tool_results)

        for zero_index, tool_call in enumerate(tool_calls):
            result = _result_for_call(tool_call, tool_results, results_by_call_id, zero_index)
            gateway_result = (result or {}).get("gateway_result") or {}

            tool_name = tool_call.get("tool_name") or (result or {}).get("tool_name") or ""
            parameters = tool_call.get("parameters")
            if parameters is None:
                parameters = (result or {}).get("parameters") or {}

            status = gateway_result.get("status") or ("missing_result" if result is None else "unknown")
            data = gateway_result.get("data")
            message = gateway_result.get("message") or gateway_result.get("error")

            actions.append(
                {
                    "action_id": len(actions) + 1,
                    "trajectory_id": trajectory_id,
                    "step_id": step_id,
                    "action_index": zero_index + 1,
                    "call_id": tool_call.get("call_id") or (result or {}).get("call_id"),
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "parameters_summary": format_parameters(parameters),
                    "status": status,
                    "result_summary": summarize_result(tool_name, status, data, message),
                    "result_data": data,
                }
            )

    return actions


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def default_output_path(input_path: Path, output_dir: Path | None, fmt: str) -> Path:
    suffix = "csv" if fmt == "csv" else "json"
    directory = output_dir if output_dir else input_path.parent / "evaluations"
    return directory / f"{input_path.stem}__pass2.{suffix}"


def save_actions(actions: list[dict[str, Any]], output_path: Path, fmt: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output_path.write_text(json.dumps(actions, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    fieldnames = [
        "action_id",
        "trajectory_id",
        "step_id",
        "action_index",
        "call_id",
        "tool_name",
        "parameters_summary",
        "status",
        "result_summary",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for action in actions:
            writer.writerow({key: action.get(key) for key in fieldnames})


def print_action_summary(actions: list[dict[str, Any]]) -> None:
    click.echo(f"\n{'=' * 88}")
    click.echo(f"PASS 2 RESULTS  ({len(actions)} actions)")
    click.echo(f"{'=' * 88}")
    click.echo(f"{'id':>3}  {'step':>4}  {'tool_name':24s}  {'status':10s}  result_summary")
    click.echo("-" * 88)
    for action in actions:
        result = action["result_summary"]
        if len(result) > 90:
            result = result[:87] + "..."
        click.echo(
            f"{action['action_id']:>3}  "
            f"{action['step_id']:>4}  "
            f"{action['tool_name'][:24]:24s}  "
            f"{action['status'][:10]:10s}  "
            f"{result}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Pass 2 evaluator: rule-based tool/action extraction."""


@cli.command("run")
@click.option("--trajectory", "traj_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to a trajectory JSON file.")
@click.option("--output", "-o", type=click.Path(path_type=Path),
              help="Output file path. Defaults to <trajectory_dir>/evaluations/<stem>__pass2.json.")
@click.option("--output-dir", type=click.Path(path_type=Path),
              help="Output directory when --output is omitted.")
@click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json", show_default=True,
              help="Output format.")
def run_cmd(traj_path: Path, output: Path | None, output_dir: Path | None, fmt: str) -> None:
    """Extract action rows from one trajectory JSON."""
    trajectory = load_trajectory(traj_path)
    actions = extract_actions(trajectory)
    output_path = output or default_output_path(traj_path, output_dir, fmt)
    save_actions(actions, output_path, fmt)

    click.echo(f"Task:    {trajectory.get('task', '?')}")
    click.echo(f"Steps:   {len(trajectory.get('steps', []))}")
    click.echo(f"Actions: {len(actions)}")
    click.echo(f"Saved → {output_path}")
    print_action_summary(actions)


@cli.command("batch")
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output-dir", type=click.Path(path_type=Path),
              help="Output directory. Defaults to <input_dir>/evaluations.")
@click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json", show_default=True,
              help="Output format.")
def batch_cmd(input_dir: Path, output_dir: Path | None, fmt: str) -> None:
    """Extract Pass 2 action rows for every trajectory JSON in a directory."""
    files = sorted(input_dir.glob("*.json"))
    if not files:
        raise click.ClickException(f"No JSON files found in {input_dir}")

    out_dir = output_dir or input_dir / "evaluations"
    for path in files:
        trajectory = load_trajectory(path)
        actions = extract_actions(trajectory)
        output_path = default_output_path(path, out_dir, fmt)
        save_actions(actions, output_path, fmt)
        click.echo(f"{path.name}: {len(actions)} actions → {output_path}")


@cli.command("show")
@click.argument("pass2_output", type=click.Path(exists=True, path_type=Path))
def show_cmd(pass2_output: Path) -> None:
    """Pretty-print a saved Pass 2 JSON output."""
    actions = json.loads(pass2_output.read_text(encoding="utf-8"))
    print_action_summary(actions)


if __name__ == "__main__":
    cli()
