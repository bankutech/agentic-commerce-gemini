import httpx

base_url = "http://localhost:8000"

def get(path):
    r = httpx.get(f"{base_url}{path}")
    return r.json()

def post(path, json=None):
    r = httpx.post(f"{base_url}{path}", json=json or {})
    return r.json()

# 1. Create a cart with Rs 120,000 budget (12,000,000 paise)
cart = post("/cart", {"agent_id": "manual_script", "max_budget_paise": 12000000})
cart_id = cart.get("cart_id")

# 2. Add Pixel 9 Pro
post(f"/cart/{cart_id}/items", {"product_id": "prod_pixel9pro", "quantity": 1})

# 3. Add 30W Charger
post(f"/cart/{cart_id}/items", {"product_id": "prod_charger_30w", "quantity": 1})

# 4. Apply a campaign
post(f"/cart/{cart_id}/apply-campaign", {"code": "WELCOME10"})

# 5. Confirm checkout
checkout = post(f"/cart/{cart_id}/confirm", {
    "customer_name": "Test User",
    "customer_email": "test@example.com",
    "customer_contact": "+919999999999"
})

print("\n=== Agent Checkout Generated Successfully! ===")
if "payment_link" in checkout:
    print(f"Razorpay Payment Link: {checkout['payment_link']}")
else:
    print(f"Checkout Result: {checkout}")

