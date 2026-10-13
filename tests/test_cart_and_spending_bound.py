"""Cart lifecycle and spending bound enforcement — the core 'bounded' gate."""


def test_create_cart_with_budget(client):
    resp = client.post("/cart", json={"agent_id": "test_agent", "max_budget_paise": 500000})
    assert resp.status_code == 200
    data = resp.json()
    assert "cart_id" in data


def test_add_item_within_budget_succeeds(client, new_cart):
    resp = client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_case_pixel9", "quantity": 1})
    assert resp.status_code == 200
    cart = resp.json()["cart"]
    assert len(cart["items"]) == 1
    assert cart["items"][0]["product_id"] == "prod_case_pixel9"


def test_add_item_over_budget_is_rejected(client):
    # Small budget: cheapest product still exceeds it
    resp = client.post("/cart", json={"agent_id": "budget_test", "max_budget_paise": 100})
    cart_id = resp.json()["cart_id"]

    resp = client.post(f"/cart/{cart_id}/items", json={"product_id": "prod_pixel9", "quantity": 1})
    assert resp.status_code == 200  # request succeeds; the ADD is what's gated
    body = resp.json()
    assert "budget" in body["message"].lower() or "exceed" in body["message"].lower()

    cart_view = client.get(f"/cart/{cart_id}").json()
    assert len(cart_view["items"]) == 0, "item must NOT be added when it exceeds the spending bound"


def test_add_item_exceeding_stock_is_rejected(client, new_cart):
    resp = client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_pixel9", "quantity": 99999})
    assert resp.status_code == 200
    body = resp.json()
    assert "stock" in body["message"].lower() or "available" in body["message"].lower()
    cart_view = client.get(f"/cart/{new_cart}").json()
    assert len(cart_view["items"]) == 0


def test_remove_item_from_cart(client, new_cart):
    client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_case_pixel9", "quantity": 1})
    resp = client.delete(f"/cart/{new_cart}/items/prod_case_pixel9")
    assert resp.status_code == 200
    cart_view = client.get(f"/cart/{new_cart}").json()
    assert len(cart_view["items"]) == 0


def test_unknown_cart_returns_404(client):
    resp = client.get("/cart/cart_does_not_exist")
    assert resp.status_code == 404


def test_cart_recommendations_endpoint(client, new_cart):
    client.post(f"/cart/{new_cart}/items", json={"product_id": "prod_pixel9", "quantity": 1})
    resp = client.get(f"/cart/{new_cart}/recommendations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommendation_method"] in ("ai_ranked", "rule_based")
    assert isinstance(data["recommendations"], list)
