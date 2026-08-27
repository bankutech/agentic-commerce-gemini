"""Demo scenarios — pre-built flows to showcase agentic commerce capabilities.

Each scenario demonstrates a specific aspect of the system:
1. Happy path: Browse → Add → Checkout → Pay
2. Upsell accepted: Agent accepts cross-sell recommendation
3. Budget exceeded: Cart exceeds spending bound → graceful rejection
4. Campaign applied: Discount code + bounded discount
5. Payment failure: Simulated failed payment → audit trail shows recovery

Usage:
    python -m agent.demo_scenarios                          # Run all
    python -m agent.demo_scenarios --scenario happy_path    # Run specific
    python -m agent.demo_scenarios --list                   # List scenarios
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx
from rich.console import Console
from rich.panel import Panel
from rich import box

import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

console = Console(force_terminal=True)

BASE_URL = "http://localhost:8000"


def _get(path: str) -> dict:
    r = httpx.get(f"{BASE_URL}{path}", timeout=30)
    return r.json()


def _post(path: str, json: dict | None = None) -> dict:
    r = httpx.post(f"{BASE_URL}{path}", json=json or {}, timeout=30)
    return r.json()


def _delete(path: str) -> dict:
    r = httpx.delete(f"{BASE_URL}{path}", timeout=30)
    return r.json()


# ===================================================================
# Scenario 1: Happy Path
# ===================================================================

def scenario_happy_path():
    """Complete purchase flow — browse, add, checkout, confirm."""
    console.print(Panel(
        "[bold]Scenario: Happy Path[/bold]\n"
        "An AI agent discovers the store, adds a phone and cable, "
        "applies a discount, and completes checkout.",
        title="🎯 Scenario 1",
        border_style="green",
    ))

    # Discover
    manifest = _get("/")
    console.print(f"✅ Discovered: {manifest['name']}")

    # Browse catalog
    catalog = _get("/catalog")
    console.print(f"✅ Catalog loaded: {catalog['numberOfItems']} products")

    # Create cart with ₹15,000 budget
    cart = _post("/cart", {"agent_id": "demo_happy_path", "max_budget_paise": 1500000})
    cart_id = cart["cart_id"]
    console.print(f"✅ Cart created: {cart_id} (budget: ₹15,000)")

    # Add Pixel 9 + cable
    r = _post(f"/cart/{cart_id}/items", {"product_id": "prod_pixel9", "quantity": 1})
    console.print(f"✅ {r.get('message', 'Added item')}")

    r = _post(f"/cart/{cart_id}/items", {"product_id": "prod_cable_usbc", "quantity": 1})
    console.print(f"✅ {r.get('message', 'Added item')}")

    # Apply campaign
    r = _post(f"/cart/{cart_id}/apply-campaign", {"code": "WELCOME10"})
    console.print(f"✅ Campaign: {r.get('message', '')}")

    # Preview checkout
    preview = _post(f"/cart/{cart_id}/checkout")
    console.print(f"✅ Preview: {preview.get('total_display', '?')} ({len(preview.get('items', []))} items)")

    # Confirm
    result = _post(f"/cart/{cart_id}/confirm", {
        "customer_name": "Happy Path Agent",
        "customer_email": "happy@test.example.com",
    })

    if "payment_link_url" in result:
        console.print(f"✅ Order confirmed: {result['order_id']}")
        console.print(f"   Payment link: {result['payment_link_url']}")
        console.print(f"   Audit trail: {len(result.get('audit_trail', []))} entries")
        return True
    else:
        console.print(f"⛔ Failed: {result}")
        return False


# ===================================================================
# Scenario 2: Upsell Accepted
# ===================================================================

def scenario_upsell_accepted():
    """Agent adds budget earbuds, sees upsell to Pro, and accepts."""
    console.print(Panel(
        "[bold]Scenario: Upsell Accepted[/bold]\n"
        "Agent adds Pixel Buds A-Series, receives upsell to Buds Pro 2, "
        "removes the budget option and adds the premium one.",
        title="🎯 Scenario 2",
        border_style="yellow",
    ))

    cart = _post("/cart", {"agent_id": "demo_upsell", "max_budget_paise": 5000000})
    cart_id = cart["cart_id"]
    console.print(f"✅ Cart created: {cart_id} (budget: ₹50,000)")

    # Add budget earbuds
    r = _post(f"/cart/{cart_id}/items", {"product_id": "prod_buds_a", "quantity": 1})
    console.print(f"✅ Added Pixel Buds A-Series")

    # Check recommendations
    cart_view = _get(f"/cart/{cart_id}")
    recs = cart_view.get("recommendations", [])
    upsell = next((r for r in recs if r["type"] == "upsell"), None)

    if upsell:
        console.print(f"💡 Upsell detected: {upsell['product_name']} — {upsell['reason']}")

        # Accept upsell: remove budget, add premium
        _delete(f"/cart/{cart_id}/items/prod_buds_a")
        console.print("✅ Removed Pixel Buds A-Series")

        r = _post(f"/cart/{cart_id}/items", {"product_id": upsell["product_id"], "quantity": 1})
        console.print(f"✅ Added {upsell['product_name']} (upsell accepted)")
    else:
        console.print("ℹ️  No upsell recommendation found")

    # Add a phone too
    r = _post(f"/cart/{cart_id}/items", {"product_id": "prod_pixel9pro", "quantity": 1})
    console.print(f"✅ {r.get('message', 'Added Pixel 9 Pro')}")

    # Checkout
    result = _post(f"/cart/{cart_id}/confirm", {
        "customer_name": "Upsell Agent",
        "customer_email": "upsell@test.example.com",
    })

    if "payment_link_url" in result:
        console.print(f"✅ Order confirmed: {result['order_id']} ({result['total_display']})")
        console.print(f"   Payment link: {result['payment_link_url']}")
        return True
    else:
        console.print(f"⛔ Checkout failed: {result}")
        return False


# ===================================================================
# Scenario 3: Budget Exceeded (Graceful Failure)
# ===================================================================

def scenario_budget_exceeded():
    """Agent tries to exceed spending bound — system rejects gracefully."""
    console.print(Panel(
        "[bold]Scenario: Budget Exceeded[/bold]\n"
        "Agent has a ₹5,000 budget but tries to add a ₹79,999 phone. "
        "System rejects with clear explanation and the agent recovers.",
        title="🎯 Scenario 3",
        border_style="red",
    ))

    cart = _post("/cart", {"agent_id": "demo_budget", "max_budget_paise": 500000})
    cart_id = cart["cart_id"]
    console.print(f"✅ Cart created: {cart_id} (budget: ₹5,000)")

    # Try to add expensive phone
    r = _post(f"/cart/{cart_id}/items", {"product_id": "prod_pixel9", "quantity": 1})
    msg = r.get("message", "")
    if "REJECTED" in msg or "exceeds" in msg.lower():
        console.print(f"⛔ EXPECTED REJECTION: {msg}")
        console.print("   ✅ System correctly enforced spending bound!")
    else:
        console.print(f"✅ {msg}")

    # Agent recovers: add something within budget
    r = _post(f"/cart/{cart_id}/items", {"product_id": "prod_cable_usbc", "quantity": 1})
    console.print(f"✅ Recovery: {r.get('message', 'Added affordable item')}")

    r = _post(f"/cart/{cart_id}/items", {"product_id": "prod_screen_protector", "quantity": 1})
    console.print(f"✅ Recovery: {r.get('message', 'Added another item')}")

    # Show audit trail showing the rejection
    audit = _get("/audit?limit=10")
    rejections = [e for e in audit.get("entries", []) if e.get("gate_check") == "rejected"]
    console.print(f"\n📝 Audit shows {len(rejections)} rejection(s):")
    for e in rejections[:3]:
        console.print(f"   ⛔ {e['action']}: {e['explanation'][:80]}")

    # Checkout the affordable items
    result = _post(f"/cart/{cart_id}/confirm", {
        "customer_name": "Budget Agent",
        "customer_email": "budget@test.example.com",
    })

    if "payment_link_url" in result:
        console.print(f"\n✅ Recovered order: {result['order_id']} ({result['total_display']})")
        return True
    return False


# ===================================================================
# Scenario 4: Campaign Applied
# ===================================================================

def scenario_campaign_applied():
    """Agent applies a valid campaign and one that fails — shows both paths."""
    console.print(Panel(
        "[bold]Scenario: Campaign Discounts[/bold]\n"
        "Agent applies AUDIO15 (15% off audio) to earbuds, "
        "then tries an invalid code. Shows bounded discount logic.",
        title="🎯 Scenario 4",
        border_style="magenta",
    ))

    cart = _post("/cart", {"agent_id": "demo_campaign", "max_budget_paise": 5000000})
    cart_id = cart["cart_id"]
    console.print(f"✅ Cart created: {cart_id}")

    # View available campaigns
    campaigns = _get("/campaigns")
    console.print(f"📋 {campaigns.get('count', 0)} active campaigns:")
    for c in campaigns.get("campaigns", []):
        console.print(f"   🏷️  {c['code']}: {c['description']}")

    # Add audio product
    _post(f"/cart/{cart_id}/items", {"product_id": "prod_buds_pro", "quantity": 1})
    console.print("✅ Added Pixel Buds Pro 2")

    # Apply valid campaign
    r = _post(f"/cart/{cart_id}/apply-campaign", {"code": "AUDIO15"})
    console.print(f"{'✅' if r.get('success') else '⛔'} Campaign AUDIO15: {r.get('message', '')}")

    # Try invalid campaign
    r = _post(f"/cart/{cart_id}/apply-campaign", {"code": "FAKE_CODE_999"})
    console.print(f"{'✅' if r.get('success') else '⛔'} Campaign FAKE_CODE_999: {r.get('message', '')}")

    # Cart view shows discount
    view = _get(f"/cart/{cart_id}")
    console.print(f"\n   Subtotal: ₹{view.get('subtotal_paise', 0) / 100:,.2f}")
    console.print(f"   Discount: {view.get('discount_display', '₹0')}")
    console.print(f"   Total: {view.get('total_display', '?')}")

    return True


# ===================================================================
# Scenario 5: Payment Failure Handling
# ===================================================================

def scenario_payment_failure():
    """Shows how the system handles and logs payment-related errors."""
    console.print(Panel(
        "[bold]Scenario: Payment Failure Handling[/bold]\n"
        "Agent completes checkout. The audit trail shows every step, "
        "and the order status endpoint demonstrates polling for updates.",
        title="🎯 Scenario 5",
        border_style="red",
    ))

    # Create cart and checkout
    cart = _post("/cart", {"agent_id": "demo_failure", "max_budget_paise": 5000000})
    cart_id = cart["cart_id"]
    _post(f"/cart/{cart_id}/items", {"product_id": "prod_screen_protector", "quantity": 2})
    console.print("✅ Cart created with 2x screen protectors")

    result = _post(f"/cart/{cart_id}/confirm", {
        "customer_name": "Failure Demo Agent",
        "customer_email": "failure@test.example.com",
    })

    if "order_id" not in result:
        console.print(f"⛔ Checkout failed (possibly no Razorpay keys): {result}")
        console.print("   This is EXPECTED if Razorpay keys are not configured.")
        console.print("   The audit trail captures this failure gracefully.")

        # Show audit trail with the failure
        audit = _get("/audit?limit=10")
        failures = [e for e in audit.get("entries", []) if "FAIL" in e.get("action", "").upper() or "ERROR" in e.get("action", "").upper()]
        if failures:
            console.print(f"\n📝 Failure audit entries ({len(failures)}):")
            for e in failures:
                console.print(f"   ⛔ {e['action']}: {e['explanation'][:100]}")
        return True

    order_id = result["order_id"]
    console.print(f"✅ Order created: {order_id}")
    console.print(f"   Payment link: {result.get('payment_link_url', 'N/A')}")
    console.print(f"   Status: {result.get('status', 'unknown')}")

    # Poll for status (will show 'created' since no payment made)
    console.print("\n⏳ Polling order status (payment not yet made)...")
    status = _get(f"/orders/{order_id}/status")
    console.print(f"   Status: {status.get('status', 'unknown')}")
    console.print(f"   Audit trail entries: {len(status.get('audit_trail', []))}")

    console.print("\n💡 To simulate payment failure: open the payment link and use UPI ID 'failure@razorpay'")
    console.print("💡 To simulate payment success: use UPI ID 'success@razorpay'")

    return True


# ===================================================================
# Runner
# ===================================================================

SCENARIOS = {
    "happy_path": ("Happy Path — Full Purchase Flow", scenario_happy_path),
    "upsell_accepted": ("Upsell Accepted — Cross-sell Recommendation", scenario_upsell_accepted),
    "budget_exceeded": ("Budget Exceeded — Graceful Rejection", scenario_budget_exceeded),
    "campaign_applied": ("Campaign Applied — Bounded Discounts", scenario_campaign_applied),
    "payment_failure": ("Payment Failure — Error Handling", scenario_payment_failure),
}


def run_all():
    console.print(Panel(
        "[bold]Agentic Commerce — Demo Scenario Suite[/bold]\n"
        f"Server: {BASE_URL}\n"
        f"Scenarios: {len(SCENARIOS)}",
        title="🎪 Demo Suite",
        border_style="blue",
    ))

    results = {}
    for name, (desc, fn) in SCENARIOS.items():
        console.print(f"\n{'═' * 60}")
        try:
            success = fn()
            results[name] = "✅ PASS" if success else "⛔ FAIL"
        except httpx.ConnectError:
            console.print(f"[red]❌ Cannot connect to {BASE_URL}. Start the server first.[/red]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")
            results[name] = f"❌ ERROR: {e}"

    # Summary
    console.print(f"\n{'═' * 60}")
    console.print("[bold]Results Summary:[/bold]")
    for name, result in results.items():
        desc = SCENARIOS[name][0]
        console.print(f"  {result} {desc}")


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="Agentic Commerce Demo Scenarios")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), help="Run specific scenario")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()

    BASE_URL = args.url

    if args.list:
        console.print("[bold]Available Scenarios:[/bold]")
        for name, (desc, _) in SCENARIOS.items():
            console.print(f"  {name}: {desc}")
        return

    if args.scenario:
        desc, fn = SCENARIOS[args.scenario]
        console.print(f"\nRunning: {desc}")
        try:
            fn()
        except httpx.ConnectError:
            console.print(f"[red]❌ Cannot connect to {BASE_URL}. Start the server first.[/red]")
    else:
        run_all()


if __name__ == "__main__":
    main()
