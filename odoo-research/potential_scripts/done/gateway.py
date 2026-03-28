# research/gateway.py

import json, time
import xmlrpc.client
import psycopg2
import psycopg2.extras
from dataclasses import dataclass, field
from typing import Optional, Any

# 每个 tool 需要监控哪些 PostgreSQL 表
# agent 调 process_refund → 监控 pos_order 表
TOOL_TABLE_MAP = {
    "get_order":           ["pos_order"],
    "process_refund":      ["pos_order", "account_move"],
    "cancel_order":        ["pos_order"],
    "apply_discount":      ["pos_order"],
    "get_customer":        ["res_partner"],
    "update_customer_tier":["res_partner"],
    "log_interaction":     ["crm_lead", "mail_message"],
    "check_stock":         ["stock_quant"],
    "update_inventory":    ["stock_quant", "stock_move"],
    "transfer_stock":      ["stock_picking", "stock_move"],
    "get_attendance":      ["hr_attendance"],
    "correct_attendance":  ["hr_attendance"],
    "approve_leave":       ["hr_leave"],
    "reject_leave":        ["hr_leave"],
    "create_ticket":       ["project_task"],
    "assign_ticket":       ["project_task"],
    "close_ticket":        ["project_task"],
}

class ToolGateway:
    def __init__(self):
        # ── 连接 Odoo JSON-RPC ────────────────────────────────
        url = "http://localhost:8069"
        db, user, pw = "odoo_research", "admin", "admin"
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        self.uid = common.authenticate(db, user, pw, {})
        self.odoo = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
        self._odoo_args = (db, self.uid, pw)

        # ── 直连 PostgreSQL（用来做 state snapshot）────────────
        # 注意：这是绕过 Odoo ORM 直接读表
        # 只用来读数据（SELECT），不直接写业务数据
        self.pg = psycopg2.connect(
            host="localhost", port=5432,
            dbname="odoo_research",
            user="odoo", password="odoo_pw"
        )
        self.pg.autocommit = False
        self._init_audit_table()

    # ═══════════════════════════════════════════════════════════
    # 主入口：agent 的每个 tool call 都经过这里
    # ═══════════════════════════════════════════════════════════
    def execute(self,
                tool_name: str,
                parameters: dict,
                claim_pre: Optional[str] = None,
                step_id: int = 0,
                trajectory_id: str = "") -> dict:

        tables = TOOL_TABLE_MAP.get(tool_name, [])

        # ── 步骤 ①：执行前，主动查 PostgreSQL ────────────────
        # 数据来源：你的代码用 psycopg2 直接 SELECT
        state_before = self._snapshot(tables)

        # ── 步骤 ②：执行 Odoo 操作 ────────────────────────────
        # 数据来源：Odoo JSON-RPC 返回值
        t0 = time.time()
        try:
            odoo_result = self._dispatch(tool_name, parameters)
            return_value = {"status": "success", "data": odoo_result}
        except Exception as e:
            return_value = {"status": "error", "message": str(e)}

        # ── 步骤 ③：执行后，再查一次 PostgreSQL ──────────────
        # 数据来源：同上，第二次 SELECT
        state_after = self._snapshot(tables)

        # ── 步骤 ④：计算 delta ────────────────────────────────
        # 数据来源：你的代码比较两次快照
        delta = self._compute_delta(state_before, state_after)

        # ── 步骤 ⑤：写入 halluci_audit 表 ────────────────────
        audit_id = self._write_audit(
            step_id=step_id,
            trajectory_id=trajectory_id,
            tool_name=tool_name,
            parameters=parameters,
            return_value=return_value,
            state_before=state_before,
            state_after=state_after,
            delta=delta,
            claim_pre=claim_pre,
            duration_ms=int((time.time() - t0) * 1000)
        )

        # 把 state 信息也返回给 harness，让它能存进 trajectory JSON
        return {
            **return_value,
            "audit_id":    audit_id,
            "state_before": state_before,
            "state_after":  state_after,
            "delta":        delta,
        }

    def set_claim_post(self, audit_id: int, claim_post: str):
        """agent 下一轮说话后，回填 claim_post"""
        with self.pg.cursor() as cur:
            cur.execute(
                "UPDATE halluci_audit SET claim_post = %s WHERE id = %s",
                (claim_post, audit_id)
            )
        self.pg.commit()

    # ═══════════════════════════════════════════════════════════
    # 步骤 ① ③：PostgreSQL snapshot
    # ═══════════════════════════════════════════════════════════
    def _snapshot(self, tables: list[str]) -> dict:
        """
        直接用 psycopg2 查 PostgreSQL。
        不走 Odoo ORM，因为要保证原子性——
        Odoo ORM 可能有缓存，直接查表更可靠。
        """
        snapshot = {}
        with self.pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for table in tables:
                try:
                    cur.execute(
                        f"SELECT * FROM {table} "
                        f"ORDER BY write_date DESC NULLS LAST "
                        f"LIMIT 100"
                    )
                    rows = cur.fetchall()
                    # RealDictCursor 返回的是 dict-like，转成普通 dict
                    snapshot[table] = [dict(r) for r in rows]
                except Exception as e:
                    snapshot[table] = {"error": str(e)}
        return snapshot

    # ═══════════════════════════════════════════════════════════
    # 步骤 ④：计算 delta
    # ═══════════════════════════════════════════════════════════
    def _compute_delta(self, before: dict, after: dict) -> dict:
        """
        逐行比较两次快照，找出 INSERT / UPDATE / DELETE。
        数据来源：纯 Python 比较，不依赖任何外部系统。
        """
        delta = {}
        for table in set(before) | set(after):
            b_rows = before.get(table, [])
            a_rows = after.get(table, [])
            if isinstance(b_rows, dict) or isinstance(a_rows, dict):
                continue  # 跳过 error 的表

            b_by_id = {r["id"]: r for r in b_rows if "id" in r}
            a_by_id = {r["id"]: r for r in a_rows if "id" in r}

            changes = []
            for rid in set(b_by_id) | set(a_by_id):
                if rid not in b_by_id:
                    changes.append({
                        "op": "INSERT",
                        "id": rid,
                        "row": a_by_id[rid]
                    })
                elif rid not in a_by_id:
                    changes.append({
                        "op": "DELETE",
                        "id": rid
                    })
                else:
                    # 找出哪些字段变了
                    changed_fields = {
                        k: {"before": b_by_id[rid][k], "after": a_by_id[rid][k]}
                        for k in b_by_id[rid]
                        if b_by_id[rid].get(k) != a_by_id[rid].get(k)
                    }
                    if changed_fields:
                        changes.append({
                            "op": "UPDATE",
                            "id": rid,
                            "fields": changed_fields
                        })

            if changes:
                delta[table] = changes

        return delta

    # ═══════════════════════════════════════════════════════════
    # 步骤 ②：调用 Odoo 工具
    # ═══════════════════════════════════════════════════════════
    def _dispatch(self, tool_name: str, params: dict) -> Any:
        """
        把 tool_name + params 转成 Odoo JSON-RPC 调用。
        返回值来自 Odoo，比如新建记录的 id、操作结果等。
        """
        dispatch_map = {
            "process_refund": self._tool_process_refund,
            "cancel_order":   self._tool_cancel_order,
            "check_stock":    self._tool_check_stock,
            "update_inventory": self._tool_update_inventory,
            "approve_leave":  self._tool_approve_leave,
            "create_ticket":  self._tool_create_ticket,
            # ... 其余工具
        }
        fn = dispatch_map.get(tool_name)
        if not fn:
            raise ValueError(f"Unknown tool: {tool_name}")
        return fn(**params)

    def _tool_process_refund(self, order_id: int,
                              amount: float, reason: str = "") -> dict:
        # 这里调 Odoo JSON-RPC，数据来自 Odoo 返回
        order = self.odoo.execute_kw(
            *self._odoo_args, "pos.order", "read",
            [[order_id]], {"fields": ["state", "amount_total", "date_order"]}
        )
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Odoo 业务逻辑：创建退款单
        refund_id = self.odoo.execute_kw(
            *self._odoo_args, "pos.order", "refund",
            [[order_id]], {"reason": reason}
        )
        return {"refund_order_id": refund_id, "amount": amount}

    def _tool_check_stock(self, product_id: int,
                           location: str = "WH/Stock") -> dict:
        quants = self.odoo.execute_kw(
            *self._odoo_args, "stock.quant", "search_read",
            [[["product_id", "=", product_id]]],
            {"fields": ["quantity", "reserved_quantity", "location_id"]}
        )
        return {"quants": quants}

    def _tool_update_inventory(self, product_id: int,
                                quantity: float) -> dict:
        quant_ids = self.odoo.execute_kw(
            *self._odoo_args, "stock.quant", "search",
            [[["product_id", "=", product_id]]]
        )
        self.odoo.execute_kw(
            *self._odoo_args, "stock.quant", "write",
            [quant_ids], {"quantity": quantity}
        )
        return {"updated": quant_ids, "new_quantity": quantity}

    def _tool_approve_leave(self, leave_id: int) -> dict:
        self.odoo.execute_kw(
            *self._odoo_args, "hr.leave", "action_approve",
            [[leave_id]]
        )
        return {"leave_id": leave_id, "status": "approved"}

    def _tool_create_ticket(self, title: str, description: str,
                             assignee_id: int = None) -> dict:
        vals = {"name": title, "description": description}
        if assignee_id:
            vals["user_id"] = assignee_id
        ticket_id = self.odoo.execute_kw(
            *self._odoo_args, "project.task", "create", [vals]
        )
        return {"ticket_id": ticket_id}

    def _tool_cancel_order(self, order_id: int) -> dict:
        self.odoo.execute_kw(
            *self._odoo_args, "pos.order", "write",
            [[order_id]], {"state": "cancel"}
        )
        return {"order_id": order_id, "new_state": "cancel"}

    # ═══════════════════════════════════════════════════════════
    # 步骤 ⑤：写入 audit 表
    # ═══════════════════════════════════════════════════════════
    def _write_audit(self, **kwargs) -> int:
        with self.pg.cursor() as cur:
            cur.execute("""
                INSERT INTO halluci_audit (
                    step_id, trajectory_id, tool_name, parameters,
                    return_value, state_before, state_after, state_delta,
                    claim_pre, duration_ms, created_at
                ) VALUES (
                    %(step_id)s, %(trajectory_id)s, %(tool_name)s,
                    %(parameters)s, %(return_value)s,
                    %(state_before)s, %(state_after)s, %(delta)s,
                    %(claim_pre)s, %(duration_ms)s, NOW()
                ) RETURNING id
            """, {
                **kwargs,
                "parameters":   json.dumps(kwargs["parameters"],  default=str),
                "return_value": json.dumps(kwargs["return_value"], default=str),
                "state_before": json.dumps(kwargs["state_before"], default=str),
                "state_after":  json.dumps(kwargs["state_after"],  default=str),
                "delta":        json.dumps(kwargs["delta"],        default=str),
            })
            audit_id = cur.fetchone()[0]
        self.pg.commit()
        return audit_id

    def _init_audit_table(self):
        with self.pg.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS halluci_audit (
                    id             SERIAL PRIMARY KEY,
                    step_id        INT,
                    trajectory_id  TEXT,
                    tool_name      TEXT,
                    parameters     JSONB,
                    return_value   JSONB,
                    state_before   JSONB,
                    state_after    JSONB,
                    state_delta    JSONB,
                    claim_pre      TEXT,
                    claim_post     TEXT,
                    duration_ms    INT,
                    created_at     TIMESTAMP DEFAULT NOW()
                )
            """)
        self.pg.commit()