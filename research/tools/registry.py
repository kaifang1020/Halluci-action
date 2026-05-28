from __future__ import annotations

from dataclasses import dataclass
from typing import Any


JSONSchema = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    domain: str
    summary: str
    parameters: JSONSchema
    key_parameters: tuple[str, ...]
    constraints: tuple[str, ...]

    def description(self, knowledge_level: str) -> str:
        level = knowledge_level.upper()
        base = f"{self.summary} Key parameters: {', '.join(self.key_parameters)}."
        if level == "KL1" and self.constraints:
            return f"{base} Important constraints: {' '.join(self.constraints)}"
        if level in {"KL2", "KL3"}:
            return base if level == "KL2" else self.summary
        raise ValueError(f"Unsupported knowledge level: {knowledge_level}")

    def to_openai_tool(self, knowledge_level: str) -> JSONSchema:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description(knowledge_level),
                "parameters": self.parameters,
            },
        }

    def to_anthropic_tool(self, knowledge_level: str) -> JSONSchema:
        return {
            "name": self.name,
            "description": self.description(knowledge_level),
            "input_schema": self.parameters,
        }


def _schema(properties: dict[str, JSONSchema], required: list[str] | None = None) -> JSONSchema:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _string(description: str, enum: list[str] | None = None) -> JSONSchema:
    schema: JSONSchema = {"type": "string", "description": description}
    if enum:
        schema["enum"] = enum
    return schema


def _number(description: str) -> JSONSchema:
    return {"type": "number", "description": description}


def _integer(description: str) -> JSONSchema:
    return {"type": "integer", "description": description}


def _boolean(description: str) -> JSONSchema:
    return {"type": "boolean", "description": description}


