"""AI Buyer Agent — demonstrates end-to-end agentic commerce flow.

This agent autonomously:
1. Discovers the merchant's capabilities
2. Browses the agent-readable catalog
3. Searches for products
4. Creates a cart with spending bound
5. Adds items, reviews recommendations
6. Applies campaign codes
7. Initiates checkout (preview phase)
8. Confirms checkout (creates Razorpay order + payment link)
9. Checks payment status

Usage:
    python -m agent.buyer_agent                     # Interactive mode
    python -m agent.buyer_agent --auto              # Automatic happy path
    python -m agent.buyer_agent --budget 15000      # Custom budget (in rupees)
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Optional

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich import box

console = Console()

DEFAULT_BASE_URL = "http://localhost:8000"
AGENT_ID = "ai_buyer_agent_001"


class AIBuyerAgent:
    """Autonomous AI buyer agent for agentic commerce."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, budget_rupees: float = 200.0):
        self.base_url = base_url.rstrip("/")
        self.budget_paise = int(budget_rupees * 100)
        self.client = httpx.Client(timeout=30.0)
        self.cart_id: Optional[str] = None
        self.order_id: Optional[str] = None

    def _get(self, path: str) -> dict:
        r = self.client.get(f"{self.base_url}{path}")
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json: dict | None = None) -> dict:
        r = self.client.post(f"{self.base_url}{path}", json=json or {})
        if r.status_code >= 400:
            console.print(f"[red]Error {r.status_code}:[/red] {r.text}")
            return {"error": r.text, "status_code": r.status_code}
        return r.json()

    def _delete(self, path: str) -> dict:
        r = self.client.delete(f"{self.base_url}{path}")
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Step 1: Discover merchant capabilities
    # ------------------------------------------------------------------

    def discover(self) -> dict:
        console.print("\n[bold cyan]═══ Step 1: Discovering Merchant ═══[/bold cyan]")
        manifest = self._get("/")
        console.print(Panel(
            f"[bold]{manifest.get('name', 'Unknown')}[/bold]\n"
            f"{manifest.get('description', '')}\n\n"
            f"Version: {manifest.get('version', '?')}\n"
            f"Payment: {manifest.get('payment_provider', '?')}\n"
            f"Capabilities: {', '.join(manifest.get('capabilities', []))}",
            title="🏪 Merchant Manifest",
            border_style="cyan",
        ))
        return manifest

    # ------------------------------------------------------------------
    # Step 2: Browse catalog
    # ------------------------------------------------------------------

    def browse_catalog(self) -> dict:
        console.print("\n[bold cyan]═══ Step 2: Browsing Catalog (JSON-LD) ═══[/bold cyan]")
        catalog = self._get("/catalog")

        table = Table(title="📦 Product Catalog (Schema.org ItemList)", box=box.ROUNDED)
        table.add_column("#", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Category")
        table.add_column("Price", justify="right", style="green")
        table.add_column("Stock", justify="right")
        table.add_column("ID", style="dim")

        for item in catalog.get("itemListElement", []):
            p = item.get("item", {})
            offer = p.get("offers", {})
            table.add_row(
                str(item.get("position", "")),
                p.get("name", ""),
                p.get("category", ""),
                f"₹{float(offer.get('price', 0)):,.2f}",
                "✅" if "InStock" in offer.get("availability", "") else "❌",
                p.get("sku", ""),
            )

        console.print(table)
        console.print(f"[dim]Total products: {catalog.get('numberOfItems', 0)}[/dim]")
        return catalog

    # ------------------------------------------------------------------
    # Step 3: Search for specific products
    # ------------------------------------------------------------------

    def search(self, query: str = "", category: str = "") -> dict:
        console.print(f"\n[bold cyan]═══ Step 3: Searching (q='{query}', category='{category}') ═══[/bold cyan]")
        params = []
        if query:
            params.append(f"q={query}")
        if category:
            params.append(f"category={category}")
        qs = "?" + "&".join(params) if params else ""
        results = self._get(f"/catalog/search{qs}")

        console.print(f"Found [bold]{results.get('count', 0)}[/bold] products")
        for r in results.get("results", []):
            offer = r.get("offers", {})
            console.print(f"  • {r.get('name')} — ₹{float(offer.get('price', 0)):,.2f}")
        return results

    # ------------------------------------------------------------------
    # Step 4: Create cart with spending bound
    # ------------------------------------------------------------------

    def create_cart(self) -> dict:
        console.print(f"\n[bold cyan]═══ Step 4: Creating Cart (Budget: ₹{self.budget_paise / 100:,.2f}) ═══[/bold cyan]")
        result = self._post("/cart", {
            "agent_id": AGENT_ID,
            "max_budget_paise": self.budget_paise,
        })
        self.cart_id = result.get("cart_id")
        bound = result.get("spending_bound", {})
        console.print(Panel(
            f"Cart ID: [bold]{self.cart_id}[/bold]\n"
            f"Budget: {bound.get('max_amount_display', 'None')}\n"
            f"Status: {bound.get('status', 'No bound')}",
            title="🛒 Cart Created",
            border_style="green",
        ))
        return result

    # ------------------------------------------------------------------
    # Step 5: Add items to cart
    # ------------------------------------------------------------------

    def add_item(self, product_id: str, quantity: int = 1) -> dict:
        console.print(f"\n[bold cyan]Adding {quantity}x {product_id}...[/bold cyan]")
        result = self._post(f"/cart/{self.cart_id}/items", {
            "product_id": product_id,
            "quantity": quantity,
        })
        msg = result.get("message", "")
        if "REJECTED" in msg or "error" in result:
            console.print(f"[red]⛔ {msg}[/red]")
        else:
            console.print(f"[green]✅ {msg}[/green]")

        # Show recommendations if any
        cart = result.get("cart", {})
        recs = cart.get("recommendations", [])
        if recs:
            console.print("\n[yellow]💡 Recommendations:[/yellow]")
            for r in recs[:3]:
                console.print(
                    f"  [{r['type'].upper()}] {r['product_name']} ({r['price']}) — {r['reason']}"
                )
                if r.get("discount_hint"):
                    console.print(f"    💰 {r['discount_hint']}")

        return result

    # ------------------------------------------------------------------
    # Step 6: Apply campaign
    # ------------------------------------------------------------------

    def view_campaigns(self) -> dict:
        console.print("\n[bold cyan]═══ Available Campaigns ═══[/bold cyan]")
        result = self._get("/campaigns")
        for c in result.get("campaigns", []):
            console.print(
                f"  🏷️  [bold]{c['code']}[/bold] — {c['description']} "
                f"(max {c['max_discount_display']}, min cart {c['min_cart_display']})"
            )
        return result

    def apply_campaign(self, code: str) -> dict:
        console.print(f"\n[bold cyan]Applying campaign: {code}[/bold cyan]")
        result = self._post(f"/cart/{self.cart_id}/apply-campaign", {"code": code})
        if result.get("success"):
            console.print(f"[green]✅ {result.get('message', '')}[/green]")
        else:
            console.print(f"[red]⛔ {result.get('message', '')}[/red]")
        return result

    # ------------------------------------------------------------------
    # Step 7: Preview checkout
    # ------------------------------------------------------------------

    def preview_checkout(self) -> dict:
        console.print("\n[bold cyan]═══ Step 7: Checkout Preview ═══[/bold cyan]")
        result = self._post(f"/cart/{self.cart_id}/checkout")

        if "error" in result:
            console.print(f"[red]⛔ {result.get('error', result.get('detail', 'Unknown error'))}[/red]")
            return result

        table = Table(title="📋 Order Preview", box=box.ROUNDED)
        table.add_column("Item")
        table.add_column("Qty", justify="right")
        table.add_column("Total", justify="right", style="green")

        for item in result.get("items", []):
            table.add_row(
                item.get("name", ""),
                str(item.get("quantity", "")),
                f"₹{item.get('line_total_paise', 0) / 100:,.2f}",
            )

        console.print(table)
        console.print(f"  Subtotal: ₹{result.get('subtotal_paise', 0) / 100:,.2f}")
        if result.get("discount_paise", 0) > 0:
            console.print(f"  [yellow]Discount: -₹{result['discount_paise'] / 100:,.2f} ({result.get('campaign_code', '')})[/yellow]")
        console.print(f"  [bold green]Total: {result.get('total_display', '?')}[/bold green]")
        console.print(f"  Budget: {result.get('spending_bound_status', 'N/A')}")
        console.print(f"\n  ⚠️  {result.get('message', '')}")
        return result

    # ------------------------------------------------------------------
    # Step 8: Confirm checkout
    # ------------------------------------------------------------------

    def confirm_checkout(self) -> dict:
        console.print("\n[bold cyan]═══ Step 8: Confirming Checkout ═══[/bold cyan]")
        result = self._post(f"/cart/{self.cart_id}/confirm", {
            "customer_name": "AI Test Buyer",
            "customer_email": "ai.buyer@test.example.com",
            "customer_contact": "+919876543210",
        })

        if "error" in result:
            console.print(f"[red]⛔ Checkout failed: {result.get('error', result.get('detail', ''))}[/red]")
            return result

        self.order_id = result.get("order_id")

        console.print(Panel(
            f"[bold green]✅ ORDER CONFIRMED[/bold green]\n\n"
            f"Order ID: {self.order_id}\n"
            f"Razorpay Order: {result.get('razorpay_order_id', 'N/A')}\n"
            f"Total: {result.get('total_display', '?')}\n"
            f"Payment Link: [link={result.get('payment_link_url', '')}]{result.get('payment_link_url', 'N/A')}[/link]\n"
            f"Expires: {result.get('expires_in', '?')}\n\n"
            f"[dim]Test payment:[/dim]\n"
            f"  Card: {result.get('test_payment_info', {}).get('card', '')}\n"
            f"  UPI (success): {result.get('test_payment_info', {}).get('upi_success', '')}\n"
            f"  UPI (failure): {result.get('test_payment_info', {}).get('upi_failure', '')}",
            title="🧾 Order Confirmation",
            border_style="green",
        ))

        # Show audit trail
        trail = result.get("audit_trail", [])
        if trail:
            console.print("\n[bold]📝 Audit Trail:[/bold]")
            for entry in trail:
                gate = entry.get("gate", "n/a")
                icon = "✅" if gate == "passed" else "⛔" if gate == "rejected" else "📋"
                console.print(
                    f"  {icon} [{entry.get('timestamp', '')[:19]}] "
                    f"{entry.get('action', '')} — {entry.get('explanation', '')[:100]}"
                )

        return result

    # ------------------------------------------------------------------
    # Step 9: Check payment status
    # ------------------------------------------------------------------

    def check_status(self) -> dict:
        console.print(f"\n[bold cyan]═══ Step 9: Checking Payment Status ═══[/bold cyan]")
        if not self.order_id:
            console.print("[red]No order to check.[/red]")
            return {}
        result = self._get(f"/orders/{self.order_id}/status")
        status = result.get("status", "unknown")
        icon = "✅" if status == "paid" else "⏳" if status == "created" else "❌"
        console.print(f"  {icon} Status: [bold]{status}[/bold]")
        console.print(f"  Payment Link: {result.get('payment_link_url', 'N/A')}")
        if result.get("paid_at"):
            console.print(f"  Paid at: {result['paid_at']}")
        return result

    # ------------------------------------------------------------------
    # Full automated flow
    # ------------------------------------------------------------------

    def run_full_flow(self):
        """Execute the complete agentic commerce flow."""
        console.print(Panel(
            f"[bold]AI Buyer Agent[/bold] — Full Automated Flow\n"
            f"Server: {self.base_url}\n"
            f"Budget: ₹{self.budget_paise / 100:,.2f}\n"
            f"Agent ID: {AGENT_ID}",
            title="🤖 Agentic Commerce Demo",
            border_style="blue",
        ))

        try:
            # 1. Discover
            self.discover()

            # 2. Browse
            self.browse_catalog()

            # 3. Search
            self.search(category="smartphones")

            # 4. Create cart
            self.create_cart()

            # 5. Add items
            self.add_item("prod_pixel9", 1)  # Phone
            self.add_item("prod_buds_a", 1)  # Budget earbuds
            self.add_item("prod_cable_usbc", 1)  # Cable

            # 6. View & apply campaign
            self.view_campaigns()
            self.apply_campaign("WELCOME10")

            # 7. Preview
            self.preview_checkout()

            # 8. Confirm
            self.confirm_checkout()

            # 9. Check status
            self.check_status()

            console.print("\n[bold green]✅ Full flow completed successfully![/bold green]")
            console.print("[dim]Open the payment link in a browser to test payment with Razorpay test credentials.[/dim]")

        except httpx.ConnectError:
            console.print(f"\n[red]❌ Cannot connect to {self.base_url}[/red]")
            console.print("[dim]Start the server first: python main.py[/dim]")
        except Exception as e:
            console.print(f"\n[red]❌ Error: {e}[/red]")
            raise


def main():
    parser = argparse.ArgumentParser(description="AI Buyer Agent for Agentic Commerce")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Merchant API base URL")
    parser.add_argument("--budget", type=float, default=200.0, help="Budget in rupees")
    parser.add_argument("--auto", action="store_true", help="Run full automated flow")
    args = parser.parse_args()

    agent = AIBuyerAgent(base_url=args.url, budget_rupees=args.budget)

    if args.auto:
        agent.run_full_flow()
    else:
        # Interactive mode
        console.print("[bold]AI Buyer Agent — Interactive Mode[/bold]")
        console.print("Commands: discover, browse, search <q>, cart, add <id>, campaigns, apply <code>, preview, confirm, status, quit")
        console.print()

        while True:
            try:
                cmd = console.input("[bold cyan]agent> [/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not cmd:
                continue
            parts = cmd.split(maxsplit=1)
            action = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if action == "quit" or action == "exit":
                break
            elif action == "discover":
                agent.discover()
            elif action == "browse":
                agent.browse_catalog()
            elif action == "search":
                agent.search(query=arg)
            elif action == "cart":
                if not agent.cart_id:
                    budget = float(arg) if arg else 200.0
                    agent.create_cart()
                else:
                    result = agent._get(f"/cart/{agent.cart_id}")
                    console.print_json(data=result)
            elif action == "add":
                if not agent.cart_id:
                    agent.create_cart()
                agent.add_item(arg)
            elif action == "remove":
                if agent.cart_id:
                    agent._delete(f"/cart/{agent.cart_id}/items/{arg}")
            elif action == "campaigns":
                agent.view_campaigns()
            elif action == "apply":
                agent.apply_campaign(arg)
            elif action == "preview":
                agent.preview_checkout()
            elif action == "confirm":
                agent.confirm_checkout()
            elif action == "status":
                agent.check_status()
            elif action == "audit":
                result = agent._get("/audit?limit=10")
                for e in result.get("entries", []):
                    console.print(f"  {e['action']} | {e['explanation'][:80]}")
            else:
                console.print(f"[red]Unknown command: {action}[/red]")


if __name__ == "__main__":
    main()
