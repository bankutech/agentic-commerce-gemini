"""Catalog and discovery — agent-readable storefront."""


def test_discovery_root_returns_valid_jsonld(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["@type"] == "WebAPI"


def test_catalog_returns_schema_org_itemlist(client):
    resp = client.get("/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert data["@type"] == "ItemList"
    assert data["numberOfItems"] >= 10  # 12 seeded products
    assert len(data["itemListElement"]) == data["numberOfItems"]
    first_item = data["itemListElement"][0]["item"]
    assert first_item["@type"] == "Product"


def test_single_product_lookup(client):
    resp = client.get("/catalog/prod_pixel9")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Google Pixel 9"


def test_unknown_product_returns_404(client):
    resp = client.get("/catalog/does_not_exist")
    assert resp.status_code == 404


def test_search_by_category(client):
    resp = client.get("/catalog/search", params={"category": "audio"})
    assert resp.status_code == 200
