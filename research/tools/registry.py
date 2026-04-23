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
                "product_name": _string("Partial or full product name in order lines."),
                "state": _string("Order state filter.", enum=["draft", "sent", "sale", "done", "cancel"]),
                "limit": _integer("Maximum number of orders to return."),
            },
            required=[],
        ),
        key_parameters=("customer_name", "customer_id", "product_name", "state"),
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
                "state": _string("Invoice state.", enum=["draft", "posted", "cancel"]),
                "overdue_only": _boolean("Only return overdue unpaid invoices."),
                "limit": _integer("Maximum number of invoices to return."),
            },
            required=[],
        ),
        key_parameters=("customer_id", "state", "overdue_only"),
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
        summary="Check on-hand and reserved stock for a product.",
        parameters=_schema(
            {
                "product_id": _integer("The product to inspect."),
                "location_id": _integer("Optional stock location ID."),
            },
            required=["product_id"],
        ),
        key_parameters=("product_id", "location_id"),
        constraints=("Read-only lookup; use a location filter when a warehouse-specific answer is required.",),
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
                "priority": _string("Ticket priority.", enum=["0", "1", "2", "3"]),
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
                "priority": _string("Optional higher priority level.", enum=["0", "1", "2", "3"]),
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
