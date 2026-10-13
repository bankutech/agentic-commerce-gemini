"""Campaign discounts — bounded, capped, and explainable."""


def test_list_campaigns_includes_all_seeded_codes(client):
    resp = client.get("/campaigns")
    assert resp.status_code == 200
    codes = {c["code"] for c in resp.json()["campaigns"]}
    # WELCOME10, FLAT200, BUNDLE10, AUDIO15, BUNDLE500 must all exist —
    # BUNDLE500 was referenced by the recommendation engine's bundle hint
    # but was missing from the seed data; this asserts that fix holds.
    assert {"WELCOME10", "FLAT200", "BUNDLE10", "AUDIO15", "BUNDLE500"}.issubset(codes)


def test_apply_valid_campaign_reduces_total(client, new_cart):
    client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_pixel9", "quantity": 1})
    before = client.get(f"/cart/{new_cart}").json()["total_paise"]

    resp = client.post(f"/cart/{new_cart}/apply-campaign", json={"code": "WELCOME10"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    after = client.get(f"/cart/{new_cart}").json()["total_paise"]
    assert after < before


def test_bundle500_campaign_applies_successfully(client, new_cart):
    """Regression test: BUNDLE500 was referenced by the recommendation
    engine's bundle hint but was never seeded as a real campaign, so
    redeeming it always failed. Confirms the fix."""
    client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_buds_a", "quantity": 1})
    resp = client.post(f"/cart/{new_cart}/apply-campaign", json={"code": "BUNDLE500"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_invalid_campaign_code_is_rejected(client, new_cart):
    client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_pixel9", "quantity": 1})
    resp = client.post(f"/cart/{new_cart}/apply-campaign", json={"code": "NOT_A_REAL_CODE"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_campaign_usage_count_decrements(client):
    resp = client.get("/campaigns")
    before = next(c for c in resp.json()["campaigns"] if c["code"] == "FLAT200")["uses_remaining"]

    resp = client.post("/cart", json={"agent_id": "usage_test", "max_budget_paise": 10_000_000})
    cart_id = resp.json()["cart_id"]
    client.post(f"/cart/{cart_id}/items", json={"product_id": "prod_pixel9", "quantity": 1})
    client.post(f"/cart/{cart_id}/apply-campaign", json={"code": "FLAT200"})

    resp = client.get("/campaigns")
    after = next(c for c in resp.json()["campaigns"] if c["code"] == "FLAT200")["uses_remaining"]
    assert after == before - 1
