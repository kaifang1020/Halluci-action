#!/usr/bin/env python3
"""
Database reset script for Halluci-Action experiments.

This script resets the Odoo database to its initial state by:
1. Cancelling and deleting modified sales orders
2. Re-creating the original test data

Run this BEFORE each experiment to ensure a clean slate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.config import OdooConfig
from research.tools.odoo_tools import OdooJSONRPCClient, OdooRPCError


def reset_database(config: OdooConfig | None = None) -> None:
    """Reset the database to initial state for experiments."""
    config = config or OdooConfig()
    client = OdooJSONRPCClient(config)

    print("=" * 60)
    print("Resetting Odoo Database for Halluci-Action Experiments")
    print("=" * 60)

    # Step 1: Cancel and delete all sales orders
    print("\n=== Resetting Sales Orders ===")
    orders = client.search_read("sale.order", [], ["name", "state"])
    for order in orders:
        order_id = order["id"]
        order_name = order["name"]
        order_state = order["state"]

        try:
            # Cancel if not already cancelled
            if order_state not in ("cancel", "draft"):
                try:
                    client.execute_kw("sale.order", "action_cancel", [[order_id]])
                    print(f"  Cancelled: {order_name}")
                except OdooRPCError:
                    # Force cancel via write
                    client.write("sale.order", [order_id], {"state": "cancel"})
                    print(f"  Force-cancelled: {order_name}")

            # Set to draft so we can delete
            try:
                client.write("sale.order", [order_id], {"state": "draft"})
            except OdooRPCError:
                pass

            # Delete the order
            client.execute_kw("sale.order", "unlink", [[order_id]])
            print(f"  Deleted: {order_name}")
        except OdooRPCError as e:
            # Last resort: just leave it cancelled
            print(f"  Warning: Could not delete {order_name}, left in cancelled state: {e}")

    # Step 2: Reset stock quants to remove reservations
    print("\n=== Resetting Stock Quants ===")
    quants = client.search("stock.quant", [["reserved_quantity", ">", 0]])
    if quants:
        client.write("stock.quant", quants, {"reserved_quantity": 0})
        print(f"  Reset {len(quants)} quants with reservations")

    # Step 3: Delete CRM leads (will be re-created)
    print("\n=== Resetting CRM Leads ===")
    leads = client.search("crm.lead", [])
    if leads:
        try:
            client.execute_kw("crm.lead", "unlink", [leads])
            print(f"  Deleted {len(leads)} leads")
        except OdooRPCError as e:
            print(f"  Warning: Could not delete leads: {e}")

    # Step 4: Delete invoices (will be re-created)
    print("\n=== Resetting Invoices ===")
    invoices = client.search("account.move", [["move_type", "=", "out_invoice"]])
    for inv_id in invoices:
        try:
            # Reset to draft first
            inv_data = client.read("account.move", [inv_id], ["state"])
            if inv_data and inv_data[0].get("state") == "posted":
                try:
                    client.execute_kw("account.move", "button_draft", [[inv_id]])
                except OdooRPCError:
                    pass
            client.execute_kw("account.move", "unlink", [[inv_id]])
            print(f"  Deleted invoice {inv_id}")
        except OdooRPCError as e:
            print(f"  Warning: Could not delete invoice {inv_id}: {e}")

    print("\n=== Database Reset Complete ===")
    print("Now run: python potential_scripts/furnish_database.py")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reset Odoo database for experiments")
    parser.add_argument("--url", default=None, help="Odoo URL")
    parser.add_argument("--db", default=None, help="Database name")
    parser.add_argument("--user", default=None, help="Username")
    parser.add_argument("--password", default=None, help="Password")

    args = parser.parse_args()

    config = OdooConfig()
    if args.url:
        config.url = args.url
    if args.db:
        config.db = args.db
    if args.user:
        config.username = args.user
    if args.password:
        config.password = args.password

    reset_database(config)


if __name__ == "__main__":
    main()
