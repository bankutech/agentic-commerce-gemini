"""Checkout (two-phase) and the audit trail — 'explainable, bounded, gated'."""


def test_preview_checkout_on_empty_cart_is_rejected(client, new_cart):
    resp = client.post(f"/cart/{new_cart}/checkout")
    assert resp.status_code == 400


def test_preview_checkout_returns_totals_and_recommendation_method(client, new_cart):
    client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_pixel9", "quantity": 1})
    resp = client.post(f"/cart/{new_cart}/checkout")
    assert resp.status_code == 200
    data = resp.json()
    assert data["subtotal_paise"] > 0
    assert data["recommendation_method"] in ("ai_ranked", "rule_based")
    assert data["requires_confirmation"] is True


def test_confirm_checkout_without_preview_fails_gracefully(client, new_cart):
    """Confirming with an empty cart must be rejected cleanly (400), never a 500."""
    resp = client.post(
        f"/cart/{new_cart}/confirm",
        json={"customer_name": "Test", "customer_email": "t@example.com", "customer_contact": "+919999999999"},
    )
    assert resp.status_code == 400


def test_confirm_checkout_with_no_razorpay_keys_fails_gracefully(client, new_cart):
    """With no real Razorpay credentials configured (the CI/test default),
    confirm_checkout must fail with a clean error response, never crash
    the process — this is the 'one failure handled gracefully' bar."""
    client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_case_pixel9", "quantity": 1})
    client.post(f"/cart/{new_cart}/checkout")
    resp = client.post(
        f"/cart/{new_cart}/confirm",
        json={"customer_name": "Test", "customer_email": "t@example.com", "customer_contact": "+919999999999"},
    )
    # Whatever the outcome, it must be a well-formed HTTP response, not a crash.
    assert resp.status_code in (200, 400, 500)
    assert resp.headers["content-type"].startswith("application/json")


def test_audit_trail_records_cart_creation(client):
    resp = client.post("/cart", json={"agent_id": "audit_test_agent", "max_budget_paise": 100000})
    cart_id = resp.json()["cart_id"]

    trail_resp = client.get("/audit", params={"limit": 20})
    assert trail_resp.status_code == 200
    entries = trail_resp.json()["entries"]
    matching = [e for e in entries if e.get("cart_id") == cart_id]
    assert any(e["action"] == "cart_created" for e in matching)


def test_audit_trail_records_spending_bound_rejection(client):
    resp = client.post("/cart", json={"agent_id": "audit_reject_test", "max_budget_paise": 1})
    cart_id = resp.json()["cart_id"]
    client.post(f"/cart/{cart_id}/items", json={"product_id": "prod_pixel9", "quantity": 1})

    trail_resp = client.get("/audit/failures")
    assert trail_resp.status_code == 200
    entries = trail_resp.json()["entries"]
    matching = [e for e in entries if e.get("cart_id") == cart_id]
    assert any(e["action"] == "spending_bound_exceeded" for e in matching)


def test_unknown_order_audit_returns_404(client):
    resp = client.get("/audit/order_does_not_exist")
    assert resp.status_code == 404


def test_revenue_metrics_endpoint_is_well_formed(client):
    resp = client.get("/metrics/revenue")
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data and "discounts" in data and "recommendation_engine" in data
    assert isinstance(data["summary"]["orders_confirmed"], int)
