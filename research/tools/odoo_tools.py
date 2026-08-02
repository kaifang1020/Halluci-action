from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib import error, request

try:
    import structlog
except ModuleNotFoundError:  # pragma: no cover - local runner convenience
    structlog = None

from research.config import OdooConfig
from research.config import benchmark_today

logger = structlog.get_logger(__name__) if structlog else logging.getLogger(__name__)


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
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        if context:
            kwargs["context"] = context
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

    def _fields(self, model: str) -> set[str]:
        return set(self.client.fields_get(model).keys())

    def _existing_fields(self, model: str, fields: list[str]) -> list[str]:
        available = self._fields(model)
        return [field for field in fields if field in available]

    def _read_existing(
        self,
        model: str,
        record_ids: list[int],
        fields: list[str],
    ) -> list[dict[str, Any]]:
        return self.client.read(model, record_ids, self._existing_fields(model, fields))

    def _search_read_existing(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        limit: int | None = None,
        order: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self.client.search_read(
            model,
            domain,
            self._existing_fields(model, fields),
            limit=limit,
            order=order,
            context=context,
        )

    def _many2one_id(self, value: Any) -> int | None:
        if isinstance(value, list) and value:
            return int(value[0])
        if isinstance(value, int):
            return value
        return None

    def _find_by_id_or_name(
        self,
        model: str,
        record_id: int | None,
        name: str | None,
        label: str,
    ) -> int:
        if record_id is not None:
            return record_id
        if not name:
            raise ValueError(f"Provide either {label}_id or {label}_name/reference.")
        ids = self.client.search(model, [["name", "=", name]], limit=1)
        if not ids:
            ids = self.client.search(model, [["name", "ilike", name]], limit=1)
        if not ids:
            raise OdooRPCError(f"{label.title()} '{name}' was not found.")
        return ids[0]

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
        original_total = float(order.get("amount_total") or 0.0)
        if amount > abs(original_total):
            return {
                "status": "blocked",
                "reason": "refund_amount_exceeds_original_total",
                "original_order_id": order_id,
                "requested_amount": amount,
                "original_total": original_total,
            }
        refund_result = self.client.execute_kw("pos.order", "refund", [[order_id]])
        self._post_message("pos.order", order_id, f"Refund requested: {amount}. Reason: {reason or 'n/a'}")
        return {
            "status": "refund_created",
            "original_order_id": order_id,
            "refund_result": refund_result,
            "requested_amount": amount,
            "original_total": original_total,
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
        """Return on-hand / reserved / available stock for a product.

        - Only `stock.location.usage = 'internal'` locations are counted.
          Virtual locations (vendors, customers, inventory adjustment,
          production, transit) are explicitly excluded; they represent
          double-entry bookkeeping, not physical stock.
        - When `location_id` is given, the response is limited to that
          single internal location. Passing a non-internal location id
          raises an error to prevent stock figures from being polluted by
          virtual quants.
        - When `location_id` is omitted, all internal locations across
          warehouses are aggregated; per-store figures are returned in
          `by_location` so multi-store callers can reason about each
          warehouse independently.
        """
        self._ensure_model("stock.quant")

        if location_id is not None:
            loc = self.client.read(
                "stock.location", [location_id], ["usage", "complete_name"]
            )
            if not loc or loc[0].get("usage") != "internal":
                raise OdooRPCError(
                    f"Location {location_id} is not an internal stock location; "
                    "check_stock only operates on internal warehouse locations."
                )
            domain: list[Any] = [
                ["product_id", "=", product_id],
                ["location_id", "=", location_id],
            ]
        else:
            internal_ids = self.client.search(
                "stock.location", [["usage", "=", "internal"]]
            )
            if not internal_ids:
                raise OdooRPCError("No internal stock locations exist.")
            domain = [
                ["product_id", "=", product_id],
                ["location_id", "in", internal_ids],
            ]

        quants = self.client.search_read(
            "stock.quant",
            domain,
            ["location_id", "quantity", "reserved_quantity"],
        )

        by_location: dict[int, dict[str, Any]] = {}
        for q in quants:
            loc_field = q.get("location_id") or [None, None]
            loc_id = loc_field[0] if isinstance(loc_field, list) else loc_field
            loc_name = loc_field[1] if isinstance(loc_field, list) and len(loc_field) > 1 else None
            bucket = by_location.setdefault(loc_id, {
                "location_id": loc_id,
                "location_name": loc_name,
                "on_hand": 0.0,
                "reserved": 0.0,
            })
            bucket["on_hand"] += float(q.get("quantity") or 0.0)
            bucket["reserved"] += float(q.get("reserved_quantity") or 0.0)
        for bucket in by_location.values():
            bucket["available"] = bucket["on_hand"] - bucket["reserved"]

        total_on_hand = sum(b["on_hand"] for b in by_location.values())
        total_reserved = sum(b["reserved"] for b in by_location.values())

        return {
            "product_id": product_id,
            "location_id": location_id,
            "on_hand": total_on_hand,
            "reserved": total_reserved,
            "available": total_on_hand - total_reserved,
            "by_location": list(by_location.values()),
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
        fields = [
            "name",
            "work_email",
            "work_phone",
            "department_id",
            "parent_id",
            "job_title",
            "company_id",
            "user_id",
            "notes",
            "first_contract_date",
        ]
        rows = self.client.read(
            "hr.employee",
            [employee_id],
            self._existing_fields("hr.employee", fields),
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
            "notes": row.get("notes"),
            "contract_start_date": row.get("first_contract_date"),
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
        fields = self.client.fields_get(model)
        payload: dict[str, Any] = {
            "name": title,
            "description": description,
            "priority": self._coerce_selection_value(fields, "priority", priority),
        }
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
        fields = self.client.fields_get(model)
        next_priority = priority or str(min(int(current_priority or "1") + 1, 3))
        values: dict[str, Any] = {
            "priority": self._coerce_selection_value(fields, "priority", next_priority),
        }
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
        actual_priority = updated.get("priority")
        result: dict[str, Any] = {
            "ticket_id": ticket_id,
            "model": model,
            "name": updated.get("name"),
            "priority": actual_priority,
            "team": self._normalize_many2one(updated.get("team_id") or updated.get("project_id")),
            "reason": reason,
        }
        if str(actual_priority) != str(next_priority):
            result["priority_note"] = (
                f"Priority could not be set to {next_priority}; "
                f"system maximum supported level is {actual_priority}. "
                f"Priority remains unchanged."
            )
        return result

    def _coerce_selection_value(self, fields: dict[str, Any], field_name: str, value: str) -> str:
        selection = fields.get(field_name, {}).get("selection") or []
        allowed = [str(option[0]) for option in selection if option]
        if not allowed or str(value) in allowed:
            return str(value)
        numeric_allowed = [item for item in allowed if item.isdigit()]
        if str(value).isdigit() and numeric_allowed:
            return max((item for item in numeric_allowed if int(item) <= int(value)), default=min(numeric_allowed, key=int), key=int)
        return allowed[0]

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
        product_id: int | None = None,
        product_name: str | None = None,
        state: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        date_before: str | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        note_contains: str | None = None,
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
        if date_from:
            domain.append(["date_order", ">=", date_from])
        if date_to:
            domain.append(["date_order", "<=", date_to])
        if date_before:
            domain.append(["date_order", "<", date_before])
        if amount_min is not None:
            domain.append(["amount_total", ">=", amount_min])
        if amount_max is not None:
            domain.append(["amount_total", "<=", amount_max])
        if note_contains:
            domain.append(["note", "ilike", note_contains])

        orders = self.client.search_read(
            "sale.order",
            domain,
            ["name", "partner_id", "state", "amount_total", "date_order", "order_line", "note"],
            limit=limit,
            order="date_order desc",
        )

        # If product filter is present, check order lines.
        if product_name or product_id is not None:
            filtered_orders = []
            for order in orders:
                line_ids = order.get("order_line", [])
                if line_ids:
                    line_domain: list[Any] = [["id", "in", line_ids]]
                    if product_id is not None:
                        line_domain.append(["product_id", "=", product_id])
                    if product_name:
                        line_domain.append(["product_id.name", "ilike", product_name])
                    lines = self.client.search_read(
                        "sale.order.line",
                        line_domain,
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
                    "note": order.get("note"),
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

    def cancel_sale_order(self, order_id: int, reason: str) -> dict[str, Any]:
        """Cancel a sale order via action_cancel and log the reason on the chatter."""
        self._ensure_model("sale.order")
        if not reason or not reason.strip():
            raise ValueError("reason is required when cancelling a sale order.")
        order = self.client.read("sale.order", [order_id], ["name", "state"])
        if not order:
            raise OdooRPCError(f"Sale order {order_id} was not found.")
        prior_state = order[0].get("state")
        if prior_state == "cancel":
            return {
                "order_id": order_id,
                "name": order[0].get("name"),
                "state": "cancel",
                "success": False,
                "message": "Order is already cancelled.",
                "reason": reason,
            }
        try:
            self.client.execute_kw("sale.order", "action_cancel", [[order_id]])
        except OdooRPCError as exc:
            return {
                "order_id": order_id,
                "name": order[0].get("name"),
                "state": prior_state,
                "success": False,
                "message": f"Odoo refused to cancel: {exc}",
                "reason": reason,
            }
        self._post_message("sale.order", order_id, f"Order cancelled. Reason: {reason}")
        updated = self.client.read("sale.order", [order_id], ["name", "state"])
        return {
            "order_id": order_id,
            "name": updated[0].get("name") if updated else None,
            "state": updated[0].get("state") if updated else None,
            "prior_state": prior_state,
            "success": True,
            "message": "Order cancelled successfully.",
            "reason": reason,
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
        invoice_number: str | None = None,
        move_type: str = "out_invoice",
        state: str | None = None,
        payment_state: str | None = None,
        overdue_only: bool = False,
        invoice_date_from: str | None = None,
        invoice_date_to: str | None = None,
        due_date_before: str | None = None,
        origin: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for invoices with various filters."""
        self._ensure_model("account.move")
        domain: list[Any] = []

        if move_type:
            domain.append(["move_type", "=", move_type])

        if customer_id is not None:
            domain.append(["partner_id", "=", customer_id])
        if invoice_number:
            domain.append(["name", "ilike", invoice_number])
        if state:
            domain.append(["state", "=", state])
        if payment_state:
            domain.append(["payment_state", "=", payment_state])
        if invoice_date_from:
            domain.append(["invoice_date", ">=", invoice_date_from])
        if invoice_date_to:
            domain.append(["invoice_date", "<=", invoice_date_to])
        if due_date_before:
            domain.append(["invoice_date_due", "<", due_date_before])
        if origin:
            domain.append(["invoice_origin", "ilike", origin])
        if overdue_only:
            domain.append(["invoice_date_due", "<", benchmark_today().isoformat()])
            domain.append(["payment_state", "!=", "paid"])

        invoices = self.client.search_read(
            "account.move",
            domain,
            ["name", "partner_id", "state", "amount_total", "amount_residual",
             "invoice_date", "invoice_date_due", "payment_state", "move_type", "invoice_origin"],
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
                    "move_type": inv.get("move_type"),
                    "invoice_origin": inv.get("invoice_origin"),
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

    # =========================================================================
    # EXPANDED BENCHMARK TOOLS
    # =========================================================================

    def update_sale_order_discount(
        self,
        order_id: int,
        discount_percent: float,
        reason: str = "",
    ) -> dict[str, Any]:
        self._ensure_model("sale.order")
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("discount_percent must be between 0 and 100.")
        order = self.client.read("sale.order", [order_id], ["name", "state", "order_line"])
        if not order:
            raise OdooRPCError(f"Sale order {order_id} was not found.")
        line_ids = order[0].get("order_line", [])
        if line_ids:
            self.client.write("sale.order.line", line_ids, {"discount": discount_percent})
        if reason:
            self._post_message("sale.order", order_id, f"Discount applied: {discount_percent}%. Reason: {reason}")
        return {
            "order_id": order_id,
            "name": order[0].get("name"),
            "state": order[0].get("state"),
            "updated_lines": line_ids,
            "discount_percent": discount_percent,
            "reason": reason,
        }

    def create_delivery_backorder(
        self,
        order_id: int,
        product_id: int,
        deliver_quantity: float,
        backorder_quantity: float,
        note: str = "",
    ) -> dict[str, Any]:
        self._ensure_model("sale.order")
        pickings = self.client.search_read(
            "stock.picking",
            [["sale_id", "=", order_id], ["state", "not in", ["done", "cancel"]]],
            self._existing_fields("stock.picking", ["name", "state", "move_ids", "move_ids_without_package"]),
            limit=1,
        )
        if not pickings:
            self._post_message(
                "sale.order",
                order_id,
                f"Partial delivery requested for product {product_id}: deliver {deliver_quantity}, backorder {backorder_quantity}. {note}",
            )
            return {
                "order_id": order_id,
                "product_id": product_id,
                "deliver_quantity": deliver_quantity,
                "backorder_quantity": backorder_quantity,
                "delivery_created": False,
                "message": "No open delivery picking was found; note logged on sale order.",
            }
        picking = pickings[0]
        move_ids = picking.get("move_ids_without_package") or picking.get("move_ids") or []
        matching_moves = self.client.search_read(
            "stock.move",
            [["id", "in", move_ids], ["product_id", "=", product_id]],
            self._existing_fields("stock.move", ["name", "product_id", "product_uom_qty", "quantity_done"]),
        )
        for move in matching_moves:
            fields = self._fields("stock.move")
            values: dict[str, Any] = {}
            if "quantity_done" in fields:
                values["quantity_done"] = deliver_quantity
            if values:
                self.client.write("stock.move", [move["id"]], values)
        self._post_message(
            "stock.picking",
            picking["id"],
            f"Partial delivery: product {product_id}, deliver {deliver_quantity}, backorder {backorder_quantity}. {note}",
        )
        return {
            "order_id": order_id,
            "picking_id": picking["id"],
            "picking_name": picking.get("name"),
            "product_id": product_id,
            "deliver_quantity": deliver_quantity,
            "backorder_quantity": backorder_quantity,
            "matching_moves": matching_moves,
        }

    def search_stock_locations(
        self,
        name: str | None = None,
        complete_name: str | None = None,
        usage: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("stock.location")
        domain: list[Any] = []
        if name:
            domain.append(["name", "ilike", name])
        if complete_name:
            domain.append(["complete_name", "ilike", complete_name])
        if usage:
            domain.append(["usage", "=", usage])
        rows = self._search_read_existing("stock.location", domain, ["name", "complete_name", "usage"], limit=limit)
        return {"count": len(rows), "locations": rows}

    def search_reorder_rules(
        self,
        product_id: int,
        location_id: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("stock.warehouse.orderpoint")
        domain: list[Any] = [["product_id", "=", product_id]]
        if location_id is not None:
            domain.append(["location_id", "=", location_id])
        rows = self._search_read_existing(
            "stock.warehouse.orderpoint",
            domain,
            ["name", "product_id", "location_id", "product_min_qty", "product_max_qty", "qty_to_order"],
            limit=limit,
        )
        return {"count": len(rows), "reorder_rules": rows}

    def apply_inventory_adjustment(
        self,
        product_id: int,
        quantity: float,
        reason: str,
        location_id: int | None = None,
    ) -> dict[str, Any]:
        result = self.update_inventory(product_id=product_id, quantity=quantity, location_id=location_id)
        product = self.client.read("product.product", [product_id], ["product_tmpl_id"])
        template_id = self._many2one_id(product[0].get("product_tmpl_id")) if product else None
        if template_id is not None:
            self._post_message("product.template", template_id, f"Inventory adjusted to {quantity}. Reason: {reason}")
        result["reason"] = reason
        return result

    def get_invoice(self, invoice_id: int | None = None, invoice_number: str | None = None) -> dict[str, Any]:
        self._ensure_model("account.move")
        move_id = self._find_by_id_or_name("account.move", invoice_id, invoice_number, "invoice")
        moves = self._read_existing(
            "account.move",
            [move_id],
            [
                "name",
                "partner_id",
                "move_type",
                "state",
                "payment_state",
                "amount_total",
                "amount_residual",
                "invoice_date",
                "invoice_date_due",
                "invoice_origin",
                "invoice_line_ids",
            ],
        )
        if not moves:
            raise OdooRPCError(f"Invoice {move_id} was not found.")
        move = moves[0]
        line_ids = move.get("invoice_line_ids", [])
        lines = self._read_existing(
            "account.move.line",
            line_ids,
            ["product_id", "name", "quantity", "price_unit", "price_subtotal", "price_total"],
        ) if line_ids else []
        return {**move, "id": move_id, "partner": self._normalize_many2one(move.get("partner_id")), "lines": lines}

    def create_credit_note(
        self,
        invoice_id: int,
        amount: float,
        reason: str,
        product_id: int | None = None,
        quantity: float | None = None,
    ) -> dict[str, Any]:
        invoice = self.get_invoice(invoice_id=invoice_id)
        partner_id = self._many2one_id(invoice.get("partner_id"))
        if partner_id is None:
            raise OdooRPCError(f"Invoice {invoice_id} has no partner.")
        qty = quantity or 1.0
        line: dict[str, Any] = {"name": reason, "quantity": qty, "price_unit": amount / qty}
        if product_id is not None:
            line["product_id"] = product_id
        values: dict[str, Any] = {
            "move_type": "out_refund",
            "partner_id": partner_id,
            "invoice_origin": invoice.get("name"),
            "invoice_line_ids": [[0, 0, line]],
            "ref": f"Credit for {invoice.get('name')}: {reason}",
        }
        credit_id = self.client.create("account.move", values)
        self._post_message("account.move", credit_id, f"Credit note created for invoice {invoice.get('name')}: {reason}")
        return self.get_invoice(invoice_id=credit_id)

    def reconcile_payment(
        self,
        customer_id: int,
        allocations: list[dict[str, Any]],
        payment_reference: str = "",
    ) -> dict[str, Any]:
        applied: list[dict[str, Any]] = []
        for allocation in allocations:
            invoice_id = int(allocation["invoice_id"])
            amount = float(allocation["amount"])
            self._post_message(
                "account.move",
                invoice_id,
                f"Payment allocation recorded: {amount}. Reference: {payment_reference or 'n/a'}",
            )
            applied.append({"invoice_id": invoice_id, "amount": amount})
        return {"customer_id": customer_id, "allocations": applied, "payment_reference": payment_reference}

    def post_invoice(self, invoice_id: int, approval_note: str = "") -> dict[str, Any]:
        self._ensure_model("account.move")
        if approval_note:
            self._post_message("account.move", invoice_id, approval_note)
        self.client.execute_kw("account.move", "action_post", [[invoice_id]])
        return self.get_invoice(invoice_id=invoice_id)

    def flag_invoice_for_review(self, invoice_id: int, reason: str) -> dict[str, Any]:
        self._ensure_model("account.move")
        self._post_message("account.move", invoice_id, f"Flagged for review: {reason}")
        return {"invoice_id": invoice_id, "flagged": True, "reason": reason}

    def get_lead(self, lead_id: int) -> dict[str, Any]:
        self._ensure_model("crm.lead")
        rows = self._read_existing(
            "crm.lead",
            [lead_id],
            ["name", "type", "contact_name", "partner_id", "email_from", "phone", "stage_id", "user_id", "expected_revenue", "probability", "write_date"],
        )
        if not rows:
            raise OdooRPCError(f"Lead {lead_id} was not found.")
        row = rows[0]
        return {
            **row,
            "id": lead_id,
            "partner": self._normalize_many2one(row.get("partner_id")),
            "stage": self._normalize_many2one(row.get("stage_id")),
            "user": self._normalize_many2one(row.get("user_id")),
        }

    def update_lead_assignee(self, lead_id: int, user_id: int, reason: str = "") -> dict[str, Any]:
        self._ensure_model("crm.lead")
        self.client.write("crm.lead", [lead_id], {"user_id": user_id})
        if reason:
            self._post_message("crm.lead", lead_id, f"Reassigned to user {user_id}. Reason: {reason}")
        return self.get_lead(lead_id)

    def flag_customer_duplicate(self, duplicate_customer_id: int, primary_customer_id: int, note: str) -> dict[str, Any]:
        self._ensure_model("res.partner")
        message = f"Duplicate of customer {primary_customer_id}: {note}"
        self._post_message("res.partner", duplicate_customer_id, message)
        rows = self.client.read("res.partner", [duplicate_customer_id], ["comment"])
        comment = (rows[0].get("comment") if rows else "") or ""
        self.client.write("res.partner", [duplicate_customer_id], {"comment": f"{comment}\n{message}".strip()})
        return {"duplicate_customer_id": duplicate_customer_id, "primary_customer_id": primary_customer_id, "note": note}

    def search_users(
        self,
        name: str | None = None,
        team_name: str | None = None,
        available_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("res.users")
        domain: list[Any] = [["active", "=", True]]
        if name:
            domain.append(["name", "ilike", name])
        if team_name and self.client.model_exists("crm.team"):
            teams = self.client.search("crm.team", [["name", "ilike", team_name]])
            if teams:
                domain.append(["sale_team_id", "in", teams])
        rows = self._search_read_existing("res.users", domain, ["name", "login", "email", "sale_team_id"], limit=limit)
        if available_only:
            rows = [row for row in rows if row.get("share") is not True]
        return {"count": len(rows), "users": rows}

    def search_pos_orders(
        self,
        order_name: str | None = None,
        customer_id: int | None = None,
        product_id: int | None = None,
        state: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("pos.order")
        domain: list[Any] = []
        if order_name:
            domain.append(["name", "ilike", order_name])
        if customer_id is not None:
            domain.append(["partner_id", "=", customer_id])
        if state:
            domain.append(["state", "=", state])
        if date_from:
            domain.append(["date_order", ">=", date_from])
        if date_to:
            domain.append(["date_order", "<=", date_to])
        rows = self._search_read_existing(
            "pos.order",
            domain,
            ["name", "partner_id", "state", "date_order", "amount_total", "amount_paid", "lines"],
            limit=limit,
            order="date_order desc",
        )
        if product_id is not None:
            filtered = []
            for row in rows:
                line_ids = row.get("lines", [])
                matches = self.client.search_read(
                    "pos.order.line",
                    [["id", "in", line_ids], ["product_id", "=", product_id]],
                    self._existing_fields("pos.order.line", ["product_id", "qty", "price_unit", "price_subtotal_incl"]),
                ) if line_ids else []
                if matches:
                    row["matching_lines"] = matches
                    filtered.append(row)
            rows = filtered
        return {"count": len(rows), "orders": rows}

    def get_pos_session_summary(
        self,
        session_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        domain: list[Any] = []
        if session_id is not None:
            domain.append(["session_id", "=", session_id])
        if date_from:
            domain.append(["date_order", ">=", date_from])
        if date_to:
            domain.append(["date_order", "<=", date_to])
        orders = self._search_read_existing("pos.order", domain, ["name", "state", "amount_total", "date_order"], limit=500)
        gross = sum(float(order.get("amount_total") or 0.0) for order in orders if order.get("state") in {"paid", "done"})
        refunds = sum(abs(float(order.get("amount_total") or 0.0)) for order in orders if float(order.get("amount_total") or 0.0) < 0)
        return {"order_count": len(orders), "gross_sales": gross, "refunds": refunds, "net_revenue": gross - refunds, "orders": orders}

    def search_employees(
        self,
        name: str | None = None,
        department: str | None = None,
        work_email: str | None = None,
        manager_id: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("hr.employee")
        domain: list[Any] = []
        if name:
            domain.append(["name", "ilike", name])
        if department:
            domain.append(["department_id.name", "ilike", department])
        if work_email:
            domain.append(["work_email", "ilike", work_email])
        if manager_id is not None:
            domain.append(["parent_id", "=", manager_id])
        rows = self._search_read_existing("hr.employee", domain, ["name", "work_email", "department_id", "parent_id", "user_id", "notes", "first_contract_date"], limit=limit)
        return {"count": len(rows), "employees": rows}

    def search_leave_requests(
        self,
        employee_id: int | None = None,
        employee_name: str | None = None,
        state: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("hr.leave")
        domain: list[Any] = []
        if employee_id is not None:
            domain.append(["employee_id", "=", employee_id])
        if employee_name:
            domain.append(["employee_id.name", "ilike", employee_name])
        if state:
            domain.append(["state", "=", state])
        if date_from:
            domain.append(["request_date_to", ">=", date_from])
        if date_to:
            domain.append(["request_date_from", "<=", date_to])
        rows = self._search_read_existing(
            "hr.leave",
            domain,
            ["name", "employee_id", "holiday_status_id", "state", "request_date_from", "request_date_to", "number_of_days"],
            limit=limit,
        )
        return {"count": len(rows), "leave_requests": rows}

    def get_leave_balance(self, employee_id: int, leave_type: str | None = None) -> dict[str, Any]:
        self._ensure_model("hr.leave.allocation")
        domain: list[Any] = [["employee_id", "=", employee_id], ["state", "=", "validate"]]
        if leave_type:
            domain.append(["holiday_status_id.name", "ilike", leave_type])
        allocations = self._search_read_existing(
            "hr.leave.allocation",
            domain,
            ["holiday_status_id", "number_of_days", "number_of_days_display"],
            limit=100,
        )
        leaves = self.search_leave_requests(employee_id=employee_id, state="validate", limit=100)["leave_requests"]
        allocated = sum(float(row.get("number_of_days") or row.get("number_of_days_display") or 0.0) for row in allocations)
        used = sum(float(row.get("number_of_days") or 0.0) for row in leaves)
        return {"employee_id": employee_id, "leave_type": leave_type, "allocated_days": allocated, "used_days": used, "remaining_days": allocated - used, "allocations": allocations}

    def search_tickets(
        self,
        partner_id: int | None = None,
        title: str | None = None,
        state: str | None = None,
        priority: str | None = None,
        assignee_id: int | None = None,
        team_id: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        model = self._helpdesk_model()
        domain: list[Any] = []
        fields = self._fields(model)
        if partner_id is not None and "partner_id" in fields:
            domain.append(["partner_id", "=", partner_id])
        if title:
            domain.append(["name", "ilike", title])
        if priority and "priority" in fields:
            domain.append(["priority", "=", priority])
        if assignee_id is not None and "user_id" in fields:
            domain.append(["user_id", "=", assignee_id])
        if team_id is not None and "team_id" in fields:
            domain.append(["team_id", "=", team_id])
        if state:
            stage_field = "stage_id"
            if stage_field in fields:
                domain.append([f"{stage_field}.name", "ilike", state])
        rows = self._search_read_existing(
            model,
            domain,
            [
                "name",
                "partner_id",
                "stage_id",
                "priority",
                "user_id",
                "team_id",
                "create_date",
                "write_date",
                "date_last_stage_update",
            ],
            limit=limit,
        )
        return {"model": model, "count": len(rows), "tickets": rows}

    def get_ticket(self, ticket_id: int, include_notes: bool = True) -> dict[str, Any]:
        model = self._helpdesk_model()
        rows = self._read_existing(
            model,
            [ticket_id],
            [
                "name",
                "description",
                "partner_id",
                "stage_id",
                "priority",
                "user_id",
                "team_id",
                "create_date",
                "write_date",
                "date_last_stage_update",
            ],
        )
        if not rows:
            raise OdooRPCError(f"Ticket {ticket_id} was not found in {model}.")
        result = {**rows[0], "id": ticket_id, "model": model}
        if include_notes and self.client.model_exists("mail.message"):
            result["notes"] = self._search_read_existing(
                "mail.message",
                [["model", "=", model], ["res_id", "=", ticket_id]],
                ["date", "subject", "body", "author_id"],
                limit=50,
                order="date desc",
            )
        return result

    def search_vendors(
        self,
        name: str | None = None,
        email: str | None = None,
        product_id: int | None = None,
        preferred_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("res.partner")
        vendor_ids: list[int] | None = None
        if product_id is not None and self.client.model_exists("product.supplierinfo"):
            supplier_domain: list[Any] = []
            product = self.client.read("product.product", [product_id], ["product_tmpl_id"])
            tmpl_id = self._many2one_id(product[0].get("product_tmpl_id")) if product else None
            if tmpl_id is not None:
                supplier_domain.append(["product_tmpl_id", "=", tmpl_id])
            suppliers = self._search_read_existing("product.supplierinfo", supplier_domain, ["partner_id", "sequence"], limit=100, order="sequence asc")
            if preferred_only and suppliers:
                best_sequence = suppliers[0].get("sequence")
                suppliers = [row for row in suppliers if row.get("sequence") == best_sequence]
            vendor_ids = [self._many2one_id(row.get("partner_id")) for row in suppliers]
            vendor_ids = [vendor_id for vendor_id in vendor_ids if vendor_id is not None]
        domain: list[Any] = [["supplier_rank", ">", 0]]
        if vendor_ids is not None:
            domain.append(["id", "in", vendor_ids])
        if name:
            domain.append(["name", "ilike", name])
        if email:
            domain.append(["email", "ilike", email])
        rows = self._search_read_existing("res.partner", domain, ["name", "email", "phone", "supplier_rank"], limit=limit)
        return {"count": len(rows), "vendors": rows}

    def get_vendor_pricelist(self, vendor_id: int, product_id: int | None = None) -> dict[str, Any]:
        self._ensure_model("product.supplierinfo")
        domain: list[Any] = [["partner_id", "=", vendor_id]]
        if product_id is not None:
            product = self.client.read("product.product", [product_id], ["product_tmpl_id"])
            tmpl_id = self._many2one_id(product[0].get("product_tmpl_id")) if product else None
            if tmpl_id is not None:
                domain.append(["product_tmpl_id", "=", tmpl_id])
        rows = self._search_read_existing(
            "product.supplierinfo",
            domain,
            ["partner_id", "product_tmpl_id", "product_id", "min_qty", "price", "currency_id", "sequence"],
            limit=100,
            order="sequence asc",
        )
        return {"vendor_id": vendor_id, "product_id": product_id, "prices": rows}

    def search_purchase_orders(
        self,
        order_name: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        state: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("purchase.order")
        po_fields = self._fields("purchase.order")
        domain: list[Any] = []
        if order_name:
            domain.append(["name", "ilike", order_name])
        if vendor_id is not None:
            domain.append(["partner_id", "=", vendor_id])
        if state:
            domain.append(["state", "=", state])
        if date_from:
            domain.append(["date_order", ">=", date_from])
        if date_to:
            domain.append(["date_order", "<=", date_to])
        rows = self._search_read_existing(
            "purchase.order",
            domain,
            ["name", "partner_id", "state", "amount_total", "date_order", "order_line", "notes"],
            limit=limit,
            order="date_order desc",
        )
        if order_name and not rows and "notes" in po_fields:
            alt_domain: list[Any] = [["notes", "ilike", f"[HA-REF:{order_name}]"]]
            if vendor_id is not None:
                alt_domain.append(["partner_id", "=", vendor_id])
            if state:
                alt_domain.append(["state", "=", state])
            if date_from:
                alt_domain.append(["date_order", ">=", date_from])
            if date_to:
                alt_domain.append(["date_order", "<=", date_to])
            rows = self._search_read_existing(
                "purchase.order",
                alt_domain,
                ["name", "partner_id", "state", "amount_total", "date_order", "order_line", "notes"],
                limit=limit,
                order="date_order desc",
            )
        if product_id is not None:
            rows = [
                row for row in rows
                if row.get("order_line") and self.client.search("purchase.order.line", [["id", "in", row["order_line"]], ["product_id", "=", product_id]], limit=1)
            ]
        return {"count": len(rows), "purchase_orders": rows}

    def get_purchase_order(self, order_id: int | None = None, order_name: str | None = None) -> dict[str, Any]:
        self._ensure_model("purchase.order")
        try:
            po_id = self._find_by_id_or_name("purchase.order", order_id, order_name, "purchase_order")
        except OdooRPCError:
            po_fields = self._fields("purchase.order")
            if not order_name or "notes" not in po_fields:
                raise
            ids = self.client.search("purchase.order", [["notes", "ilike", f"[HA-REF:{order_name}]"]], limit=1)
            if not ids:
                raise
            po_id = ids[0]
        rows = self._read_existing("purchase.order", [po_id], ["name", "partner_id", "state", "amount_total", "date_order", "order_line", "picking_ids", "notes"])
        if not rows:
            raise OdooRPCError(f"Purchase order {po_id} was not found.")
        row = rows[0]
        lines = self._read_existing("purchase.order.line", row.get("order_line", []), ["product_id", "product_qty", "qty_received", "price_unit", "price_subtotal"]) if row.get("order_line") else []
        return {**row, "id": po_id, "vendor": self._normalize_many2one(row.get("partner_id")), "lines": lines}

    def create_purchase_order(self, vendor_id: int, lines: list[dict[str, Any]], note: str = "") -> dict[str, Any]:
        self._ensure_model("purchase.order")
        if not lines:
            raise ValueError("At least one purchase order line is required.")
        order_lines = []
        for line in lines:
            values = {"product_id": line["product_id"], "product_qty": line["quantity"]}
            if line.get("price_unit") is not None:
                values["price_unit"] = line["price_unit"]
            order_lines.append([0, 0, values])
        payload: dict[str, Any] = {"partner_id": vendor_id, "order_line": order_lines}
        if "notes" in self._fields("purchase.order") and note:
            payload["notes"] = note
        po_id = self.client.create("purchase.order", payload)
        if note:
            self._post_message("purchase.order", po_id, note)
        return self.get_purchase_order(order_id=po_id)

    def confirm_purchase_order(self, order_id: int, approval_note: str = "") -> dict[str, Any]:
        self._ensure_model("purchase.order")
        if approval_note:
            self._post_message("purchase.order", order_id, approval_note)
        self.client.execute_kw("purchase.order", "button_confirm", [[order_id]])
        return self.get_purchase_order(order_id=order_id)

    def receive_purchase_order(
        self,
        order_id: int,
        receipts: list[dict[str, Any]],
        create_backorder: bool = True,
    ) -> dict[str, Any]:
        self._ensure_model("purchase.order")
        updated: list[dict[str, Any]] = []
        for receipt in receipts:
            product_id = int(receipt["product_id"])
            quantity = float(receipt["quantity"])
            location_id = receipt.get("location_id") or self._default_stock_location_id()
            stock = self.check_stock(product_id, location_id)
            self.update_inventory(product_id, float(stock.get("on_hand") or 0.0) + quantity, location_id)
            updated.append({"product_id": product_id, "quantity_received": quantity, "location_id": location_id})
        self._post_message("purchase.order", order_id, f"Receipt processed: {updated}. create_backorder={create_backorder}")
        return {"order_id": order_id, "receipts": updated, "create_backorder": create_backorder}

    def create_vendor_return(
        self,
        order_id: int,
        vendor_id: int,
        product_id: int,
        quantity: float,
        reason: str,
        location_id: int | None = None,
    ) -> dict[str, Any]:
        target_location = location_id or self._default_stock_location_id()
        stock = self.check_stock(product_id, target_location)
        new_quantity = float(stock.get("on_hand") or 0.0) - quantity
        if new_quantity < 0:
            raise ValueError("Return quantity exceeds current on-hand stock at the location.")
        self.update_inventory(product_id, new_quantity, target_location)
        self._post_message("purchase.order", order_id, f"Vendor return to {vendor_id}: product {product_id}, qty {quantity}. Reason: {reason}")
        return {"order_id": order_id, "vendor_id": vendor_id, "product_id": product_id, "quantity": quantity, "location_id": target_location, "reason": reason, "new_on_hand": new_quantity}

    def search_boms(
        self,
        product_id: int | None = None,
        product_name: str | None = None,
        component_id: int | None = None,
        active: bool | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("mrp.bom")
        domain: list[Any] = []
        if product_id is not None:
            domain.append(["product_tmpl_id", "=", self._many2one_id(self.client.read("product.product", [product_id], ["product_tmpl_id"])[0].get("product_tmpl_id")) or product_id])
        if product_name:
            domain.append(["product_tmpl_id.name", "ilike", product_name])
        if active is not None:
            domain.append(["active", "=", active])
        rows = self._search_read_existing(
            "mrp.bom",
            domain,
            ["product_tmpl_id", "product_id", "code", "active", "bom_line_ids"],
            limit=limit,
            context={"active_test": False} if active is not True else None,
        )
        if component_id is not None:
            rows = [row for row in rows if row.get("bom_line_ids") and self.client.search("mrp.bom.line", [["id", "in", row["bom_line_ids"]], ["product_id", "=", component_id]], limit=1)]
        return {"count": len(rows), "boms": rows}

    def get_bom(self, bom_id: int) -> dict[str, Any]:
        self._ensure_model("mrp.bom")
        rows = self._read_existing("mrp.bom", [bom_id], ["product_tmpl_id", "product_id", "code", "active", "bom_line_ids"])
        if not rows:
            raise OdooRPCError(f"BOM {bom_id} was not found.")
        row = rows[0]
        lines = self._read_existing("mrp.bom.line", row.get("bom_line_ids", []), ["product_id", "product_qty", "product_uom_id"]) if row.get("bom_line_ids") else []
        return {**row, "id": bom_id, "lines": lines}

    def search_production_orders(
        self,
        order_name: str | None = None,
        product_id: int | None = None,
        bom_id: int | None = None,
        state: str | None = None,
        availability: str | None = None,
        scheduled_date: str | None = None,
        scheduled_date_from: str | None = None,
        scheduled_date_to: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("mrp.production")
        domain: list[Any] = []
        if order_name:
            domain.append(["name", "ilike", order_name])
        if product_id is not None:
            domain.append(["product_id", "=", product_id])
        if bom_id is not None:
            domain.append(["bom_id", "=", bom_id])
        if state:
            domain.append(["state", "=", state])
        if availability and "reservation_state" in self._fields("mrp.production"):
            domain.append(["reservation_state", "=", availability])
        if scheduled_date:
            date_field = "date_planned_start" if "date_planned_start" in self._fields("mrp.production") else "date_start"
            domain.append([date_field, ">=", scheduled_date])
        if scheduled_date_from:
            date_field = "date_planned_start" if "date_planned_start" in self._fields("mrp.production") else "date_start"
            domain.append([date_field, ">=", scheduled_date_from])
        if scheduled_date_to:
            date_field = "date_planned_start" if "date_planned_start" in self._fields("mrp.production") else "date_start"
            domain.append([date_field, "<=", scheduled_date_to])
        rows = self._search_read_existing("mrp.production", domain, ["name", "product_id", "product_qty", "bom_id", "state", "reservation_state", "date_planned_start", "date_start"], limit=limit)
        return {"count": len(rows), "production_orders": rows}

    def get_production_order(self, order_id: int | None = None, order_name: str | None = None) -> dict[str, Any]:
        self._ensure_model("mrp.production")
        mo_id = self._find_by_id_or_name("mrp.production", order_id, order_name, "production_order")
        rows = self._read_existing("mrp.production", [mo_id], ["name", "product_id", "product_qty", "bom_id", "state", "reservation_state", "date_planned_start", "date_start", "move_raw_ids"])
        if not rows:
            raise OdooRPCError(f"Production order {mo_id} was not found.")
        row = rows[0]
        components = self._read_existing("stock.move", row.get("move_raw_ids", []), ["product_id", "product_uom_qty", "reserved_availability", "quantity_done", "state"]) if row.get("move_raw_ids") else []
        return {**row, "id": mo_id, "components": components}

    def create_production_order(
        self,
        product_id: int,
        quantity: float,
        bom_id: int,
        scheduled_date: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        self._ensure_model("mrp.production")
        values: dict[str, Any] = {"product_id": product_id, "product_qty": quantity, "bom_id": bom_id}
        fields = self._fields("mrp.production")
        if scheduled_date:
            values["date_planned_start" if "date_planned_start" in fields else "date_start"] = scheduled_date
        mo_id = self.client.create("mrp.production", values)
        if note:
            self._post_message("mrp.production", mo_id, note)
        return self.get_production_order(order_id=mo_id)

    def start_production_order(self, order_id: int) -> dict[str, Any]:
        self._ensure_model("mrp.production")
        for method in ("action_confirm", "button_plan", "button_mark_done"):
            try:
                if method == "button_mark_done":
                    break
                self.client.execute_kw("mrp.production", method, [[order_id]])
            except OdooRPCError:
                continue
        try:
            self.client.execute_kw("mrp.production", "button_start", [[order_id]])
        except OdooRPCError:
            if "state" in self._fields("mrp.production"):
                self.client.write("mrp.production", [order_id], {"state": "progress"})
        return self.get_production_order(order_id=order_id)

    def create_bom_version(
        self,
        product_id: int,
        lines: list[dict[str, Any]],
        source_bom_id: int | None = None,
        active: bool = True,
        note: str = "",
    ) -> dict[str, Any]:
        self._ensure_model("mrp.bom")
        product = self.client.read("product.product", [product_id], ["product_tmpl_id"])
        tmpl_id = self._many2one_id(product[0].get("product_tmpl_id")) if product else None
        if tmpl_id is None:
            raise OdooRPCError(f"Product {product_id} has no product template.")
        bom_lines = [
            [0, 0, {"product_id": line["component_product_id"], "product_qty": line["quantity"]}]
            for line in lines
        ]
        values: dict[str, Any] = {"product_tmpl_id": tmpl_id, "product_id": product_id, "bom_line_ids": bom_lines, "active": active}
        if source_bom_id is not None and "code" in self._fields("mrp.bom"):
            values["code"] = f"Version from BOM {source_bom_id}"
        bom_id = self.client.create("mrp.bom", values)
        if note:
            self._post_message("mrp.bom", bom_id, note)
        return self.get_bom(bom_id)

    def archive_bom(self, bom_id: int, reason: str = "") -> dict[str, Any]:
        self._ensure_model("mrp.bom")
        self.client.write("mrp.bom", [bom_id], {"active": False})
        if reason:
            self._post_message("mrp.bom", bom_id, f"Archived: {reason}")
        return self.get_bom(bom_id)

    def search_projects(
        self,
        name: str | None = None,
        active: bool | None = None,
        user_id: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("project.project")
        domain: list[Any] = []
        if name:
            domain.append(["name", "ilike", name])
        if active is not None:
            domain.append(["active", "=", active])
        if user_id is not None and "user_id" in self._fields("project.project"):
            domain.append(["user_id", "=", user_id])
        rows = self._search_read_existing(
            "project.project",
            domain,
            ["name", "active", "user_id", "partner_id", "date_start", "date"],
            limit=limit,
            context={"active_test": False} if active is not True else None,
        )
        return {"count": len(rows), "projects": rows}

    def get_project(self, project_id: int) -> dict[str, Any]:
        self._ensure_model("project.project")
        rows = self._read_existing("project.project", [project_id], ["name", "active", "user_id", "partner_id", "date_start", "date", "task_ids", "budget_total", "budget_spent"])
        if not rows:
            raise OdooRPCError(f"Project {project_id} was not found.")
        row = rows[0]
        task_count = len(row.get("task_ids", []) or [])
        return {**row, "id": project_id, "task_count": task_count}

    def search_project_tasks(
        self,
        task_name: str | None = None,
        project_id: int | None = None,
        assignee_id: int | None = None,
        state: str | None = None,
        deadline_before: str | None = None,
        blocked_only: bool = False,
        parent_task_id: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._ensure_model("project.task")
        domain: list[Any] = []
        fields = self._fields("project.task")
        if task_name:
            domain.append(["name", "ilike", task_name])
        if project_id is not None:
            domain.append(["project_id", "=", project_id])
        if assignee_id is not None:
            domain.append(["user_ids" if "user_ids" in fields else "user_id", "in" if "user_ids" in fields else "=", [assignee_id] if "user_ids" in fields else assignee_id])
        if state:
            domain.append(["stage_id.name", "ilike", state])
        deadline_field = "date_deadline" if "date_deadline" in fields else "planned_date_end"
        if deadline_before and deadline_field in fields:
            domain.append([deadline_field, "<", deadline_before])
        if parent_task_id is not None and "parent_id" in fields:
            domain.append(["parent_id", "=", parent_task_id])
        rows = self._search_read_existing("project.task", domain, ["name", "project_id", "stage_id", "user_id", "user_ids", "date_deadline", "parent_id", "child_ids", "depend_on_ids"], limit=limit)
        if blocked_only:
            rows = [row for row in rows if row.get("child_ids") or row.get("depend_on_ids")]
        return {"count": len(rows), "tasks": rows}

    def get_project_task(self, task_id: int) -> dict[str, Any]:
        self._ensure_model("project.task")
        rows = self._read_existing("project.task", [task_id], ["name", "description", "project_id", "stage_id", "user_id", "user_ids", "date_deadline", "parent_id", "child_ids", "depend_on_ids", "budget"])
        if not rows:
            raise OdooRPCError(f"Project task {task_id} was not found.")
        row = rows[0]
        subtasks = self._read_existing("project.task", row.get("child_ids", []), ["name", "stage_id"]) if row.get("child_ids") else []
        return {**row, "id": task_id, "subtasks": subtasks}

    def create_project_task(
        self,
        project_id: int,
        title: str,
        description: str = "",
        user_id: int | None = None,
        deadline: str | None = None,
        budget: float | None = None,
    ) -> dict[str, Any]:
        self._ensure_model("project.task")
        fields = self._fields("project.task")
        values: dict[str, Any] = {"project_id": project_id, "name": title}
        if description and "description" in fields:
            values["description"] = description
        if user_id is not None:
            if "user_ids" in fields:
                values["user_ids"] = [[6, 0, [user_id]]]
            elif "user_id" in fields:
                values["user_id"] = user_id
        if deadline and "date_deadline" in fields:
            values["date_deadline"] = deadline
        if budget is not None and "budget" in fields:
            values["budget"] = budget
        task_id = self.client.create("project.task", values)
        return self.get_project_task(task_id)

    def reassign_project_task(self, task_id: int, user_id: int, reason: str = "") -> dict[str, Any]:
        self._ensure_model("project.task")
        fields = self._fields("project.task")
        values = {"user_ids": [[6, 0, [user_id]]]} if "user_ids" in fields else {"user_id": user_id}
        self.client.write("project.task", [task_id], values)
        if reason:
            self._post_message("project.task", task_id, f"Task reassigned to user {user_id}. Reason: {reason}")
        return self.get_project_task(task_id)

    def close_project_task(self, task_id: int, resolution: str = "") -> dict[str, Any]:
        self._ensure_model("project.task")
        stage_id = self._closed_stage_id("project.task")
        if stage_id is not None:
            self.client.write("project.task", [task_id], {"stage_id": stage_id})
        if resolution:
            self._post_message("project.task", task_id, resolution)
        return self.get_project_task(task_id)

    def get_project_workload(self, project_id: int | None = None, include_leave_status: bool = True) -> dict[str, Any]:
        self._ensure_model("project.task")
        domain: list[Any] = []
        if project_id is not None:
            domain.append(["project_id", "=", project_id])
        tasks = self._search_read_existing("project.task", domain, ["user_id", "user_ids", "stage_id"], limit=500)
        counts: dict[int, int] = {}
        for task in tasks:
            user_ids = task.get("user_ids") or []
            if not user_ids:
                user_id = self._many2one_id(task.get("user_id"))
                user_ids = [user_id] if user_id is not None else []
            for user_id in user_ids:
                counts[int(user_id)] = counts.get(int(user_id), 0) + 1
        users = self._read_existing("res.users", list(counts.keys()), ["name", "login", "email"]) if counts else []
        leave_by_user: dict[int, bool] = {}
        if include_leave_status and counts and self.client.model_exists("hr.employee") and self.client.model_exists("hr.leave"):
            today_s = benchmark_today().isoformat()
            employees = self._search_read_existing(
                "hr.employee",
                [["user_id", "in", list(counts.keys())]],
                ["name", "user_id"],
                limit=500,
            )
            employee_to_user = {
                employee["id"]: self._many2one_id(employee.get("user_id"))
                for employee in employees
                if self._many2one_id(employee.get("user_id")) is not None
            }
            if employee_to_user:
                leaves = self._search_read_existing(
                    "hr.leave",
                    [
                        ["employee_id", "in", list(employee_to_user.keys())],
                        ["state", "=", "validate"],
                        ["request_date_from", "<=", today_s],
                        ["request_date_to", ">=", today_s],
                    ],
                    ["employee_id"],
                    limit=500,
                )
                for leave in leaves:
                    employee_id = self._many2one_id(leave.get("employee_id"))
                    user_id = employee_to_user.get(employee_id) if employee_id is not None else None
                    if user_id is not None:
                        leave_by_user[user_id] = True
        workload = []
        for user in users:
            workload.append({
                "user_id": user["id"],
                "name": user.get("name"),
                "open_task_count": counts.get(user["id"], 0),
                "on_leave": leave_by_user.get(user["id"], False) if include_leave_status else None,
            })
        return {"project_id": project_id, "include_leave_status": include_leave_status, "workload": workload}
