from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib import error, request

import structlog

from research.config import OdooConfig

logger = structlog.get_logger(__name__)


class OdooRPCError(RuntimeError):
    pass


class OdooJSONRPCClient:
    def __init__(self, config: OdooConfig) -> None:
        self.config = config
        self.endpoint = f"{config.url.rstrip('/')}/jsonrpc"
        self.uid = self._authenticate()
        self._field_cache: dict[str, dict[str, Any]] = {}

    def _call(self, service: str, method: str, *args: Any) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": service,
                "method": method,
                "args": list(args),
            },
            "id": uuid.uuid4().hex,
        }
        data = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise OdooRPCError(f"Could not reach Odoo JSON-RPC endpoint: {exc}") from exc
        if body.get("error"):
            message = body["error"].get("data", {}).get("message") or body["error"].get("message")
            raise OdooRPCError(message or "Unknown Odoo JSON-RPC error")
        return body.get("result")

    def _authenticate(self) -> int:
        uid = self._call(
            "common",
            "authenticate",
            self.config.db,
            self.config.username,
            self.config.password,
            {},
        )
        if not uid:
            raise OdooRPCError("Odoo authentication failed.")
        return int(uid)

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        return self._call(
            "object",
            "execute_kw",
            self.config.db,
            self.uid,
            self.config.password,
            model,
            method,
            args or [],
            kwargs or {},
        )

    def search(self, model: str, domain: list[Any], limit: int | None = None) -> list[int]:
        kwargs: dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = limit
        return self.execute_kw(model, "search", [domain], kwargs)

    def read(
        self,
        model: str,
        record_ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute_kw(model, "read", [record_ids], kwargs)

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def create(self, model: str, values: dict[str, Any]) -> int:
        return int(self.execute_kw(model, "create", [values]))

    def write(self, model: str, record_ids: list[int], values: dict[str, Any]) -> bool:
        return bool(self.execute_kw(model, "write", [record_ids, values]))

    def fields_get(self, model: str) -> dict[str, Any]:
        if model not in self._field_cache:
            self._field_cache[model] = self.execute_kw(model, "fields_get", [], {})
        return self._field_cache[model]

    def model_exists(self, model: str) -> bool:
        try:
            return bool(self.search("ir.model", [["model", "=", model]], limit=1))
        except OdooRPCError:
            return False


class OdooToolExecutor:
    def __init__(self, config: OdooConfig | None = None) -> None:
        self.config = config or OdooConfig()
        self.client = OdooJSONRPCClient(self.config)
        self._helpdesk_model_cache: str | None = None

    def execute(self, tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, tool_name, None)
        if handler is None or not callable(handler):
            raise ValueError(f"Unknown Odoo tool: {tool_name}")
        result = handler(**parameters)
        if isinstance(result, Mapping):
            return dict(result)
        return {"result": result}

    def _ensure_model(self, model: str) -> None:
        if not self.client.model_exists(model):
            raise OdooRPCError(f"Required Odoo model '{model}' is not installed.")

    def _first_id(self, model: str, domain: list[Any]) -> int | None:
        ids = self.client.search(model, domain, limit=1)
        return ids[0] if ids else None

    def _default_stock_location_id(self) -> int:
        location_id = self._first_id("stock.location", [["complete_name", "=", "WH/Stock"]])
        if location_id is None:
            location_id = self._first_id("stock.location", [["usage", "=", "internal"]])
        if location_id is None:
            raise OdooRPCError("No internal stock location was found.")
        return location_id

    def _default_internal_picking_type_id(self) -> int:
        picking_type_id = self._first_id("stock.picking.type", [["code", "=", "internal"]])
        if picking_type_id is None:
            raise OdooRPCError("No internal picking type was found.")
        return picking_type_id

    def _helpdesk_model(self) -> str:
        if self._helpdesk_model_cache is None:
            self._helpdesk_model_cache = (
                "helpdesk.ticket" if self.client.model_exists("helpdesk.ticket") else "project.task"
            )
        return self._helpdesk_model_cache

    def _support_project_id(self) -> int:
        project_id = self._first_id("project.project", [["name", "ilike", "support"]])
        if project_id is not None:
            return project_id
        return self.client.create("project.project", {"name": "Support"})

    def _closed_stage_id(self, model: str) -> int | None:
        stage_model = "helpdesk.stage" if model == "helpdesk.ticket" else "project.task.type"
        if not self.client.model_exists(stage_model):
            return None
        fields = self.client.fields_get(stage_model)
        domain: list[Any]
        if "is_close" in fields:
            stage_id = self._first_id(stage_model, [["is_close", "=", True]])
            if stage_id is not None:
                return stage_id
        if "fold" in fields:
            stage_id = self._first_id(stage_model, [["fold", "=", True]])
            if stage_id is not None:
                return stage_id
        domain = ["|", ["name", "ilike", "done"], ["name", "ilike", "close"]]
        return self._first_id(stage_model, domain)

    def _open_stage_ids(self, model: str) -> list[int]:
        stage_model = "helpdesk.stage" if model == "helpdesk.ticket" else "project.task.type"
        if not self.client.model_exists(stage_model):
            return []
        fields = self.client.fields_get(stage_model)
        if "is_close" in fields:
            return self.client.search(stage_model, [["is_close", "=", False]])
        if "fold" in fields:
            return self.client.search(stage_model, [["fold", "=", False]])
        return self.client.search(stage_model, [])

    def _post_message(self, model: str, record_id: int, body: str) -> None:
        try:
            self.client.execute_kw(
                model,
                "message_post",
                [[record_id]],
                {
                    "body": body,
                    "message_type": "comment",
                    "subtype_xmlid": "mail.mt_note",
                },
            )
        except OdooRPCError:
            logger.debug("message_post_failed", model=model, record_id=record_id)

    def _normalize_many2one(self, value: Any) -> dict[str, Any]:
        if isinstance(value, list) and len(value) >= 2:
            return {"id": value[0], "name": value[1]}
        return {"id": value, "name": None}

    def _parse_partner_tier(self, category_names: list[str]) -> str | None:
        for category in category_names:
            if category.startswith("Tier:"):
                return category.split(":", 1)[1].strip()
        return None

    def get_order(self, order_id: int, include_lines: bool = True) -> dict[str, Any]:
        self._ensure_model("pos.order")
        fields = [
            "name",
            "partner_id",
            "state",
            "date_order",
            "amount_total",
            "amount_paid",
            "amount_tax",
            "lines",
            "session_id",
        ]
        orders = self.client.read("pos.order", [order_id], fields)
        if not orders:
            raise OdooRPCError(f"POS order {order_id} was not found.")
        order = orders[0]
        payload: dict[str, Any] = {
            "id": order_id,
            "name": order.get("name"),
            "state": order.get("state"),
            "date_order": order.get("date_order"),
            "amount_total": order.get("amount_total"),
            "amount_paid": order.get("amount_paid"),
            "amount_tax": order.get("amount_tax"),
            "partner": self._normalize_many2one(order.get("partner_id")),
            "session": self._normalize_many2one(order.get("session_id")),
        }
        if include_lines and order.get("lines"):
            line_rows = self.client.read(
                "pos.order.line",
                order["lines"],
                ["product_id", "qty", "price_unit", "discount", "price_subtotal_incl"],
            )
            payload["lines"] = [
                {
                    "id": row["id"],
                    "product": self._normalize_many2one(row.get("product_id")),
                    "qty": row.get("qty"),
                    "price_unit": row.get("price_unit"),
                    "discount": row.get("discount"),
                    "subtotal_incl": row.get("price_subtotal_incl"),
                }
                for row in line_rows
            ]
        return payload

    def process_refund(self, order_id: int, amount: float, reason: str = "") -> dict[str, Any]:
        self._ensure_model("pos.order")
        order = self.get_order(order_id, include_lines=False)
        refund_result = self.client.execute_kw("pos.order", "refund", [[order_id]], {"reason": reason})
        self._post_message("pos.order", order_id, f"Refund requested: {amount}. Reason: {reason or 'n/a'}")
        return {
            "original_order_id": order_id,
            "refund_result": refund_result,
            "requested_amount": amount,
            "original_total": order.get("amount_total"),
            "reason": reason,
        }

    def cancel_order(self, order_id: int, reason: str = "") -> dict[str, Any]:
        self._ensure_model("pos.order")
        for method in ("action_pos_order_cancel", "action_cancel"):
            try:
                self.client.execute_kw("pos.order", method, [[order_id]])
                break
            except OdooRPCError:
                continue
        else:
            self.client.write("pos.order", [order_id], {"state": "cancel"})
        if reason:
            self._post_message("pos.order", order_id, f"Order cancelled. Reason: {reason}")
        return {"order_id": order_id, "state": "cancel", "reason": reason}

    def update_order_status(self, order_id: int, status: str, note: str = "") -> dict[str, Any]:
        if status == "cancel":
            return self.cancel_order(order_id, note)
        self._ensure_model("pos.order")
        method_map = {
            "paid": "action_pos_order_paid",
            "done": "action_pos_order_done",
        }
        if status in method_map:
            try:
                self.client.execute_kw("pos.order", method_map[status], [[order_id]])
            except OdooRPCError:
                self.client.write("pos.order", [order_id], {"state": status})
        else:
            self.client.write("pos.order", [order_id], {"state": status})
        if note:
            self._post_message("pos.order", order_id, note)
        return {"order_id": order_id, "state": status, "note": note}

    def apply_discount(self, order_id: int, discount_percent: float, reason: str = "") -> dict[str, Any]:
        self._ensure_model("pos.order")
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("discount_percent must be between 0 and 100.")
        order = self.client.read("pos.order", [order_id], ["lines"])
        if not order:
            raise OdooRPCError(f"POS order {order_id} was not found.")
        line_ids = order[0].get("lines", [])
        if not line_ids:
            return {"order_id": order_id, "updated_lines": [], "discount_percent": discount_percent}
        self.client.write("pos.order.line", line_ids, {"discount": discount_percent})
        if reason:
            self._post_message("pos.order", order_id, f"Discount applied: {discount_percent}%. Reason: {reason}")
        return {
            "order_id": order_id,
            "updated_lines": line_ids,
            "discount_percent": discount_percent,
            "reason": reason,
        }

    def get_customer(self, customer_id: int) -> dict[str, Any]:
        self._ensure_model("res.partner")
        rows = self.client.read(
            "res.partner",
            [customer_id],
            ["name", "email", "phone", "mobile", "company_type", "customer_rank", "category_id", "comment"],
        )
        if not rows:
            raise OdooRPCError(f"Customer {customer_id} was not found.")
        row = rows[0]
        category_ids = row.get("category_id", [])
        category_names: list[str] = []
        if category_ids:
            categories = self.client.read("res.partner.category", category_ids, ["name"])
            category_names = [category["name"] for category in categories]
        return {
            "id": customer_id,
            "name": row.get("name"),
            "email": row.get("email"),
            "phone": row.get("phone"),
            "mobile": row.get("mobile"),
            "company_type": row.get("company_type"),
            "customer_rank": row.get("customer_rank"),
            "tier": self._parse_partner_tier(category_names),
            "categories": category_names,
            "comment": row.get("comment"),
        }

    def update_customer_tier(self, customer_id: int, tier: str) -> dict[str, Any]:
        self._ensure_model("res.partner")
        tier_name = f"Tier:{tier.strip()}"
        category_id = self._first_id("res.partner.category", [["name", "=", tier_name]])
        if category_id is None:
            category_id = self.client.create("res.partner.category", {"name": tier_name})
        customer = self.client.read("res.partner", [customer_id], ["category_id"])
        if not customer:
            raise OdooRPCError(f"Customer {customer_id} was not found.")
        existing_ids = customer[0].get("category_id", [])
        existing_categories = self.client.read("res.partner.category", existing_ids, ["name"]) if existing_ids else []
        preserved_ids = [
            category["id"]
            for category in existing_categories
            if not category["name"].startswith("Tier:")
        ]
        self.client.write("res.partner", [customer_id], {"category_id": [[6, 0, preserved_ids + [category_id]]]})
        return {"customer_id": customer_id, "tier": tier, "tier_category_id": category_id}

    def log_interaction(self, customer_id: int, content: str, interaction_type: str = "note") -> dict[str, Any]:
        self._ensure_model("mail.message")
        message_id = self.client.create(
            "mail.message",
            {
                "model": "res.partner",
                "res_id": customer_id,
                "body": content,
                "message_type": "comment",
                "subject": interaction_type,
            },
        )
        return {
            "customer_id": customer_id,
            "message_id": message_id,
            "interaction_type": interaction_type,
        }

    def send_quote(
        self,
        customer_id: int,
        items: list[dict[str, Any]],
        opportunity_id: int | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        self._ensure_model("sale.order")
        if not items:
            raise ValueError("At least one quote item is required.")
        order_lines: list[list[Any]] = []
        for item in items:
            values = {
                "product_id": item["product_id"],
                "product_uom_qty": item["quantity"],
            }
            if item.get("unit_price") is not None:
                values["price_unit"] = item["unit_price"]
            order_lines.append([0, 0, values])
        payload: dict[str, Any] = {
            "partner_id": customer_id,
            "order_line": order_lines,
        }
        fields = self.client.fields_get("sale.order")
        if opportunity_id is not None and "opportunity_id" in fields:
            payload["opportunity_id"] = opportunity_id
        if note and "note" in fields:
            payload["note"] = note
        quote_id = self.client.create("sale.order", payload)
        if note:
            self._post_message("sale.order", quote_id, note)
        quote = self.client.read("sale.order", [quote_id], ["name", "state", "amount_total", "partner_id"])[0]
        return {
            "quote_id": quote_id,
            "name": quote.get("name"),
            "state": quote.get("state"),
            "amount_total": quote.get("amount_total"),
            "customer": self._normalize_many2one(quote.get("partner_id")),
        }

    def mark_opportunity_won(self, opportunity_id: int, expected_revenue: float | None = None) -> dict[str, Any]:
        self._ensure_model("crm.lead")
        if expected_revenue is not None:
            self.client.write("crm.lead", [opportunity_id], {"expected_revenue": expected_revenue})
        self.client.execute_kw("crm.lead", "action_set_won", [[opportunity_id]])
        row = self.client.read("crm.lead", [opportunity_id], ["name", "probability", "stage_id", "expected_revenue"])[0]
        return {
            "opportunity_id": opportunity_id,
            "name": row.get("name"),
            "stage": self._normalize_many2one(row.get("stage_id")),
            "probability": row.get("probability"),
            "expected_revenue": row.get("expected_revenue"),
        }

    def check_stock(self, product_id: int, location_id: int | None = None) -> dict[str, Any]:
        self._ensure_model("stock.quant")
        domain: list[Any] = [["product_id", "=", product_id]]
        if location_id is not None:
            domain.append(["location_id", "=", location_id])
        quants = self.client.search_read(
            "stock.quant",
            domain,
            ["product_id", "location_id", "quantity", "reserved_quantity"],
        )
        on_hand = sum(float(quant.get("quantity") or 0.0) for quant in quants)
        reserved = sum(float(quant.get("reserved_quantity") or 0.0) for quant in quants)
        return {
            "product_id": product_id,
            "location_id": location_id,
            "on_hand": on_hand,
            "reserved": reserved,
            "available": on_hand - reserved,
            "quants": quants,
        }

    def update_inventory(self, product_id: int, quantity: float, location_id: int | None = None) -> dict[str, Any]:
        self._ensure_model("stock.quant")
        target_location = location_id or self._default_stock_location_id()
        domain = [["product_id", "=", product_id], ["location_id", "=", target_location]]
        quant_ids = self.client.search("stock.quant", domain)
        quant_fields = self.client.fields_get("stock.quant")
        if quant_ids:
            if "inventory_quantity" in quant_fields:
                self.client.write("stock.quant", quant_ids, {"inventory_quantity": quantity})
                self.client.execute_kw("stock.quant", "action_apply_inventory", [quant_ids])
            else:
                self.client.write("stock.quant", quant_ids, {"quantity": quantity})
        else:
            values: dict[str, Any] = {
                "product_id": product_id,
                "location_id": target_location,
            }
            if "inventory_quantity" in quant_fields:
                values["inventory_quantity"] = quantity
            else:
                values["quantity"] = quantity
            quant_id = self.client.create("stock.quant", values)
            quant_ids = [quant_id]
            if "inventory_quantity" in quant_fields:
                self.client.execute_kw("stock.quant", "action_apply_inventory", [quant_ids])
        return {
            "product_id": product_id,
            "location_id": target_location,
            "target_quantity": quantity,
            "quant_ids": quant_ids,
        }

    def transfer_stock(
        self,
        product_id: int,
        quantity: float,
        source_location_id: int,
        destination_location_id: int,
    ) -> dict[str, Any]:
        self._ensure_model("stock.picking")
        if quantity <= 0:
            raise ValueError("quantity must be positive.")
        if source_location_id == destination_location_id:
            raise ValueError("source and destination locations must differ.")
        product = self.client.read("product.product", [product_id], ["display_name", "uom_id"])
        if not product:
            raise OdooRPCError(f"Product {product_id} was not found.")
        product_row = product[0]
        picking_type_id = self._default_internal_picking_type_id()
        move_command = [
            0,
            0,
            {
                "name": product_row.get("display_name"),
                "product_id": product_id,
                "product_uom_qty": quantity,
                "product_uom": self._normalize_many2one(product_row.get("uom_id"))["id"],
                "location_id": source_location_id,
                "location_dest_id": destination_location_id,
            },
        ]
        picking_id = self.client.create(
            "stock.picking",
            {
                "picking_type_id": picking_type_id,
                "location_id": source_location_id,
                "location_dest_id": destination_location_id,
                "move_ids_without_package": [move_command],
                "origin": "Halluci-Action transfer",
            },
        )
        for method in ("action_confirm", "action_assign"):
            try:
                self.client.execute_kw("stock.picking", method, [[picking_id]])
            except OdooRPCError:
                logger.debug("stock_picking_method_failed", picking_id=picking_id, method=method)
        picking = self.client.read("stock.picking", [picking_id], ["name", "state", "move_ids_without_package"])[0]
        move_ids = picking.get("move_ids_without_package", [])
        if move_ids:
            move_fields = self.client.fields_get("stock.move")
            quantity_field = "quantity_done" if "quantity_done" in move_fields else "product_uom_qty"
            self.client.write("stock.move", move_ids, {quantity_field: quantity})
        try:
            self.client.execute_kw("stock.picking", "button_validate", [[picking_id]])
        except OdooRPCError:
            logger.debug("stock_picking_validate_failed", picking_id=picking_id)
        updated = self.client.read("stock.picking", [picking_id], ["name", "state"])[0]
        return {
            "picking_id": picking_id,
            "name": updated.get("name"),
            "state": updated.get("state"),
            "move_ids": move_ids,
        }

    def trigger_reorder(
        self,
        product_id: int,
        min_qty: float | None = None,
        max_qty: float | None = None,
        quantity: float | None = None,
        location_id: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_model("stock.warehouse.orderpoint")
        target_location = location_id or self._default_stock_location_id()
        minimum = min_qty if min_qty is not None else max(quantity or 0.0, 0.0)
        maximum = max_qty if max_qty is not None else max(minimum, quantity or minimum)
        if maximum < minimum:
            raise ValueError("max_qty must be greater than or equal to min_qty.")
        domain = [["product_id", "=", product_id], ["location_id", "=", target_location]]
        orderpoint_ids = self.client.search("stock.warehouse.orderpoint", domain)
        values = {
            "product_id": product_id,
            "location_id": target_location,
            "product_min_qty": minimum,
            "product_max_qty": maximum,
            "qty_multiple": quantity or 1.0,
        }
        if orderpoint_ids:
            self.client.write("stock.warehouse.orderpoint", orderpoint_ids, values)
            orderpoint_id = orderpoint_ids[0]
        else:
            orderpoint_id = self.client.create("stock.warehouse.orderpoint", values)
        return {
            "orderpoint_id": orderpoint_id,
            "product_id": product_id,
            "location_id": target_location,
            "min_qty": minimum,
            "max_qty": maximum,
            "quantity": quantity,
        }

    def get_low_stock_items(self, limit: int = 20, location_id: int | None = None) -> dict[str, Any]:
        self._ensure_model("stock.warehouse.orderpoint")
        domain: list[Any] = []
        if location_id is not None:
            domain.append(["location_id", "=", location_id])
        rows = self.client.search_read(
            "stock.warehouse.orderpoint",
            domain,
            ["product_id", "location_id", "product_min_qty", "product_max_qty", "qty_on_hand", "qty_forecast"],
            limit=limit,
        )
        low_stock = [
            {
                "product": self._normalize_many2one(row.get("product_id")),
                "location": self._normalize_many2one(row.get("location_id")),
                "min_qty": row.get("product_min_qty"),
                "max_qty": row.get("product_max_qty"),
                "qty_on_hand": row.get("qty_on_hand"),
                "qty_forecast": row.get("qty_forecast"),
            }
            for row in rows
            if float(row.get("qty_forecast") or row.get("qty_on_hand") or 0.0)
            < float(row.get("product_min_qty") or 0.0)
        ]
        return {"count": len(low_stock), "items": low_stock[:limit]}

    def get_attendance(
        self,
        employee_id: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_model("hr.attendance")
        domain: list[Any] = [["employee_id", "=", employee_id]]
        if date_from:
            domain.append(["check_in", ">=", date_from])
        if date_to:
            domain.append(["check_in", "<=", date_to])
        rows = self.client.search_read(
            "hr.attendance",
            domain,
            ["employee_id", "check_in", "check_out", "worked_hours"],
            order="check_in desc",
        )
        return {"employee_id": employee_id, "records": rows}

    def correct_attendance(
        self,
        attendance_id: int,
        check_in: str | None = None,
        check_out: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_model("hr.attendance")
        if not check_in and not check_out:
            raise ValueError("Provide check_in or check_out.")
        if check_in and check_out:
            check_in_dt = datetime.fromisoformat(check_in.replace("Z", "+00:00"))
            check_out_dt = datetime.fromisoformat(check_out.replace("Z", "+00:00"))
            if check_out_dt < check_in_dt:
                raise ValueError("check_out cannot be earlier than check_in.")
        values = {k: v for k, v in {"check_in": check_in, "check_out": check_out}.items() if v is not None}
        self.client.write("hr.attendance", [attendance_id], values)
        row = self.client.read("hr.attendance", [attendance_id], ["employee_id", "check_in", "check_out"])[0]
        return {
            "attendance_id": attendance_id,
            "employee": self._normalize_many2one(row.get("employee_id")),
            "check_in": row.get("check_in"),
            "check_out": row.get("check_out"),
        }

    def approve_leave(self, leave_id: int) -> dict[str, Any]:
        self._ensure_model("hr.leave")
        for method in ("action_approve", "action_validate"):
            try:
                self.client.execute_kw("hr.leave", method, [[leave_id]])
            except OdooRPCError:
                logger.debug("leave_transition_failed", leave_id=leave_id, method=method)
        row = self.client.read("hr.leave", [leave_id], ["name", "state", "employee_id"])[0]
        return {
            "leave_id": leave_id,
            "state": row.get("state"),
            "employee": self._normalize_many2one(row.get("employee_id")),
            "name": row.get("name"),
        }

    def reject_leave(self, leave_id: int, reason: str) -> dict[str, Any]:
        self._ensure_model("hr.leave")
        self._post_message("hr.leave", leave_id, f"Leave rejected. Reason: {reason}")
        self.client.execute_kw("hr.leave", "action_refuse", [[leave_id]])
        row = self.client.read("hr.leave", [leave_id], ["name", "state", "employee_id"])[0]
        return {
            "leave_id": leave_id,
            "state": row.get("state"),
            "employee": self._normalize_many2one(row.get("employee_id")),
            "reason": reason,
            "name": row.get("name"),
        }

    def get_employee_info(self, employee_id: int) -> dict[str, Any]:
        self._ensure_model("hr.employee")
        rows = self.client.read(
            "hr.employee",
            [employee_id],
            ["name", "work_email", "work_phone", "department_id", "parent_id", "job_title", "company_id", "user_id"],
        )
        if not rows:
            raise OdooRPCError(f"Employee {employee_id} was not found.")
        row = rows[0]
        return {
            "employee_id": employee_id,
            "name": row.get("name"),
            "work_email": row.get("work_email"),
            "work_phone": row.get("work_phone"),
            "department": self._normalize_many2one(row.get("department_id")),
            "manager": self._normalize_many2one(row.get("parent_id")),
            "job_title": row.get("job_title"),
            "company": self._normalize_many2one(row.get("company_id")),
            "user": self._normalize_many2one(row.get("user_id")),
        }

    def create_ticket(
        self,
        title: str,
        description: str,
        partner_id: int | None = None,
        priority: str = "1",
        assignee_id: int | None = None,
    ) -> dict[str, Any]:
        model = self._helpdesk_model()
        payload: dict[str, Any] = {
            "name": title,
            "description": description,
            "priority": priority,
        }
        fields = self.client.fields_get(model)
        if partner_id is not None and "partner_id" in fields:
            payload["partner_id"] = partner_id
        if model == "helpdesk.ticket":
            if assignee_id is not None and "user_id" in fields:
                payload["user_id"] = assignee_id
        else:
            payload["project_id"] = self._support_project_id()
            if assignee_id is not None and "user_ids" in fields:
                payload["user_ids"] = [[6, 0, [assignee_id]]]
        ticket_id = self.client.create(model, payload)
        row = self.client.read(model, [ticket_id], ["name", "priority", "stage_id"])[0]
        return {
            "ticket_id": ticket_id,
            "model": model,
            "name": row.get("name"),
            "priority": row.get("priority"),
            "stage": self._normalize_many2one(row.get("stage_id")),
        }

    def assign_ticket(self, ticket_id: int, user_id: int) -> dict[str, Any]:
        model = self._helpdesk_model()
        fields = self.client.fields_get(model)
        values = {"user_id": user_id} if "user_id" in fields else {"user_ids": [[6, 0, [user_id]]]}
        self.client.write(model, [ticket_id], values)
        row = self.client.read(model, [ticket_id], ["name"])[0]
        return {"ticket_id": ticket_id, "model": model, "user_id": user_id, "name": row.get("name")}

    def close_ticket(self, ticket_id: int, resolution: str = "") -> dict[str, Any]:
        model = self._helpdesk_model()
        close_stage_id = self._closed_stage_id(model)
        fields = self.client.fields_get(model)
        values: dict[str, Any] = {}
        if close_stage_id is not None and "stage_id" in fields:
            values["stage_id"] = close_stage_id
        elif "active" in fields:
            values["active"] = False
        if values:
            self.client.write(model, [ticket_id], values)
        if resolution:
            self._post_message(model, ticket_id, f"Resolution: {resolution}")
        read_fields = ["name"]
        if "stage_id" in fields:
            read_fields.append("stage_id")
        if "active" in fields:
            read_fields.append("active")
        row = self.client.read(model, [ticket_id], read_fields)[0]
        return {
            "ticket_id": ticket_id,
            "model": model,
            "name": row.get("name"),
            "stage": self._normalize_many2one(row.get("stage_id")),
            "active": row.get("active"),
            "resolution": resolution,
        }

    def escalate_ticket(
        self,
        ticket_id: int,
        reason: str,
        priority: str | None = None,
        team_id: int | None = None,
    ) -> dict[str, Any]:
        model = self._helpdesk_model()
        row = self.client.read(model, [ticket_id], ["priority"])[0]
        current_priority = row.get("priority") or "1"
        values: dict[str, Any] = {
            "priority": priority or str(min(int(current_priority or "1") + 1, 3)),
        }
        fields = self.client.fields_get(model)
        if team_id is not None:
            if model == "helpdesk.ticket" and "team_id" in fields:
                values["team_id"] = team_id
            elif model == "project.task" and "project_id" in fields:
                values["project_id"] = team_id
        self.client.write(model, [ticket_id], values)
        self._post_message(model, ticket_id, f"Ticket escalated. Reason: {reason}")
        read_fields = ["name", "priority"]
        if "team_id" in fields:
            read_fields.append("team_id")
        if "project_id" in fields:
            read_fields.append("project_id")
        updated = self.client.read(model, [ticket_id], read_fields)[0]
        return {
            "ticket_id": ticket_id,
            "model": model,
            "name": updated.get("name"),
            "priority": updated.get("priority"),
            "team": self._normalize_many2one(updated.get("team_id") or updated.get("project_id")),
            "reason": reason,
        }

    def get_open_tickets(self, limit: int = 20, assignee_id: int | None = None) -> dict[str, Any]:
        model = self._helpdesk_model()
        fields = self.client.fields_get(model)
        domain: list[Any] = []
        open_stage_ids = self._open_stage_ids(model)
        if open_stage_ids and "stage_id" in fields:
            domain.append(["stage_id", "in", open_stage_ids])
        if assignee_id is not None:
            if "user_id" in fields:
                domain.append(["user_id", "=", assignee_id])
            elif "user_ids" in fields:
                domain.append(["user_ids", "in", [assignee_id]])
        read_fields = ["name", "priority"]
        if "stage_id" in fields:
            read_fields.append("stage_id")
        if "user_id" in fields:
            read_fields.append("user_id")
        if "user_ids" in fields:
            read_fields.append("user_ids")
        rows = self.client.search_read(model, domain, read_fields, limit=limit)
        return {
            "model": model,
            "count": len(rows),
            "tickets": rows,
        }

    # =========================================================================
    # SALES ORDER TOOLS (for Task 1, 2, 5, 6)
    # =========================================================================

    def search_sale_orders(
        self,
        customer_name: str | None = None,
        customer_id: int | None = None,
        product_name: str | None = None,
        state: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for sales orders with various filters."""
        self._ensure_model("sale.order")
        domain: list[Any] = []

        if customer_id is not None:
            domain.append(["partner_id", "=", customer_id])
        elif customer_name:
            domain.append(["partner_id.name", "ilike", customer_name])

        if state:
            domain.append(["state", "=", state])

        orders = self.client.search_read(
            "sale.order",
            domain,
            ["name", "partner_id", "state", "amount_total", "date_order", "order_line"],
            limit=limit,
            order="date_order desc",
        )

        # If product_name filter, check order lines
        if product_name:
            filtered_orders = []
            for order in orders:
                line_ids = order.get("order_line", [])
                if line_ids:
                    lines = self.client.search_read(
                        "sale.order.line",
                        [["id", "in", line_ids], ["product_id.name", "ilike", product_name]],
                        ["product_id", "product_uom_qty", "price_unit"],
                    )
                    if lines:
                        order["matching_lines"] = [
                            {
                                "product": self._normalize_many2one(line.get("product_id")),
                                "quantity": line.get("product_uom_qty"),
                                "price_unit": line.get("price_unit"),
                            }
                            for line in lines
                        ]
                        filtered_orders.append(order)
            orders = filtered_orders

        return {
            "count": len(orders),
            "orders": [
                {
                    "id": order["id"],
                    "name": order.get("name"),
                    "partner": self._normalize_many2one(order.get("partner_id")),
                    "state": order.get("state"),
                    "amount_total": order.get("amount_total"),
                    "date_order": order.get("date_order"),
                    "matching_lines": order.get("matching_lines", []),
                }
                for order in orders
            ],
        }

    def get_sale_order(self, order_id: int) -> dict[str, Any]:
        """Get detailed information about a specific sales order."""
        self._ensure_model("sale.order")
        orders = self.client.read(
            "sale.order",
            [order_id],
            ["name", "partner_id", "state", "amount_total", "amount_tax",
             "date_order", "order_line", "note", "invoice_status"],
        )
        if not orders:
            raise OdooRPCError(f"Sale order {order_id} was not found.")

        order = orders[0]
        lines = []
        if order.get("order_line"):
            line_data = self.client.read(
                "sale.order.line",
                order["order_line"],
                ["product_id", "product_uom_qty", "price_unit", "price_subtotal", "state"],
            )
            lines = [
                {
                    "id": line["id"],
                    "product": self._normalize_many2one(line.get("product_id")),
                    "quantity": line.get("product_uom_qty"),
                    "price_unit": line.get("price_unit"),
                    "subtotal": line.get("price_subtotal"),
                    "state": line.get("state"),
                }
                for line in line_data
            ]

        return {
            "id": order_id,
            "name": order.get("name"),
            "partner": self._normalize_many2one(order.get("partner_id")),
            "state": order.get("state"),
            "amount_total": order.get("amount_total"),
            "amount_tax": order.get("amount_tax"),
            "date_order": order.get("date_order"),
            "invoice_status": order.get("invoice_status"),
            "note": order.get("note"),
            "lines": lines,
        }

    def confirm_sale_order(self, order_id: int) -> dict[str, Any]:
        """Confirm a draft sales order (action_confirm)."""
        self._ensure_model("sale.order")
        order = self.client.read("sale.order", [order_id], ["name", "state"])
        if not order:
            raise OdooRPCError(f"Sale order {order_id} was not found.")

        if order[0].get("state") != "draft":
            return {
                "order_id": order_id,
                "name": order[0].get("name"),
                "success": False,
                "message": f"Order is in state '{order[0].get('state')}', not 'draft'. Cannot confirm.",
            }

        self.client.execute_kw("sale.order", "action_confirm", [[order_id]])
        updated = self.client.read("sale.order", [order_id], ["name", "state"])
        return {
            "order_id": order_id,
            "name": updated[0].get("name") if updated else None,
            "state": updated[0].get("state") if updated else None,
            "success": True,
            "message": "Order confirmed successfully.",
        }

    def create_sale_order(
        self,
        customer_id: int,
        lines: list[dict[str, Any]],
        note: str = "",
    ) -> dict[str, Any]:
        """Create a new sales order (quotation) for a customer."""
        self._ensure_model("sale.order")
        if not lines:
            raise ValueError("At least one order line is required.")

        order_lines = []
        for line in lines:
            line_vals = {
                "product_id": line["product_id"],
                "product_uom_qty": line["quantity"],
            }
            if line.get("price_unit") is not None:
                line_vals["price_unit"] = line["price_unit"]
            order_lines.append([0, 0, line_vals])

        order_id = self.client.create("sale.order", {
            "partner_id": customer_id,
            "order_line": order_lines,
            "note": note,
        })

        return self.get_sale_order(order_id)

    # =========================================================================
    # CUSTOMER/PARTNER TOOLS (for Task 1, 3, 5)
    # =========================================================================

    def search_customers(
        self,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for customers/partners by name, email, or phone."""
        self._ensure_model("res.partner")
        domain: list[Any] = [["customer_rank", ">", 0]]

        if name:
            domain.append(["name", "ilike", name])
        if email:
            domain.append(["email", "ilike", email])
        if phone:
            domain.append(["|", ["phone", "ilike", phone], ["mobile", "ilike", phone]])

        customers = self.client.search_read(
            "res.partner",
            domain,
            ["name", "email", "phone", "mobile", "credit_limit", "comment", "customer_rank"],
            limit=limit,
        )

        return {
            "count": len(customers),
            "customers": [
                {
                    "id": c["id"],
                    "name": c.get("name"),
                    "email": c.get("email"),
                    "phone": c.get("phone"),
                    "mobile": c.get("mobile"),
                    "credit_limit": c.get("credit_limit"),
                    "comment": c.get("comment"),
                }
                for c in customers
            ],
        }

    def create_customer(
        self,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        credit_limit: float = 1000.0,
        comment: str = "",
    ) -> dict[str, Any]:
        """Create a new customer record."""
        self._ensure_model("res.partner")
        values = {
            "name": name,
            "customer_rank": 1,
            "credit_limit": credit_limit,
        }
        if email:
            values["email"] = email
        if phone:
            values["phone"] = phone
        if comment:
            values["comment"] = comment

        customer_id = self.client.create("res.partner", values)
        return self.get_customer(customer_id)

    # =========================================================================
    # PRODUCT TOOLS (for Task 1, 2, 3, 4)
    # =========================================================================

    def search_products(
        self,
        name: str | None = None,
        default_code: str | None = None,
        category_name: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for products by name, internal reference, or category."""
        self._ensure_model("product.product")
        domain: list[Any] = []

        if name:
            domain.append(["name", "ilike", name])
        if default_code:
            domain.append(["default_code", "ilike", default_code])
        if category_name:
            domain.append(["categ_id.name", "ilike", category_name])

        products = self.client.search_read(
            "product.product",
            domain,
            ["name", "default_code", "list_price", "categ_id", "type", "qty_available", "virtual_available"],
            limit=limit,
        )

        return {
            "count": len(products),
            "products": [
                {
                    "id": p["id"],
                    "name": p.get("name"),
                    "default_code": p.get("default_code"),
                    "list_price": p.get("list_price"),
                    "category": self._normalize_many2one(p.get("categ_id")),
                    "type": p.get("type"),
                    "qty_available": p.get("qty_available"),
                    "virtual_available": p.get("virtual_available"),
                }
                for p in products
            ],
        }

    def get_product(self, product_id: int) -> dict[str, Any]:
        """Get detailed information about a specific product."""
        self._ensure_model("product.product")
        products = self.client.read(
            "product.product",
            [product_id],
            ["name", "default_code", "list_price", "categ_id", "type",
             "qty_available", "virtual_available", "description_sale"],
        )
        if not products:
            raise OdooRPCError(f"Product {product_id} was not found.")

        p = products[0]
        # Also get stock details
        stock_info = self.check_stock(product_id)

        return {
            "id": product_id,
            "name": p.get("name"),
            "default_code": p.get("default_code"),
            "list_price": p.get("list_price"),
            "category": self._normalize_many2one(p.get("categ_id")),
            "type": p.get("type"),
            "description_sale": p.get("description_sale"),
            "stock": {
                "on_hand": stock_info.get("on_hand"),
                "reserved": stock_info.get("reserved"),
                "available": stock_info.get("available"),
            },
        }

    def update_product_price(
        self,
        product_id: int,
        new_price: float,
        log_change: bool = True,
    ) -> dict[str, Any]:
        """Update the list price of a product."""
        self._ensure_model("product.product")
        products = self.client.read("product.product", [product_id], ["name", "list_price", "product_tmpl_id"])
        if not products:
            raise OdooRPCError(f"Product {product_id} was not found.")

        old_price = products[0].get("list_price")
        template_id = products[0].get("product_tmpl_id")
        if isinstance(template_id, list):
            template_id = template_id[0]

        # Update on the template (which propagates to variants)
        self.client.write("product.template", [template_id], {"list_price": new_price})

        result = {
            "product_id": product_id,
            "name": products[0].get("name"),
            "old_price": old_price,
            "new_price": new_price,
            "change_logged": log_change,
        }

        if log_change:
            self._post_message(
                "product.template",
                template_id,
                f"Price updated from {old_price} to {new_price}",
            )

        return result

    # =========================================================================
    # INVOICE/ACCOUNTING TOOLS (for Task 6)
    # =========================================================================

    def search_invoices(
        self,
        customer_id: int | None = None,
        state: str | None = None,
        overdue_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for invoices with various filters."""
        self._ensure_model("account.move")
        domain: list[Any] = [["move_type", "=", "out_invoice"]]

        if customer_id is not None:
            domain.append(["partner_id", "=", customer_id])
        if state:
            domain.append(["state", "=", state])
        if overdue_only:
            domain.append(["invoice_date_due", "<", datetime.now().strftime("%Y-%m-%d")])
            domain.append(["payment_state", "!=", "paid"])

        invoices = self.client.search_read(
            "account.move",
            domain,
            ["name", "partner_id", "state", "amount_total", "amount_residual",
             "invoice_date", "invoice_date_due", "payment_state"],
            limit=limit,
            order="invoice_date_due asc",
        )

        return {
            "count": len(invoices),
            "invoices": [
                {
                    "id": inv["id"],
                    "name": inv.get("name"),
                    "partner": self._normalize_many2one(inv.get("partner_id")),
                    "state": inv.get("state"),
                    "amount_total": inv.get("amount_total"),
                    "amount_residual": inv.get("amount_residual"),
                    "invoice_date": inv.get("invoice_date"),
                    "invoice_date_due": inv.get("invoice_date_due"),
                    "payment_state": inv.get("payment_state"),
                }
                for inv in invoices
            ],
        }

    # =========================================================================
    # CRM LEAD TOOLS (for disambiguation in Task 1)
    # =========================================================================

    def search_leads(
        self,
        contact_name: str | None = None,
        email: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for CRM leads by contact name or email."""
        self._ensure_model("crm.lead")
        domain: list[Any] = []

        if contact_name:
            domain.append(["contact_name", "ilike", contact_name])
        if email:
            domain.append(["email_from", "ilike", email])

        leads = self.client.search_read(
            "crm.lead",
            domain,
            ["name", "contact_name", "email_from", "phone", "expected_revenue", "stage_id"],
            limit=limit,
        )

        return {
            "count": len(leads),
            "leads": [
                {
                    "id": lead["id"],
                    "name": lead.get("name"),
                    "contact_name": lead.get("contact_name"),
                    "email": lead.get("email_from"),
                    "phone": lead.get("phone"),
                    "expected_revenue": lead.get("expected_revenue"),
                    "stage": self._normalize_many2one(lead.get("stage_id")),
                }
                for lead in leads
            ],
        }