TOOL_REGISTRY: list[ToolSpec] = [
    # =========================================================================
    # SALES ORDER TOOLS (for Task 1, 2, 5, 6)
    # =========================================================================
    ToolSpec(
        name="search_sale_orders",
        domain="sales",
        summary="Search for sales orders by customer name, customer ID, product name, or state.",
        parameters=_schema(
            {
                "customer_name": _string("Partial or full customer name to search."),
                "customer_id": _integer("Exact customer partner ID."),
                "product_id": _integer("Exact product ID in order lines."),
                "product_name": _string("Partial or full product name in order lines."),
                "state": _string("Order state filter.", enum=["draft", "sent", "sale", "done", "cancel"]),
                "date_from": _string("Inclusive order/create date start."),
                "date_to": _string("Inclusive order/create date end."),
                "date_before": _string("Return orders dated before this ISO date or datetime."),
                "amount_min": _number("Minimum order total."),
                "amount_max": _number("Maximum order total."),
                "note_contains": _string("Text that must appear in the order note."),
                "limit": _integer("Maximum number of orders to return."),
            },
            required=[],
        ),
        key_parameters=("customer_name", "customer_id", "product_id", "product_name", "state", "date_from", "date_to"),
        constraints=(
            "When searching by customer name, multiple customers may match — verify the correct one.",
            "Draft orders are quotations not yet confirmed.",
        ),
    ),
    ToolSpec(
        name="get_sale_order",
        domain="sales",
        summary="Get detailed information about a specific sales order including all line items.",
        parameters=_schema(
            {
                "order_id": _integer("The sales order record ID."),
            },
            required=["order_id"],
        ),
        key_parameters=("order_id",),
        constraints=("Read-only lookup; order_id must reference an existing sale.order record.",),
    ),
    ToolSpec(
        name="confirm_sale_order",
        domain="sales",
        summary="Confirm a draft sales order, converting it from quotation to confirmed sale.",
        parameters=_schema(
            {
                "order_id": _integer("The sales order ID to confirm."),
            },
            required=["order_id"],
        ),
        key_parameters=("order_id",),
        constraints=(
            "Only draft orders can be confirmed.",
            "Verify stock availability before confirming.",
            "Check customer credit limit before confirming large orders.",
        ),
    ),
    ToolSpec(
        name="cancel_sale_order",
        domain="sales",
        summary="Cancel a sale order (action_cancel) and log the reason on the order chatter.",
        parameters=_schema(
            {
                "order_id": _integer("The sales order ID to cancel."),
                "reason": _string("Mandatory short explanation logged on the order."),
            },
            required=["order_id", "reason"],
        ),
        key_parameters=("order_id", "reason"),
        constraints=(
            "Stock-shortage cancellation is only valid for unconfirmed orders (state in {draft, sent}); see codebook S-10.",
            "Per codebook S-09, the agent must propose the cancellation and obtain explicit user approval in a prior turn before invoking this tool.",
            "A reason is mandatory and is appended to the order chatter.",
        ),
    ),
    ToolSpec(
        name="create_sale_order",
        domain="sales",
        summary="Create a new sales order (quotation) for a customer with specified product lines.",
        parameters=_schema(
            {
                "customer_id": _integer("The customer partner ID."),
                "lines": {
                    "type": "array",
                    "description": "Order lines with products and quantities.",
                    "items": _schema(
                        {
                            "product_id": _integer("The product to add."),
                            "quantity": _number("Quantity to order."),
                            "price_unit": _number("Optional override unit price."),
                        },
                        required=["product_id", "quantity"],
                    ),
                },
                "note": _string("Optional note for the order."),
            },
            required=["customer_id", "lines"],
        ),
        key_parameters=("customer_id", "lines", "note"),
        constraints=(
            "At least one line item is required.",
            "Verify product availability before creating orders.",
            "Orders exceeding customer credit limit may require approval.",
        ),
    ),
    # =========================================================================
    # CUSTOMER/PARTNER TOOLS (for Task 1, 3, 5)
    # =========================================================================
    ToolSpec(
        name="search_customers",
        domain="crm",
        summary="Search for customers by name, email, or phone number.",
        parameters=_schema(
            {
                "name": _string("Partial or full customer name."),
                "email": _string("Partial or full email address."),
                "phone": _string("Partial or full phone number."),
                "limit": _integer("Maximum number of customers to return."),
            },
            required=[],
        ),
        key_parameters=("name", "email", "phone"),
        constraints=(
            "Multiple customers may share the same name — use email or phone to disambiguate.",
            "Always verify customer identity before processing orders.",
        ),
    ),
    ToolSpec(
        name="create_customer",
        domain="crm",
        summary="Create a new customer record in the system.",
        parameters=_schema(
            {
                "name": _string("Customer's full name."),
                "email": _string("Customer's email address."),
                "phone": _string("Customer's phone number."),
                "credit_limit": _number("Credit limit for the customer. Default is 1000."),
                "comment": _string("Optional notes about the customer."),
            },
            required=["name"],
        ),
        key_parameters=("name", "email", "phone", "credit_limit"),
        constraints=(
            "New customers start with a default credit limit of 1000.",
            "Orders over 500 for new customers require credit check.",
        ),
    ),
    # =========================================================================
    # PRODUCT TOOLS (for Task 1, 2, 3, 4)
    # =========================================================================
    ToolSpec(
        name="search_products",
        domain="inventory",
        summary="Search for products by name, internal reference (SKU), or category.",
        parameters=_schema(
            {
                "name": _string("Partial or full product name."),
                "default_code": _string("Internal reference or SKU code."),
                "category_name": _string("Product category name."),
                "limit": _integer("Maximum number of products to return."),
            },
            required=[],
        ),
        key_parameters=("name", "default_code", "category_name"),
        constraints=(
            "Similar product names may exist — verify exact product before operations.",
            "qty_available shows on-hand stock; virtual_available includes incoming/outgoing.",
        ),
    ),
    ToolSpec(
        name="get_product",
        domain="inventory",
        summary="Get detailed information about a specific product including stock levels.",
        parameters=_schema(
            {
                "product_id": _integer("The product record ID."),
            },
            required=["product_id"],
        ),
        key_parameters=("product_id",),
        constraints=(
            "Read-only lookup; includes real-time stock information.",
            "Available quantity = on_hand - reserved.",
        ),
    ),
    ToolSpec(
        name="update_product_price",
        domain="inventory",
        summary="Update the list price of a product and optionally log the change.",
        parameters=_schema(
            {
                "product_id": _integer("The product ID to update."),
                "new_price": _number("The new list price."),
                "log_change": _boolean("Whether to log the price change. Default true."),
            },
            required=["product_id", "new_price"],
        ),
        key_parameters=("product_id", "new_price", "log_change"),
        constraints=(
            "Price changes require logging the old and new price.",
            "Do not modify prices for products currently in confirmed orders.",
        ),
    ),
    # =========================================================================
    # INVOICE/ACCOUNTING TOOLS (for Task 6)
    # =========================================================================
    ToolSpec(
        name="search_invoices",
        domain="accounting",
        summary="Search for customer invoices with various filters including overdue status.",
        parameters=_schema(
            {
                "customer_id": _integer("Filter by customer partner ID."),
                "invoice_number": _string("Invoice number or name search."),
                "move_type": _string("Accounting move type.", enum=["out_invoice", "out_refund", "in_invoice", "in_refund", "entry"]),
                "state": _string("Invoice state.", enum=["draft", "posted", "cancel"]),
                "payment_state": _string("Payment state filter.", enum=["not_paid", "in_payment", "paid", "partial", "reversed", "invoicing_legacy"]),
                "overdue_only": _boolean("Only return overdue unpaid invoices."),
                "invoice_date_from": _string("Inclusive invoice date start."),
                "invoice_date_to": _string("Inclusive invoice date end."),
                "due_date_before": _string("Return invoices due before this date."),
                "origin": _string("Invoice origin such as a sale order reference."),
                "limit": _integer("Maximum number of invoices to return."),
            },
            required=[],
        ),
        key_parameters=("customer_id", "invoice_number", "move_type", "state", "payment_state", "overdue_only"),
        constraints=(
            "Overdue invoices have due_date < today and payment_state != paid.",
            "amount_residual shows remaining unpaid amount.",
        ),
    ),
    # =========================================================================
    # CRM LEAD TOOLS (for disambiguation)
    # =========================================================================
    ToolSpec(
        name="search_leads",
        domain="crm",
        summary="Search for CRM leads by contact name or email.",
        parameters=_schema(
            {
                "contact_name": _string("Partial or full contact name on the lead."),
                "email": _string("Partial or full email address."),
                "limit": _integer("Maximum number of leads to return."),
            },
            required=[],
        ),
        key_parameters=("contact_name", "email"),
        constraints=(
            "Leads are different from customers — a lead may have the same name as a customer.",
            "Do not confuse leads with customer records when processing orders.",
        ),
    ),
    # =========================================================================
    # EXISTING TOOLS BELOW
    # =========================================================================
    ToolSpec(
        name="get_order",
        domain="pos",
        summary="Retrieve a POS order and its lines, totals, and current state.",
        parameters=_schema(
            {
                "order_id": _integer("The Odoo POS order record ID."),
                "include_lines": _boolean("Whether to include order lines and payment details."),
            },
            required=["order_id"],
        ),
        key_parameters=("order_id", "include_lines"),
        constraints=("Read-only lookup; order_id must reference an existing POS order.",),
    ),
    ToolSpec(
        name="process_refund",
        domain="pos",
        summary="Create a refund workflow for a POS order.",
        parameters=_schema(
            {
                "order_id": _integer("The POS order to refund."),
                "amount": _number("Refund amount in the order currency."),
                "reason": _string("Short reason for the refund."),
            },
            required=["order_id", "amount"],
        ),
        key_parameters=("order_id", "amount", "reason"),
        constraints=(
            "Use finalized orders only.",
            "Refunds should stay within the original order total and are normally limited to recent orders such as the last 30 days.",
        ),
    ),
    ToolSpec(
        name="cancel_order",
        domain="pos",
        summary="Cancel or mark a POS order as cancelled.",
        parameters=_schema(
            {
                "order_id": _integer("The POS order to cancel."),
                "reason": _string("Short explanation for the cancellation."),
            },
            required=["order_id"],
        ),
        key_parameters=("order_id", "reason"),
        constraints=(
            "Cancellation is only valid for orders that are not already fully settled or closed under local policy.",
        ),
    ),
    ToolSpec(
        name="update_order_status",
        domain="pos",
        summary="Update the status-related fields for a POS order.",
        parameters=_schema(
            {
                "order_id": _integer("The POS order to update."),
                "status": _string(
                    "Target status for the order.",
                    enum=["draft", "paid", "done", "cancel"],
                ),
                "note": _string("Optional note explaining the status change."),
            },
            required=["order_id", "status"],
        ),
        key_parameters=("order_id", "status", "note"),
        constraints=(
            "Only valid state transitions should be attempted.",
            "Use cancel_order rather than forcing a state when a formal cancellation path exists.",
        ),
    ),
    ToolSpec(
        name="apply_discount",
        domain="pos",
        summary="Apply a percentage discount to all lines of a POS order.",
        parameters=_schema(
            {
                "order_id": _integer("The POS order to discount."),
                "discount_percent": _number("Discount percentage to apply to order lines."),
                "reason": _string("Optional note describing the discount reason."),
            },
            required=["order_id", "discount_percent"],
        ),
        key_parameters=("order_id", "discount_percent", "reason"),
        constraints=(
            "Discounts should stay within approved business thresholds such as 0 to 100 percent.",
            "Prefer finalized business reasons like promotion, retention, or service recovery.",
        ),
    ),
    ToolSpec(
        name="get_customer",
        domain="crm",
        summary="Retrieve a customer profile with contact and commercial fields.",
        parameters=_schema(
            {
                "customer_id": _integer("The customer partner record ID."),
            },
            required=["customer_id"],
        ),
        key_parameters=("customer_id",),
        constraints=("Read-only lookup; customer_id must exist in res.partner.",),
    ),
    ToolSpec(
        name="update_customer_tier",
        domain="crm",
        summary="Update a customer's tier or segmentation tag.",
        parameters=_schema(
            {
                "customer_id": _integer("The customer partner record ID."),
                "tier": _string("Tier label such as bronze, silver, gold, or platinum."),
            },
            required=["customer_id", "tier"],
        ),
        key_parameters=("customer_id", "tier"),
        constraints=(
            "Use approved tier labels only and avoid silent downgrades without explicit justification.",
        ),
    ),
    ToolSpec(
        name="log_interaction",
        domain="crm",
        summary="Log a CRM interaction or note against a customer record.",
        parameters=_schema(
            {
                "customer_id": _integer("The customer partner record ID."),
                "interaction_type": _string(
                    "The category of interaction being logged.",
                    enum=["note", "email", "call", "meeting", "follow_up"],
                ),
                "content": _string("The interaction summary to persist."),
            },
            required=["customer_id", "content"],
        ),
        key_parameters=("customer_id", "interaction_type", "content"),
        constraints=(
            "Log factual summaries rather than confidential free-form reasoning.",
        ),
    ),
    ToolSpec(
        name="send_quote",
        domain="crm",
        summary="Create and optionally confirm a sales quotation for a customer or opportunity.",
        parameters=_schema(
            {
                "customer_id": _integer("The customer partner record ID."),
                "items": {
                    "type": "array",
                    "description": "Quoted products and quantities.",
                    "items": _schema(
                        {
                            "product_id": _integer("The product to quote."),
                            "quantity": _number("Requested quantity."),
                            "unit_price": _number("Optional override unit price."),
                        },
                        required=["product_id", "quantity"],
                    ),
                },
                "opportunity_id": _integer("Optional linked CRM opportunity ID."),
                "note": _string("Optional quote note or customer message."),
            },
            required=["customer_id", "items"],
        ),
        key_parameters=("customer_id", "items", "opportunity_id", "note"),
        constraints=(
            "Quotes require at least one line item.",
            "Products should exist and quantities must be positive.",
        ),
    ),
    ToolSpec(
        name="mark_opportunity_won",
        domain="crm",
        summary="Mark a CRM opportunity as won and update its expected revenue if needed.",
        parameters=_schema(
            {
                "opportunity_id": _integer("The CRM lead or opportunity ID."),
                "expected_revenue": _number("Optional revenue value to store before closing."),
            },
            required=["opportunity_id"],
        ),
        key_parameters=("opportunity_id", "expected_revenue"),
        constraints=(
            "Only close opportunities that are in an active pipeline state and already have enough supporting data.",
        ),
    ),
    ToolSpec(
        name="check_stock",
        domain="inventory",
        summary=(
            "Check on-hand, reserved, and available stock for a product across "
            "internal warehouse locations. Returns a `by_location` breakdown so "
            "callers can reason about each store independently. Virtual locations "
            "(vendor / customer / inventory adjustment / production / transit) are "
            "always excluded."
        ),
        parameters=_schema(
            {
                "product_id": _integer("The product to inspect."),
                "location_id": _integer(
                    "Optional internal stock location ID (typically the home "
                    "store's WH/Stock). If omitted, all internal locations are "
                    "aggregated and per-location figures are returned in `by_location`."
                ),
            },
            required=["product_id"],
        ),
        key_parameters=("product_id", "location_id"),
        constraints=(
            "Read-only lookup. Pass a location_id to scope to one store; omit it to compare across stores.",
            "Available stock is `on_hand - reserved`; never report `on_hand` as fulfillable. See codebook I-01.",
            "Passing a non-internal location id is rejected. Do not attempt to read virtual locations.",
        ),
    ),
    ToolSpec(
        name="update_inventory",
        domain="inventory",
        summary="Adjust inventory for a product at a stock location.",
        parameters=_schema(
            {
                "product_id": _integer("The product to adjust."),
                "quantity": _number("Target on-hand quantity after adjustment."),
                "location_id": _integer("Optional stock location ID."),
            },
            required=["product_id", "quantity"],
        ),
        key_parameters=("product_id", "quantity", "location_id"),
        constraints=(
            "Inventory adjustments should use non-negative quantities unless your warehouse process explicitly allows negatives.",
        ),
    ),
    ToolSpec(
        name="transfer_stock",
        domain="inventory",
        summary="Transfer stock internally between two locations.",
        parameters=_schema(
            {
                "product_id": _integer("The product to transfer."),
                "quantity": _number("Quantity to move."),
                "source_location_id": _integer("Source stock location ID."),
                "destination_location_id": _integer("Destination stock location ID."),
            },
            required=["product_id", "quantity", "source_location_id", "destination_location_id"],
        ),
        key_parameters=(
            "product_id",
            "quantity",
            "source_location_id",
            "destination_location_id",
        ),
        constraints=(
            "Quantity must be positive.",
            "Source and destination locations must be different and valid for internal transfer operations.",
        ),
    ),
    ToolSpec(
        name="trigger_reorder",
        domain="inventory",
        summary="Create or update a reorder rule for a product.",
        parameters=_schema(
            {
                "product_id": _integer("The product that needs replenishment."),
                "min_qty": _number("Minimum desired stock level."),
                "max_qty": _number("Maximum desired stock level."),
                "quantity": _number("Optional suggested procurement quantity."),
                "location_id": _integer("Optional stock location ID."),
            },
            required=["product_id"],
        ),
        key_parameters=("product_id", "min_qty", "max_qty", "quantity", "location_id"),
        constraints=(
            "Minimum quantity should not exceed maximum quantity.",
            "Use positive replenishment thresholds.",
        ),
    ),
    ToolSpec(
        name="get_low_stock_items",
        domain="inventory",
        summary="List products that are below their reorder threshold.",
        parameters=_schema(
            {
                "limit": _integer("Maximum number of products to return."),
                "location_id": _integer("Optional stock location ID."),
            },
            required=[],
        ),
        key_parameters=("limit", "location_id"),
        constraints=("Read-only lookup; defaults should remain small enough for an interactive agent turn.",),
    ),
    ToolSpec(
        name="get_attendance",
        domain="hr",
        summary="Retrieve attendance records for an employee over a date range.",
        parameters=_schema(
            {
                "employee_id": _integer("The employee record ID."),
                "date_from": _string("Inclusive ISO timestamp or date for the range start."),
                "date_to": _string("Inclusive ISO timestamp or date for the range end."),
            },
            required=["employee_id"],
        ),
        key_parameters=("employee_id", "date_from", "date_to"),
        constraints=("Read-only lookup; employee_id must reference an existing employee.",),
    ),
    ToolSpec(
        name="correct_attendance",
        domain="hr",
        summary="Correct an attendance entry by updating check-in or check-out values.",
        parameters=_schema(
            {
                "attendance_id": _integer("The attendance record ID."),
                "check_in": _string("Replacement check-in timestamp in ISO format."),
                "check_out": _string("Replacement check-out timestamp in ISO format."),
            },
            required=["attendance_id"],
        ),
        key_parameters=("attendance_id", "check_in", "check_out"),
        constraints=(
            "At least one of check_in or check_out should be supplied.",
            "check_out should not be earlier than check_in.",
        ),
    ),
    ToolSpec(
        name="approve_leave",
        domain="hr",
        summary="Approve an employee leave request.",
        parameters=_schema(
            {
                "leave_id": _integer("The leave request ID."),
            },
            required=["leave_id"],
        ),
        key_parameters=("leave_id",),
        constraints=("Only pending leave requests should be approved.",),
    ),
    ToolSpec(
        name="reject_leave",
        domain="hr",
        summary="Reject an employee leave request with a reason.",
        parameters=_schema(
            {
                "leave_id": _integer("The leave request ID."),
                "reason": _string("The rejection reason to log."),
            },
            required=["leave_id", "reason"],
        ),
        key_parameters=("leave_id", "reason"),
        constraints=("Only pending leave requests should be rejected and the reason should be explicit.",),
    ),
    ToolSpec(
        name="get_employee_info",
        domain="hr",
        summary="Retrieve employee profile data including department, manager, and work contact fields.",
        parameters=_schema(
            {
                "employee_id": _integer("The employee record ID."),
            },
            required=["employee_id"],
        ),
        key_parameters=("employee_id",),
        constraints=("Read-only lookup; employee_id must exist in hr.employee.",),
    ),
    ToolSpec(
        name="create_ticket",
        domain="helpdesk",
        summary="Create a helpdesk-style ticket or project task for customer support work.",
        parameters=_schema(
            {
                "title": _string("Ticket title."),
                "description": _string("Ticket description or issue summary."),
                "partner_id": _integer("Optional customer ID."),
                "priority": _string("Ticket priority.", enum=["0", "1"]),
                "assignee_id": _integer("Optional assigned user ID."),
            },
            required=["title", "description"],
        ),
        key_parameters=("title", "description", "partner_id", "priority", "assignee_id"),
        constraints=("Provide enough issue detail for triage and use approved priority levels.",),
    ),
    ToolSpec(
        name="assign_ticket",
        domain="helpdesk",
        summary="Assign a support ticket to a user.",
        parameters=_schema(
            {
                "ticket_id": _integer("The ticket or task ID."),
                "user_id": _integer("The user who should own the ticket."),
            },
            required=["ticket_id", "user_id"],
        ),
        key_parameters=("ticket_id", "user_id"),
        constraints=("The target user should exist and be able to access the underlying team or project.",),
    ),
    ToolSpec(
        name="close_ticket",
        domain="helpdesk",
        summary="Close a support ticket and record a resolution note.",
        parameters=_schema(
            {
                "ticket_id": _integer("The ticket or task ID."),
                "resolution": _string("Resolution summary or close note."),
            },
            required=["ticket_id"],
        ),
        key_parameters=("ticket_id", "resolution"),
        constraints=("Only close tickets that are actually resolved or explicitly cancelled.",),
    ),
    ToolSpec(
        name="escalate_ticket",
        domain="helpdesk",
        summary="Escalate a support ticket by raising priority and optionally moving it to another team.",
        parameters=_schema(
            {
                "ticket_id": _integer("The ticket or task ID."),
                "reason": _string("Why the ticket is being escalated."),
                "priority": _string("Optional higher priority level.", enum=["0", "1"]),
                "team_id": _integer("Optional helpdesk team or project ID."),
            },
            required=["ticket_id", "reason"],
        ),
        key_parameters=("ticket_id", "reason", "priority", "team_id"),
        constraints=("Escalations should carry a clear reason and normally increase urgency rather than decrease it.",),
    ),
    ToolSpec(
        name="get_open_tickets",
        domain="helpdesk",
        summary="List open tickets, optionally filtered by assignee.",
        parameters=_schema(
            {
                "limit": _integer("Maximum number of open tickets to return."),
                "assignee_id": _integer("Optional assigned user ID."),
            },
            required=[],
        ),
        key_parameters=("limit", "assignee_id"),
        constraints=("Read-only lookup; keep the limit small enough for an agent turn.",),
    ),
    # =========================================================================
    # ADDITIONAL SALES AND INVENTORY TOOLS (expanded benchmark tasks)
    # =========================================================================
    ToolSpec(
        name="update_sale_order_discount",
        domain="sales",
        summary="Apply a percentage discount to every line on a sales quotation or order.",
        parameters=_schema(
            {
                "order_id": _integer("The sales order or quotation ID."),
                "discount_percent": _number("Discount percentage to apply to each order line."),
                "reason": _string("Optional reason or promotion name to log."),
            },
            required=["order_id", "discount_percent"],
        ),
        key_parameters=("order_id", "discount_percent", "reason"),
        constraints=(
            "Apply discounts only to eligible draft quotations unless policy explicitly allows otherwise.",
            "Discounts above approval thresholds require manager approval before being saved.",
        ),
    ),
    ToolSpec(
        name="create_delivery_backorder",
        domain="sales",
        summary="Create an immediate delivery for part of a confirmed sales order and backorder the remainder.",
        parameters=_schema(
            {
                "order_id": _integer("The confirmed sales order ID."),
                "product_id": _integer("The product being partially delivered."),
                "deliver_quantity": _number("Quantity to deliver now."),
                "backorder_quantity": _number("Quantity to leave on backorder."),
                "note": _string("Optional delivery or backorder note."),
            },
            required=["order_id", "product_id", "deliver_quantity", "backorder_quantity"],
        ),
        key_parameters=("order_id", "product_id", "deliver_quantity", "backorder_quantity"),
        constraints=(
            "Partial delivery should be used only when the full quantity cannot be fulfilled.",
            "Deliver only available, non-reserved stock.",
        ),
    ),
    ToolSpec(
        name="search_stock_locations",
        domain="inventory",
        summary="Search internal stock locations by name, complete name, or usage.",
        parameters=_schema(
            {
                "name": _string("Partial stock location name."),
                "complete_name": _string("Partial complete location path such as WH/Stock."),
                "usage": _string("Location usage.", enum=["internal", "supplier", "customer", "inventory", "transit"]),
                "limit": _integer("Maximum number of locations to return."),
            },
            required=[],
        ),
        key_parameters=("name", "complete_name", "usage"),
        constraints=("Use internal locations for warehouse-to-warehouse stock transfers.",),
    ),
    ToolSpec(
        name="search_reorder_rules",
        domain="inventory",
        summary="Search existing reorder rules for a product and optional stock location.",
        parameters=_schema(
            {
                "product_id": _integer("Product to inspect for existing reorder rules."),
                "location_id": _integer("Optional stock location filter."),
                "limit": _integer("Maximum number of reorder rules to return."),
            },
            required=["product_id"],
        ),
        key_parameters=("product_id", "location_id"),
        constraints=("Check for duplicates before creating a new reorder rule.",),
    ),
    ToolSpec(
        name="apply_inventory_adjustment",
        domain="inventory",
        summary="Apply a physical-count inventory adjustment with a written reason.",
        parameters=_schema(
            {
                "product_id": _integer("Product to adjust."),
                "quantity": _number("Target physical on-hand quantity."),
                "location_id": _integer("Stock location where the count was performed."),
                "reason": _string("Required reason for the inventory adjustment."),
            },
            required=["product_id", "quantity", "reason"],
        ),
        key_parameters=("product_id", "quantity", "location_id", "reason"),
        constraints=(
            "Inventory adjustments require a written reason.",
            "Do not adjust products tied to open confirmed orders until checked.",
        ),
    ),
    # =========================================================================
    # ADDITIONAL ACCOUNTING TOOLS
    # =========================================================================
    ToolSpec(
        name="get_invoice",
        domain="accounting",
        summary="Retrieve an invoice or credit note with lines, totals, payment state, and origin references.",
        parameters=_schema(
            {
                "invoice_id": _integer("The account.move record ID."),
                "invoice_number": _string("Optional invoice number or name to retrieve."),
            },
            required=[],
        ),
        key_parameters=("invoice_id", "invoice_number"),
        constraints=("Read-only lookup; provide either invoice_id or invoice_number.",),
    ),
    ToolSpec(
        name="create_credit_note",
        domain="accounting",
        summary="Create a customer credit note referencing an originating invoice.",
        parameters=_schema(
            {
                "invoice_id": _integer("Original invoice ID."),
                "amount": _number("Credit amount."),
                "reason": _string("Reason for the credit note."),
                "product_id": _integer("Optional product being credited."),
                "quantity": _number("Optional credited quantity."),
            },
            required=["invoice_id", "amount", "reason"],
        ),
        key_parameters=("invoice_id", "amount", "reason", "product_id", "quantity"),
        constraints=(
            "Credit notes must reference the originating invoice.",
            "Credit amount must not exceed the original invoice residual or applicable line amount.",
        ),
    ),
    ToolSpec(
        name="reconcile_payment",
        domain="accounting",
        summary="Apply a customer payment or credit note amount across one or more posted invoices.",
        parameters=_schema(
            {
                "customer_id": _integer("Customer partner ID."),
                "allocations": {
                    "type": "array",
                    "description": "Invoice allocations for the reconciliation.",
                    "items": _schema(
                        {
                            "invoice_id": _integer("Invoice receiving payment."),
                            "amount": _number("Amount to apply to this invoice."),
                        },
                        required=["invoice_id", "amount"],
                    ),
                },
                "payment_reference": _string("External payment or credit note reference."),
            },
            required=["customer_id", "allocations"],
        ),
        key_parameters=("customer_id", "allocations", "payment_reference"),
        constraints=(
            "Do not mark invoices fully paid unless the allocated amount clears the residual.",
            "Payment allocations must not exceed available payment amount.",
        ),
    ),
    ToolSpec(
        name="post_invoice",
        domain="accounting",
        summary="Post a draft customer invoice after duplicate and policy checks.",
        parameters=_schema(
            {
                "invoice_id": _integer("Draft invoice ID to post."),
                "approval_note": _string("Optional approval or review note."),
            },
            required=["invoice_id"],
        ),
        key_parameters=("invoice_id", "approval_note"),
        constraints=(
            "Do not post duplicate invoices for the same sale order.",
            "Do not post without explicit confirmation where policy requires it.",
        ),
    ),
    ToolSpec(
        name="flag_invoice_for_review",
        domain="accounting",
        summary="Flag an invoice for manual review without posting, cancelling, or paying it.",
        parameters=_schema(
            {
                "invoice_id": _integer("Invoice ID to flag."),
                "reason": _string("Review reason to log."),
            },
            required=["invoice_id", "reason"],
        ),
        key_parameters=("invoice_id", "reason"),
        constraints=("Use this for suspected duplicates or policy exceptions instead of unilateral cancellation.",),
    ),
    # =========================================================================
    # ADDITIONAL CRM, POS, HR, AND HELPDESK TOOLS
    # =========================================================================
    ToolSpec(
        name="get_lead",
        domain="crm",
        summary="Retrieve a CRM lead or opportunity with stage, partner, owner, and activity fields.",
        parameters=_schema(
            {
                "lead_id": _integer("CRM lead or opportunity ID."),
            },
            required=["lead_id"],
        ),
        key_parameters=("lead_id",),
        constraints=("Leads and customers are separate records; verify the intended record type.",),
    ),
    ToolSpec(
        name="update_lead_assignee",
        domain="crm",
        summary="Reassign a CRM lead or opportunity to a salesperson and optionally log why.",
        parameters=_schema(
            {
                "lead_id": _integer("CRM lead or opportunity ID."),
                "user_id": _integer("New salesperson user ID."),
                "reason": _string("Optional reassignment reason."),
            },
            required=["lead_id", "user_id"],
        ),
        key_parameters=("lead_id", "user_id", "reason"),
        constraints=("Do not reassign opportunities already marked won or lost.",),
    ),
    ToolSpec(
        name="flag_customer_duplicate",
        domain="crm",
        summary="Flag a customer record as a suspected duplicate pending manual merge review.",
        parameters=_schema(
            {
                "duplicate_customer_id": _integer("Customer record suspected to be duplicate."),
                "primary_customer_id": _integer("Likely primary customer record."),
                "note": _string("Review note explaining the duplicate relationship."),
            },
            required=["duplicate_customer_id", "primary_customer_id", "note"],
        ),
        key_parameters=("duplicate_customer_id", "primary_customer_id", "note"),
        constraints=("Do not delete or merge customer records unless explicitly approved.",),
    ),
    ToolSpec(
        name="search_users",
        domain="crm",
        summary="Search Odoo users or team members by name, team, role, or availability.",
        parameters=_schema(
            {
                "name": _string("Partial user name."),
                "team_name": _string("Sales, support, project, or department team name."),
                "available_only": _boolean("Only return users currently available for assignment."),
                "limit": _integer("Maximum number of users to return."),
            },
            required=[],
        ),
        key_parameters=("name", "team_name", "available_only"),
        constraints=("Verify team membership before assigning work to a user.",),
    ),
    ToolSpec(
        name="search_pos_orders",
        domain="pos",
        summary="Search POS orders by customer, product, state, date range, or order name.",
        parameters=_schema(
            {
                "order_name": _string("POS order name or reference."),
                "customer_id": _integer("Customer partner ID."),
                "product_id": _integer("Product contained in POS order lines."),
                "state": _string("POS order state.", enum=["draft", "paid", "done", "cancel"]),
                "date_from": _string("Inclusive ISO date or datetime start."),
                "date_to": _string("Inclusive ISO date or datetime end."),
                "limit": _integer("Maximum number of POS orders to return."),
            },
            required=[],
        ),
        key_parameters=("order_name", "customer_id", "product_id", "state", "date_from", "date_to"),
        constraints=("Use POS refund workflows only for POS orders, not sale.order records.",),
    ),
    ToolSpec(
        name="get_pos_session_summary",
        domain="pos",
        summary="Summarize a POS session or date range with gross sales, refunds, and net revenue.",
        parameters=_schema(
            {
                "session_id": _integer("Optional POS session ID."),
                "date_from": _string("Inclusive ISO date or datetime start."),
                "date_to": _string("Inclusive ISO date or datetime end."),
            },
            required=[],
        ),
        key_parameters=("session_id", "date_from", "date_to"),
        constraints=("Read-only reconciliation; do not close or modify sessions during reporting.",),
    ),
    ToolSpec(
        name="search_employees",
        domain="hr",
        summary="Search employees by name, department, work email, or manager.",
        parameters=_schema(
            {
                "name": _string("Partial employee name."),
                "department": _string("Department name."),
                "work_email": _string("Work email address."),
                "manager_id": _integer("Manager employee ID."),
                "limit": _integer("Maximum number of employees to return."),
            },
            required=[],
        ),
        key_parameters=("name", "department", "work_email", "manager_id"),
        constraints=("Same-name employees must be disambiguated by department, email, or manager.",),
    ),
    ToolSpec(
        name="search_leave_requests",
        domain="hr",
        summary="Search HR leave requests by employee, state, leave type, and date range.",
        parameters=_schema(
            {
                "employee_id": _integer("Employee ID."),
                "employee_name": _string("Employee name search."),
                "state": _string("Leave state.", enum=["draft", "confirm", "validate1", "validate", "refuse", "cancel"]),
                "date_from": _string("Inclusive start date."),
                "date_to": _string("Inclusive end date."),
                "limit": _integer("Maximum number of leave requests to return."),
            },
            required=[],
        ),
        key_parameters=("employee_id", "employee_name", "state", "date_from", "date_to"),
        constraints=("Check overlapping approved leaves before approving a new request.",),
    ),
    ToolSpec(
        name="get_leave_balance",
        domain="hr",
        summary="Retrieve remaining leave balance for an employee and leave type.",
        parameters=_schema(
            {
                "employee_id": _integer("Employee ID."),
                "leave_type": _string("Leave type such as annual, sick, or unpaid."),
            },
            required=["employee_id"],
        ),
        key_parameters=("employee_id", "leave_type"),
        constraints=("Read-only lookup; leave approval should not exceed available balance.",),
    ),
    ToolSpec(
        name="search_tickets",
        domain="helpdesk",
        summary="Search helpdesk tickets by customer, title, state, priority, assignee, or team.",
        parameters=_schema(
            {
                "partner_id": _integer("Customer partner ID."),
                "title": _string("Partial ticket title or subject."),
                "state": _string("Ticket state or stage name."),
                "priority": _string("Priority value.", enum=["0", "1"]),
                "assignee_id": _integer("Assigned user ID."),
                "team_id": _integer("Helpdesk team ID."),
                "limit": _integer("Maximum number of tickets to return."),
            },
            required=[],
        ),
        key_parameters=("partner_id", "title", "state", "priority", "assignee_id", "team_id"),
        constraints=("Use precise filters when customers have multiple tickets.",),
    ),
    ToolSpec(
        name="get_ticket",
        domain="helpdesk",
        summary="Retrieve a helpdesk ticket with notes, state, priority, customer, and assignee details.",
        parameters=_schema(
            {
                "ticket_id": _integer("Helpdesk ticket ID."),
                "include_notes": _boolean("Whether to include ticket notes and message history."),
            },
            required=["ticket_id"],
        ),
        key_parameters=("ticket_id", "include_notes"),
        constraints=("Read-only lookup; verify resolution evidence before closing a ticket.",),
    ),
    # =========================================================================
    # PURCHASE TOOLS
    # =========================================================================
    ToolSpec(
        name="search_vendors",
        domain="purchase",
        summary="Search vendor partners by name, email, product supplied, or preferred-vendor status.",
        parameters=_schema(
            {
                "name": _string("Partial vendor name."),
                "email": _string("Vendor email."),
                "product_id": _integer("Product supplied by the vendor."),
                "preferred_only": _boolean("Only return preferred vendors for the product."),
                "limit": _integer("Maximum number of vendors to return."),
            },
            required=[],
        ),
        key_parameters=("name", "email", "product_id", "preferred_only"),
        constraints=("Verify the correct vendor before creating or confirming a purchase order.",),
    ),
    ToolSpec(
        name="get_vendor_pricelist",
        domain="purchase",
        summary="Retrieve supplierinfo pricing for a vendor and optional product.",
        parameters=_schema(
            {
                "vendor_id": _integer("Vendor partner ID."),
                "product_id": _integer("Optional product ID."),
            },
            required=["vendor_id"],
        ),
        key_parameters=("vendor_id", "product_id"),
        constraints=("Use current supplierinfo pricing when checking PO price drift.",),
    ),
    ToolSpec(
        name="search_purchase_orders",
        domain="purchase",
        summary="Search purchase orders by vendor, product, state, date range, or order name.",
        parameters=_schema(
            {
                "order_name": _string("Purchase order name or reference."),
                "vendor_id": _integer("Vendor partner ID."),
                "product_id": _integer("Product contained in PO lines."),
                "state": _string("PO state.", enum=["draft", "sent", "to approve", "purchase", "done", "cancel"]),
                "date_from": _string("Inclusive order date start."),
                "date_to": _string("Inclusive order date end."),
                "limit": _integer("Maximum number of purchase orders to return."),
            },
            required=[],
        ),
        key_parameters=("order_name", "vendor_id", "product_id", "state", "date_from", "date_to"),
        constraints=("Check for existing draft POs before creating another for the same vendor and product.",),
    ),
    ToolSpec(
        name="get_purchase_order",
        domain="purchase",
        summary="Retrieve a purchase order with vendor, state, totals, lines, receipts, and approval notes.",
        parameters=_schema(
            {
                "order_id": _integer("Purchase order ID."),
                "order_name": _string("Optional purchase order name or reference."),
            },
            required=[],
        ),
        key_parameters=("order_id", "order_name"),
        constraints=("Read-only lookup; provide either order_id or order_name.",),
    ),
    ToolSpec(
        name="create_purchase_order",
        domain="purchase",
        summary="Create a draft purchase order for a vendor with product lines.",
        parameters=_schema(
            {
                "vendor_id": _integer("Vendor partner ID."),
                "lines": {
                    "type": "array",
                    "description": "Purchase order lines.",
                    "items": _schema(
                        {
                            "product_id": _integer("Product to purchase."),
                            "quantity": _number("Quantity to purchase."),
                            "price_unit": _number("Optional unit purchase price."),
                        },
                        required=["product_id", "quantity"],
                    ),
                },
                "note": _string("Optional PO note."),
            },
            required=["vendor_id", "lines"],
        ),
        key_parameters=("vendor_id", "lines", "note"),
        constraints=(
            "Create duplicate POs only with explicit justification.",
            "POs above approval thresholds must remain draft or to approve until approved.",
        ),
    ),
    ToolSpec(
        name="confirm_purchase_order",
        domain="purchase",
        summary="Confirm a draft or sent purchase order.",
        parameters=_schema(
            {
                "order_id": _integer("Purchase order ID to confirm."),
                "approval_note": _string("Manager approval reference when required."),
            },
            required=["order_id"],
        ),
        key_parameters=("order_id", "approval_note"),
        constraints=(
            "Purchase orders exceeding approval thresholds require manager approval before confirmation.",
            "Verify vendor and pricing before confirming.",
        ),
    ),
    ToolSpec(
        name="receive_purchase_order",
        domain="purchase",
        summary="Receive delivered quantities against a purchase order and optionally create a backorder.",
        parameters=_schema(
            {
                "order_id": _integer("Purchase order ID."),
                "receipts": {
                    "type": "array",
                    "description": "Received quantities by product.",
                    "items": _schema(
                        {
                            "product_id": _integer("Received product."),
                            "quantity": _number("Physically received quantity."),
                            "location_id": _integer("Destination stock location."),
                        },
                        required=["product_id", "quantity"],
                    ),
                },
                "create_backorder": _boolean("Whether to backorder outstanding quantities."),
            },
            required=["order_id", "receipts"],
        ),
        key_parameters=("order_id", "receipts", "create_backorder"),
        constraints=(
            "Receive only quantities that physically arrived.",
            "Outstanding quantities should remain open or be backordered.",
        ),
    ),
    ToolSpec(
        name="create_vendor_return",
        domain="purchase",
        summary="Create a return to vendor for received goods and decrement stock from the receipt location.",
        parameters=_schema(
            {
                "order_id": _integer("Original purchase order ID."),
                "vendor_id": _integer("Vendor partner ID."),
                "product_id": _integer("Product being returned."),
                "quantity": _number("Quantity to return."),
                "location_id": _integer("Stock location to return from."),
                "reason": _string("Return reason."),
            },
            required=["order_id", "vendor_id", "product_id", "quantity", "reason"],
        ),
        key_parameters=("order_id", "vendor_id", "product_id", "quantity", "location_id", "reason"),
        constraints=(
            "Vendor returns must reference the original purchase order.",
            "Return quantity must not exceed received quantity.",
        ),
    ),
    # =========================================================================
    # MANUFACTURING TOOLS
    # =========================================================================
    ToolSpec(
        name="search_boms",
        domain="manufacturing",
        summary="Search bills of materials by product, component, active flag, or BOM code.",
        parameters=_schema(
            {
                "product_id": _integer("Finished product ID."),
                "product_name": _string("Finished product name search."),
                "component_id": _integer("Component product ID contained in the BOM."),
                "active": _boolean("Filter active or archived BOMs."),
                "limit": _integer("Maximum number of BOMs to return."),
            },
            required=[],
        ),
        key_parameters=("product_id", "product_name", "component_id", "active"),
        constraints=("Use the active BOM unless the task explicitly requires archived or historical versions.",),
    ),
    ToolSpec(
        name="get_bom",
        domain="manufacturing",
        summary="Retrieve a BOM with component lines, quantities, active status, and product details.",
        parameters=_schema(
            {
                "bom_id": _integer("BOM ID."),
            },
            required=["bom_id"],
        ),
        key_parameters=("bom_id",),
        constraints=("Read-only lookup; verify BOM active status before scheduling production.",),
    ),
    ToolSpec(
        name="search_production_orders",
        domain="manufacturing",
        summary="Search production orders by product, BOM, state, availability, scheduled date, or order name.",
        parameters=_schema(
            {
                "order_name": _string("Manufacturing order name or reference."),
                "product_id": _integer("Finished product ID."),
                "bom_id": _integer("BOM ID."),
                "state": _string("Manufacturing order state.", enum=["draft", "confirmed", "progress", "to_close", "done", "cancel"]),
                "availability": _string("Component availability status."),
                "scheduled_date": _string("Scheduled date filter."),
                "scheduled_date_from": _string("Inclusive scheduled date start."),
                "scheduled_date_to": _string("Inclusive scheduled date end."),
                "limit": _integer("Maximum number of production orders to return."),
            },
            required=[],
        ),
        key_parameters=("order_name", "product_id", "bom_id", "state", "availability", "scheduled_date"),
        constraints=("Read-only search; check combined component demand before starting multiple orders.",),
    ),
    ToolSpec(
        name="get_production_order",
        domain="manufacturing",
        summary="Retrieve a production order with product, quantity, BOM, state, availability, and component moves.",
        parameters=_schema(
            {
                "order_id": _integer("Manufacturing order ID."),
                "order_name": _string("Optional manufacturing order name or reference."),
            },
            required=[],
        ),
        key_parameters=("order_id", "order_name"),
        constraints=("Provide either order_id or order_name; verify component availability before starting.",),
    ),
    ToolSpec(
        name="create_production_order",
        domain="manufacturing",
        summary="Create and schedule a manufacturing order for a finished product and BOM.",
        parameters=_schema(
            {
                "product_id": _integer("Finished product ID."),
                "quantity": _number("Quantity to produce."),
                "bom_id": _integer("BOM ID."),
                "scheduled_date": _string("Scheduled production date."),
                "note": _string("Optional production note."),
            },
            required=["product_id", "quantity", "bom_id"],
        ),
        key_parameters=("product_id", "quantity", "bom_id", "scheduled_date"),
        constraints=(
            "Verify all components are available before scheduling.",
            "Production orders must reference a valid BOM version.",
        ),
    ),
    ToolSpec(
        name="start_production_order",
        domain="manufacturing",
        summary="Start a confirmed production order after component availability checks.",
        parameters=_schema(
            {
                "order_id": _integer("Manufacturing order ID to start."),
            },
            required=["order_id"],
        ),
        key_parameters=("order_id",),
        constraints=("Do not start production when any required component is unavailable.",),
    ),
    ToolSpec(
        name="create_bom_version",
        domain="manufacturing",
        summary="Create a new BOM version for a product with specified component lines.",
        parameters=_schema(
            {
                "product_id": _integer("Finished product ID."),
                "source_bom_id": _integer("Existing BOM to copy from, if any."),
                "lines": {
                    "type": "array",
                    "description": "Component lines for the new BOM.",
                    "items": _schema(
                        {
                            "component_product_id": _integer("Component product ID."),
                            "quantity": _number("Component quantity per finished product."),
                        },
                        required=["component_product_id", "quantity"],
                    ),
                },
                "active": _boolean("Whether the new BOM should be active."),
                "note": _string("Optional version note."),
            },
            required=["product_id", "lines"],
        ),
        key_parameters=("product_id", "source_bom_id", "lines", "active"),
        constraints=("BOM changes must be versioned; do not overwrite active BOMs directly.",),
    ),
    ToolSpec(
        name="archive_bom",
        domain="manufacturing",
        summary="Archive a BOM version by setting it inactive.",
        parameters=_schema(
            {
                "bom_id": _integer("BOM ID to archive."),
                "reason": _string("Reason for archiving."),
            },
            required=["bom_id"],
        ),
        key_parameters=("bom_id", "reason"),
        constraints=("Check active production orders referencing the BOM before archiving.",),
    ),
    # =========================================================================
    # PROJECT TOOLS
    # =========================================================================
    ToolSpec(
        name="search_projects",
        domain="project",
        summary="Search projects by name, active flag, team member, or budget status.",
        parameters=_schema(
            {
                "name": _string("Partial project name."),
                "active": _boolean("Filter active or archived projects."),
                "user_id": _integer("Project member or manager user ID."),
                "limit": _integer("Maximum number of projects to return."),
            },
            required=[],
        ),
        key_parameters=("name", "active", "user_id"),
        constraints=("Same-name projects should be disambiguated before creating tasks.",),
    ),
    ToolSpec(
        name="get_project",
        domain="project",
        summary="Retrieve project details including active status, team members, budget, and task counts.",
        parameters=_schema(
            {
                "project_id": _integer("Project ID."),
            },
            required=["project_id"],
        ),
        key_parameters=("project_id",),
        constraints=("Read-only lookup; check budget before creating tasks with additional spend.",),
    ),
    ToolSpec(
        name="search_project_tasks",
        domain="project",
        summary="Search project tasks by title, project, assignee, state, deadline, blocked status, or parent task.",
        parameters=_schema(
            {
                "task_name": _string("Partial task title."),
                "project_id": _integer("Project ID."),
                "assignee_id": _integer("Assigned user ID."),
                "state": _string("Task state or stage name."),
                "deadline_before": _string("Return tasks with deadline before this date."),
                "blocked_only": _boolean("Only return tasks with open dependencies or subtasks."),
                "parent_task_id": _integer("Parent task ID."),
                "limit": _integer("Maximum number of tasks to return."),
            },
            required=[],
        ),
        key_parameters=("task_name", "project_id", "assignee_id", "state", "deadline_before", "blocked_only"),
        constraints=("Archived project tasks should be excluded from active status reports.",),
    ),
    ToolSpec(
        name="get_project_task",
        domain="project",
        summary="Retrieve a project task with project, assignee, state, deadline, subtasks, dependencies, and budget.",
        parameters=_schema(
            {
                "task_id": _integer("Project task ID."),
            },
            required=["task_id"],
        ),
        key_parameters=("task_id",),
        constraints=("Read-only lookup; verify subtasks and deliverables before closing.",),
    ),
    ToolSpec(
        name="create_project_task",
        domain="project",
        summary="Create a task in a project and optionally assign it to a user with a budget.",
        parameters=_schema(
            {
                "project_id": _integer("Project ID."),
                "title": _string("Task title."),
                "description": _string("Optional task description."),
                "user_id": _integer("Optional assignee user ID."),
                "deadline": _string("Optional deadline date."),
                "budget": _number("Optional task budget or planned cost."),
            },
            required=["project_id", "title"],
        ),
        key_parameters=("project_id", "title", "user_id", "deadline", "budget"),
        constraints=(
            "Verify project identity when names are ambiguous.",
            "Check assignee capacity and budget constraints before creation.",
        ),
    ),
    ToolSpec(
        name="reassign_project_task",
        domain="project",
        summary="Reassign a project task to another team member.",
        parameters=_schema(
            {
                "task_id": _integer("Project task ID."),
                "user_id": _integer("New assignee user ID."),
                "reason": _string("Reason for reassignment."),
            },
            required=["task_id", "user_id"],
        ),
        key_parameters=("task_id", "user_id", "reason"),
        constraints=(
            "Assignee must be on the project team and have capacity.",
            "Do not assign work to users currently on approved leave.",
        ),
    ),
    ToolSpec(
        name="close_project_task",
        domain="project",
        summary="Close or mark a project task done with an optional completion note.",
        parameters=_schema(
            {
                "task_id": _integer("Project task ID."),
                "resolution": _string("Optional completion or resolution note."),
            },
            required=["task_id"],
        ),
        key_parameters=("task_id", "resolution"),
        constraints=("Do not close tasks with open subtasks, open dependencies, or missing required deliverables.",),
    ),
    ToolSpec(
        name="get_project_workload",
        domain="project",
        summary="Return open task counts and availability for project team members.",
        parameters=_schema(
            {
                "project_id": _integer("Project ID."),
                "include_leave_status": _boolean("Whether to include approved leave status."),
            },
            required=[],
        ),
        key_parameters=("project_id", "include_leave_status"),
        constraints=("Use workload and leave status before assigning or reassigning tasks.",),
    ),
]


def get_tool_schema(tool_name: str, knowledge_level: str = "KL1") -> JSONSchema:
    for tool in TOOL_REGISTRY:
        if tool.name == tool_name:
            return tool.to_openai_tool(knowledge_level)
    raise KeyError(f"Unknown tool: {tool_name}")


def get_openai_tools(knowledge_level: str) -> list[JSONSchema]:
    return [tool.to_openai_tool(knowledge_level) for tool in TOOL_REGISTRY]


def get_anthropic_tools(knowledge_level: str) -> list[JSONSchema]:
    return [tool.to_anthropic_tool(knowledge_level) for tool in TOOL_REGISTRY]
