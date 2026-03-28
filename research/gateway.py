from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor
import structlog

from research.config import OdooConfig, PostgresConfig
from research.tools.odoo_tools import OdooToolExecutor

logger = structlog.get_logger(__name__)

TOOL_TABLE_MAP: dict[str, list[str]] = {
    "get_order": ["pos_order", "pos_order_line"],
    "process_refund": ["pos_order", "account_move"],
    "cancel_order": ["pos_order"],
    "update_order_status": ["pos_order"],
    "apply_discount": ["pos_order", "pos_order_line"],
    "get_customer": ["res_partner", "res_partner_category", "res_partner_res_partner_category_rel"],
    "update_customer_tier": ["res_partner", "res_partner_category", "res_partner_res_partner_category_rel"],
    "log_interaction": ["mail_message"],
    "send_quote": ["sale_order", "sale_order_line"],
    "mark_opportunity_won": ["crm_lead"],
    "check_stock": ["stock_quant"],
    "update_inventory": ["stock_quant", "stock_move"],
    "transfer_stock": ["stock_picking", "stock_move", "stock_move_line"],
    "trigger_reorder": ["stock_warehouse_orderpoint"],
    "get_low_stock_items": ["stock_warehouse_orderpoint"],
    "get_attendance": ["hr_attendance"],
    "correct_attendance": ["hr_attendance"],
    "approve_leave": ["hr_leave"],
    "reject_leave": ["hr_leave", "mail_message"],
    "get_employee_info": ["hr_employee"],
    "create_ticket": ["helpdesk_ticket", "project_task"],
    "assign_ticket": ["helpdesk_ticket", "project_task"],
    "close_ticket": ["helpdesk_ticket", "project_task"],
    "escalate_ticket": ["helpdesk_ticket", "project_task", "mail_message"],
    "get_open_tickets": ["helpdesk_ticket", "project_task"],
}


@dataclass(slots=True)
class BehavioralRecord:
    step_id: int
    trajectory_id: str
    timestamp: str
    tool_name: str
    parameters: dict[str, Any]
    return_value: dict[str, Any]
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    state_delta: dict[str, Any]
    claim_pre: str | None
    claim_post: str | None


