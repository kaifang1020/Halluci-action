"""
AppWorldGateway - a Postgres-free tool gateway for the AppWorld PoC.

This is the AppWorld analogue of ``research/gateway.py::ToolGateway``. It keeps the
same contract (``execute(...) -> {status, data/message, audit_id, state_before,
state_after, state_delta}``) so the rest of the Halluci-Action harness / judge sees an
identical shape, but:

  * There is NO Postgres. Audit records live IN MEMORY (a dict keyed by audit_id).
    ``claim_post`` is backfilled in memory by the driver (see ``set_claim_post``).
  * Per-tool ``state_delta`` is computed by snapshotting the relevant AppWorld app
    SQLite DBs before and after the call and diffing them by-id, reusing the exact
    INSERT / UPDATE / DELETE shape of ``ToolGateway._compute_delta``.

Why a full-DB snapshot instead of ``world.save_state`` diffing?
    ``world.save_state`` writes AppWorld's "changes" format, which is a *raw SQL
    statement log* (``.jsonl`` of ``(statement, params, executemany)``) - hard to diff
    by-id. Instead we ask AppWorld to dump the live in-memory DB to a real SQLite
    ``.db`` file (``save_local_dbs(format="full")`` -> SQLite ``.backup()``), read the
    rows, and diff them ourselves. The tool return value is always attached as primary
    evidence, so even if the snapshot fails the record is still useful (see the
    best-effort fallback + TODO in ``_snapshot``).
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

try:  # pragma: no cover - logging convenience only
    import structlog

    logger = structlog.get_logger(__name__)
except ModuleNotFoundError:  # pragma: no cover
    logger = logging.getLogger(__name__)

# Kept local (not imported from research.tools.appworld_tools) to avoid any import
# coupling; must stay in sync with AppWorld's function-calling separator.
APP_API_SEPARATOR = "__"

# Tables we never want in a state snapshot (SQLite / FTS internals, alembic, etc.).
_SNAPSHOT_TABLE_SKIP_SUBSTRINGS = ("_fts", "sqlite_", "alembic")
# NOTE: we deliberately do NOT cap the number of rows read per table. AppWorld's
# seed DBs are large (venmo.transactions ~8k rows, payment_requests ~6k), and a
# freshly-INSERTed row gets an id *above* that count. A blanket ``LIMIT`` with no
# ordering silently drops exactly those new rows, so ``state_before == state_after``
# and every write's ``state_delta`` comes back empty. Reading all rows is what makes
# the by-id diff correct; the (potentially large) full snapshots are used only for
# diffing and are never stored — ``execute`` keeps only a delta-scoped view (see
# ``_scoped_view``).


def compute_state_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """By-id INSERT / UPDATE / DELETE diff.

    Verbatim port of ``research.gateway.ToolGateway._compute_delta`` (kept as a
    standalone function so this module never imports psycopg2). ``before``/``after`` map
    a namespaced table name (``"<app>.<table>"``) to a list of row dicts; rows are keyed
    by their ``"id"`` column.
    """
    delta: dict[str, Any] = {}
    for table in sorted(set(before) | set(after)):
        before_rows = before.get(table, [])
        after_rows = after.get(table, [])
        if isinstance(before_rows, dict) or isinstance(after_rows, dict):
            # A snapshot error placeholder rather than a row list; skip.
            continue
        before_by_id = {row["id"]: row for row in before_rows if isinstance(row, dict) and "id" in row}
        after_by_id = {row["id"]: row for row in after_rows if isinstance(row, dict) and "id" in row}
        changes: list[dict[str, Any]] = []
        # Sort by str(id) so mixed/None id types never raise; ordering is cosmetic
        # (the by-id INSERT/UPDATE/DELETE shape is identical to ToolGateway._compute_delta).
        for row_id in sorted(set(before_by_id) | set(after_by_id), key=str):
            if row_id not in before_by_id:
                changes.append({"op": "INSERT", "id": row_id, "row": after_by_id[row_id]})
                continue
            if row_id not in after_by_id:
                changes.append({"op": "DELETE", "id": row_id, "row": before_by_id[row_id]})
                continue
            changed_fields = {
                key: {"before": before_by_id[row_id].get(key), "after": after_by_id[row_id].get(key)}
                for key in sorted(set(before_by_id[row_id]) | set(after_by_id[row_id]))
                if before_by_id[row_id].get(key) != after_by_id[row_id].get(key)
            }
            if changed_fields:
                changes.append({"op": "UPDATE", "id": row_id, "changed_fields": changed_fields})
        if changes:
            delta[table] = changes
    return delta


def _scoped_view(snapshot: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """Reduce a full snapshot to only the rows referenced by ``delta``.

    Returns ``{"<app>.<table>": [row_dict, ...]}`` containing, per changed table, only
    the rows whose id appears in the delta (INSERT/UPDATE/DELETE). Rows the snapshot
    doesn't contain (e.g. an INSERTed id is absent from ``state_before``) are simply
    omitted, which is correct — that asymmetry is exactly what the delta already
    encodes. A read-only call has an empty delta and therefore an empty view.
    """
    view: dict[str, Any] = {}
    for table, changes in delta.items():
        changed_ids = {change.get("id") for change in changes}
        rows = snapshot.get(table, [])
        if isinstance(rows, dict) or not isinstance(rows, list):
            # snapshot-error placeholder; nothing to scope.
            continue
        view[table] = [
            row for row in rows if isinstance(row, dict) and row.get("id") in changed_ids
        ]
    return view


class AppWorldGateway:
    def __init__(
        self,
        world: Any,
        executor: Any,
        snapshot_apps: list[str] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        world:      constructed ``appworld.AppWorld`` instance.
        executor:   ``AppWorldToolExecutor``.
        snapshot_apps:
            Apps to snapshot for the state delta. If None (default), the gateway
            snapshots only the app referenced by each tool's ``"<app>__..."`` prefix,
            which keeps the diff focused and cheap.
        """
        self.world = world
        self.executor = executor
        self.snapshot_apps = snapshot_apps
        self._audit_seq = 0
        # In-memory audit store (replaces the Postgres ``halluci_audit`` table).
        self.audit_records: dict[int, dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # Main entry point (same contract as ToolGateway.execute)
    # ------------------------------------------------------------------ #
    def execute(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        claim_pre: str | None = None,
        step_id: int = 0,
        trajectory_id: str = "",
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        app_names = self._apps_for(tool_name)
        state_before = self._snapshot(app_names)

        t0 = time.perf_counter()
        try:
            tool_payload = self.executor.execute(tool_name, parameters)
            return_value: dict[str, Any] = {"status": "success", "data": tool_payload}
        except Exception as exc:  # noqa: BLE001 - errors are recorded, not raised
            logger.exception("tool_execution_failed: %s", tool_name)
            return_value = {"status": "error", "message": str(exc)}

        state_after = self._snapshot(app_names)
        state_delta = compute_state_delta(state_before, state_after)

        # The full before/after snapshots can be multiple MB each (the entire app DB);
        # storing both in every audit record blew a 3-step task up to ~19 MB. The judge
        # only needs the rows that actually changed, so we keep a delta-scoped view:
        # for each changed table, the touched rows as they were before / after. This
        # mirrors native Halluci-Action's small scoped ``state_before``/``state_after``
        # (a read-only call → empty views, exactly like the Odoo side).
        scoped_before = _scoped_view(state_before, state_delta)
        scoped_after = _scoped_view(state_after, state_delta)

        self._audit_seq += 1
        audit_id = self._audit_seq
        self.audit_records[audit_id] = {
            "audit_id": audit_id,
            "step_id": step_id,
            "trajectory_id": trajectory_id,
            "timestamp": started_at.isoformat(),
            "tool_name": tool_name,
            "parameters": parameters,
            "return_value": return_value,
            "state_before": scoped_before,
            "state_after": scoped_after,
            "state_delta": state_delta,
            "claim_pre": claim_pre,
            "claim_post": None,  # backfilled in memory by the driver
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
        # Same dict shape the harness expects (audit-only keys are redacted by the
        # harness before the agent sees them).
        return {
            **return_value,
            "audit_id": audit_id,
            "state_before": scoped_before,
            "state_after": scoped_after,
            "state_delta": state_delta,
        }

    def set_claim_post(
        self,
        audit_id: int,
        claim_post: str,
        step_id: int | None = None,
        trajectory_id: str | None = None,
    ) -> None:
        """IN-MEMORY backfill of ``claim_post`` (no SQL).

        Signature mirrors ``ToolGateway.set_claim_post`` so the driver loop reads the
        same as ``harness._run_single``; extra positional args are accepted but unused.
        """
        record = self.audit_records.get(audit_id)
        if record is not None:
            record["claim_post"] = claim_post

    # ------------------------------------------------------------------ #
    # State snapshotting
    # ------------------------------------------------------------------ #
    def _apps_for(self, tool_name: str) -> list[str]:
        if self.snapshot_apps is not None:
            return list(self.snapshot_apps)
        if APP_API_SEPARATOR in tool_name:
            return [tool_name.split(APP_API_SEPARATOR, 1)[0]]
        return []

    def _snapshot(self, app_names: list[str]) -> dict[str, Any]:
        """Dump the live in-memory app DBs to disk and read their rows.

        Returns ``{"<app>.<table>": [row_dict, ...]}``. On any failure this degrades to
        a best-effort ``{"_snapshot_error": "..."}`` placeholder (decision 3): the tool
        return value remains the primary evidence, and ``compute_state_delta`` ignores
        non-list entries.
        """
        if not app_names:
            return {}
        try:
            # Imported lazily so this module is importable / py_compile-able without
            # AppWorld installed.
            from appworld.apps.api_lib import save_local_dbs
        except Exception as exc:  # noqa: BLE001
            # TODO(user): AppWorld not importable here (wrong venv?). state_delta is
            # unavailable; tool return value is still recorded as primary evidence.
            return {"_snapshot_error": f"appworld import failed: {exc}"}

        snapshot: dict[str, Any] = {}
        tmp_dir = tempfile.mkdtemp(prefix="halluci_appworld_state_")
        try:
            # save_local_dbs dumps the CURRENTLY-BOUND (live, in-memory) app engines to
            # real SQLite ``.db`` files via ``SQLModel.db.save("full", ...)`` ->
            # ``connection.backup(...)``. The ``from_db_home_path`` argument is required
            # but unused by the "full" path; we pass the world's in-memory home path.
            save_local_dbs(
                from_db_home_path=self.world.models_to_db_home_path,
                to_db_home_path=tmp_dir,
                format="full",
                app_names=list(app_names),
                delete_if_exists=True,
                skip_mandatory_apps=True,
                save_model_hashes=False,
                vaccum=False,
            )
            for app_name in app_names:
                db_path = os.path.join(tmp_dir, f"{app_name}.db")
                if not os.path.exists(db_path):
                    continue
                for table, rows in self._read_sqlite_tables(db_path).items():
                    snapshot[f"{app_name}.{table}"] = rows
        except Exception as exc:  # noqa: BLE001
            # TODO(user): if this fires, snapshotting the full DB is too heavy/fragile
            # for your task - consider snapshotting only the specific model tables the
            # tool touches (analogous to TOOL_TABLE_MAP in research/gateway.py).
            snapshot = {"_snapshot_error": str(exc)}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return snapshot

    @staticmethod
    def _read_sqlite_tables(db_path: str) -> dict[str, list[dict[str, Any]]]:
        """Read every real table from a SQLite file into row dicts."""
        tables_out: dict[str, list[dict[str, Any]]] = {}
        connection = sqlite3.connect(db_path)
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            table_names = [row[0] for row in cursor.fetchall()]
            for table in table_names:
                lowered = table.lower()
                if any(skip in lowered for skip in _SNAPSHOT_TABLE_SKIP_SUBSTRINGS):
                    continue
                try:
                    # No LIMIT: a newly-inserted row has a high id and must not be
                    # truncated out of the snapshot (see the note on the skip-list above).
                    cursor.execute(f'SELECT * FROM "{table}"')
                    columns = [description[0] for description in cursor.description]
                    tables_out[table] = [dict(zip(columns, row)) for row in cursor.fetchall()]
                except Exception:  # noqa: BLE001 - skip virtual/unsupported tables
                    continue
        finally:
            connection.close()
        return tables_out