class ToolGateway:
    def __init__(
        self,
        odoo_config: OdooConfig | None = None,
        postgres_config: PostgresConfig | None = None,
    ) -> None:
        self.odoo_config = odoo_config or OdooConfig()
        self.postgres_config = postgres_config or PostgresConfig()
        self.executor = OdooToolExecutor(self.odoo_config)
        self.pg = psycopg2.connect(
            host=self.postgres_config.host,
            port=self.postgres_config.port,
            dbname=self.postgres_config.dbname,
            user=self.postgres_config.user,
            password=self.postgres_config.password,
        )
        self.pg.autocommit = False
        self._table_order_cache: dict[str, str] = {}
        self._init_audit_table()

    def _init_audit_table(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS halluci_audit (
            id BIGSERIAL PRIMARY KEY,
            step_id INTEGER NOT NULL,
            trajectory_id TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            tool_name TEXT NOT NULL,
            parameters JSONB NOT NULL,
            return_value JSONB NOT NULL,
            state_before JSONB NOT NULL,
            state_after JSONB NOT NULL,
            state_delta JSONB NOT NULL,
            claim_pre TEXT,
            claim_post TEXT,
            duration_ms INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_halluci_audit_trajectory_step
            ON halluci_audit (trajectory_id, step_id, id);
        """
        with self.pg.cursor() as cur:
            cur.execute(ddl)
        self.pg.commit()

    def execute(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        claim_pre: str | None = None,
        step_id: int = 0,
        trajectory_id: str = "",
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        tables = TOOL_TABLE_MAP.get(tool_name, [])
        state_before = self._snapshot(tables)

        t0 = time.perf_counter()
        try:
            tool_payload = self.executor.execute(tool_name, parameters)
            return_value = {"status": "success", "data": tool_payload}
        except Exception as exc:
            logger.exception("tool_execution_failed", tool_name=tool_name, parameters=parameters)
            return_value = {"status": "error", "message": str(exc)}

        state_after = self._snapshot(tables)
        state_delta = self._compute_delta(state_before, state_after)

        record = BehavioralRecord(
            step_id=step_id,
            trajectory_id=trajectory_id,
            timestamp=started_at.isoformat(),
            tool_name=tool_name,
            parameters=parameters,
            return_value=return_value,
            state_before=state_before,
            state_after=state_after,
            state_delta=state_delta,
            claim_pre=claim_pre,
            claim_post=None,
        )
        audit_id = self._write_audit(record, duration_ms=int((time.perf_counter() - t0) * 1000))
        return {
            **return_value,
            "audit_id": audit_id,
            "state_before": state_before,
            "state_after": state_after,
            "state_delta": state_delta,
        }

    def set_claim_post(
        self,
        step_id: int,
        claim_post: str,
        trajectory_id: str | None = None,
        audit_id: int | None = None,
    ) -> None:
        with self.pg.cursor() as cur:
            if audit_id is not None:
                cur.execute(
                    "UPDATE halluci_audit SET claim_post = %s WHERE id = %s",
                    (claim_post, audit_id),
                )
            else:
                if trajectory_id:
                    cur.execute(
                        """
                        UPDATE halluci_audit
                           SET claim_post = %s
                         WHERE id = (
                            SELECT id
                              FROM halluci_audit
                             WHERE step_id = %s AND trajectory_id = %s
                             ORDER BY id DESC
                             LIMIT 1
                         )
                        """,
                        (claim_post, step_id, trajectory_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE halluci_audit
                           SET claim_post = %s
                         WHERE id = (
                            SELECT id
                              FROM halluci_audit
                             WHERE step_id = %s
                             ORDER BY id DESC
                             LIMIT 1
                         )
                        """,
                        (claim_post, step_id),
                    )
        self.pg.commit()

    def close(self) -> None:
        self.pg.close()

    def _write_audit(self, record: BehavioralRecord, duration_ms: int) -> int:
        with self.pg.cursor() as cur:
            cur.execute(
                """
                INSERT INTO halluci_audit (
                    step_id,
                    trajectory_id,
                    timestamp,
                    tool_name,
                    parameters,
                    return_value,
                    state_before,
                    state_after,
                    state_delta,
                    claim_pre,
                    claim_post,
                    duration_ms
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    record.step_id,
                    record.trajectory_id,
                    record.timestamp,
                    record.tool_name,
                    Json(record.parameters),
                    Json(record.return_value),
                    Json(record.state_before),
                    Json(record.state_after),
                    Json(record.state_delta),
                    record.claim_pre,
                    record.claim_post,
                    duration_ms,
                ),
            )
            audit_id = int(cur.fetchone()[0])
        self.pg.commit()
        return audit_id

    def _snapshot(self, tables: list[str]) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        if not tables:
            return snapshot
        with self.pg.cursor(cursor_factory=RealDictCursor) as cur:
            for table in tables:
                try:
                    order_by = self._row_order_column(cur, table)
                    query = sql.SQL("SELECT * FROM {} ORDER BY {} DESC NULLS LAST LIMIT 100").format(
                        sql.Identifier(table),
                        sql.Identifier(order_by),
                    )
                    cur.execute(query)
                    snapshot[table] = [self._coerce_jsonable(dict(row)) for row in cur.fetchall()]
                except Exception as exc:
                    self.pg.rollback()
                    snapshot[table] = {"error": str(exc)}
        return snapshot

    def _row_order_column(self, cur: RealDictCursor, table: str) -> str:
        cached = self._table_order_cache.get(table)
        if cached:
            return cached
        cur.execute(
            """
            SELECT column_name
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = %s
            """,
            (table,),
        )
        columns = {row["column_name"] for row in cur.fetchall()}
        for candidate in ("write_date", "create_date", "id"):
            if candidate in columns:
                self._table_order_cache[table] = candidate
                return candidate
        self._table_order_cache[table] = "id"
        return "id"

    def _compute_delta(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        delta: dict[str, Any] = {}
        for table in sorted(set(before) | set(after)):
            before_rows = before.get(table, [])
            after_rows = after.get(table, [])
            if isinstance(before_rows, dict) or isinstance(after_rows, dict):
                continue
            before_by_id = {row["id"]: row for row in before_rows if isinstance(row, dict) and "id" in row}
            after_by_id = {row["id"]: row for row in after_rows if isinstance(row, dict) and "id" in row}
            changes: list[dict[str, Any]] = []
            for row_id in sorted(set(before_by_id) | set(after_by_id)):
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

    def _coerce_jsonable(self, payload: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(payload, default=str))
