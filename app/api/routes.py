"""FastAPI API routes — the agent-facing REST interface.

Endpoints cover:
- Agent discovery & manifest
- Agent-readable catalog (Schema.org JSON-LD)
- Shopping flow (cart → checkout → confirm)
- Campaigns
- Audit trail
- Webhook receiver
- Order status
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field

from app.models.audit import AuditAction, GateResult

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------


class CreateCartRequest(BaseModel):
    agent_id: str = Field(description="Unique identifier for the AI buyer agent")
    max_budget_paise: Optional[int] = Field(
        default=None, description="Maximum spending limit in paise (optional)"
    )


class AddItemRequest(BaseModel):
    product_id: str
    quantity: int = Field(default=1, gt=0)


class ConfirmCheckoutRequest(BaseModel):
    customer_name: str = "AI Buyer Agent"
    customer_email: str = "agent@test.example.com"
    customer_contact: str = "+919999999999"


class ApplyCampaignRequest(BaseModel):
    code: str = Field(description="Campaign/coupon code")


class CreateCampaignRequest(BaseModel):
    code: str
    name: str
    description: str
    discount_type: str = "percentage"
    discount_value: int
    max_discount_paise: int
    min_cart_paise: int = 0
    eligible_categories: list[str] = Field(default_factory=list)
    max_uses: int = 100


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Agent Discovery
# ---------------------------------------------------------------------------


@router.get("/", tags=["discovery"])
async def service_manifest(request: Request):
    """Agent-readable service manifest — capabilities, endpoints, version."""
    base = str(request.base_url).rstrip("/")
    return {
        "@context": "https://schema.org/",
        "@type": "WebAPI",
        "name": "Agentic Commerce Merchant API",
        "description": (
            "AI-transactable merchant storefront. Supports agent-driven discovery, "
            "cart management, checkout, and payment — all audited and bounded."
        ),
        "version": "0.1.0",
        "documentation": f"{base}/docs",
        "capabilities": [
            "agent_readable_catalog",
            "cart_management",
            "spending_bounds",
            "two_phase_checkout",
            "upsell_recommendations",
            "campaign_discounts",
            "audit_trail",
            "razorpay_test_payments",
        ],
        "endpoints": {
            "catalog": f"{base}/catalog",
            "catalog_search": f"{base}/catalog/search",
            "cart": f"{base}/cart",
            "campaigns": f"{base}/campaigns",
            "audit": f"{base}/audit",
            "webhooks": f"{base}/webhooks/razorpay",
        },
        "payment_provider": "Razorpay (Test Mode)",
        "test_credentials": {
            "card": "5104 0600 0000 0008 (any future expiry, any CVV)",
            "upi_success": "success@razorpay",
            "upi_failure": "failure@razorpay",
        },
        "protocol_support": ["REST/JSON", "Schema.org JSON-LD"],
    }


@router.get("/status", tags=["discovery"])
async def get_status(request: Request):
    """Live system status — powers the dashboard's status pills.
    Not agent-facing; a quick human-readable health/config snapshot.
    """
    recommendations = request.app.state.recommendations
    razorpay_client = request.app.state.razorpay_client
    catalog = request.app.state.catalog
    campaign_service = request.app.state.campaign_service

    ai_ranker = getattr(recommendations, "_ai_ranker", None)
    ai_enabled = bool(ai_ranker and ai_ranker.enabled)
    razorpay_configured = bool(razorpay_client.key_id) and "REPLACE_ME" not in razorpay_client.key_id

    return {
        "ai_recommendation_ranking": "ai_ranked" if ai_enabled else "rule_based",
        "razorpay_configured": razorpay_configured,
        "database_path": os.getenv("DATABASE_PATH", "agentic_commerce.db"),
        "products_in_catalog": len(catalog.list_products()),
        "campaigns_active": len(campaign_service.list_active()),
    }


# ---------------------------------------------------------------------------
# Agent-Readable Catalog
# ---------------------------------------------------------------------------


@router.get("/catalog", tags=["catalog"])
async def get_catalog(request: Request):
    """Full product catalog as Schema.org JSON-LD ItemList."""
    catalog_service = request.app.state.catalog
    return catalog_service.get_catalog_jsonld()


@router.get("/catalog/search", tags=["catalog"])
async def search_catalog(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None, description="Filter by category"),
    max_price: Optional[int] = Query(None, description="Max price in paise"),
    min_price: Optional[int] = Query(None, description="Min price in paise"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
):
    """Search products with filters. Returns JSON-LD products."""
    catalog_service = request.app.state.catalog
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = catalog_service.search(
        query=q,
        category=category,
        max_price_paise=max_price,
        min_price_paise=min_price,
        tags=tag_list,
    )
    return {
        "query": q,
        "filters": {"category": category, "max_price": max_price, "min_price": min_price, "tags": tag_list},
        "count": len(results),
        "results": [p.to_jsonld() for p in results],
    }


@router.get("/catalog/{product_id}", tags=["catalog"])
async def get_product(request: Request, product_id: str):
    """Single product as Schema.org JSON-LD."""
    catalog_service = request.app.state.catalog
    jsonld = catalog_service.get_product_jsonld(product_id)
    if not jsonld:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")
    return jsonld


# ---------------------------------------------------------------------------
# Shopping Cart
# ---------------------------------------------------------------------------


@router.post("/cart", tags=["cart"])
async def create_cart(request: Request, body: CreateCartRequest):
    """Create a new shopping cart with optional spending bound."""
    cart_service = request.app.state.cart_service
    cart = cart_service.create_cart(
        agent_id=body.agent_id,
        max_budget_paise=body.max_budget_paise,
    )
    return cart_service.get_cart_view(cart.id)


@router.get("/cart/{cart_id}", tags=["cart"])
async def get_cart(request: Request, cart_id: str):
    """View cart with items, totals, spending bound status, and recommendations."""
    cart_service = request.app.state.cart_service
    view = cart_service.get_cart_view(cart_id)
    if not view:
        raise HTTPException(status_code=404, detail=f"Cart {cart_id} not found.")
    return view


@router.get("/cart/{cart_id}/recommendations", tags=["cart"])
async def get_cart_recommendations(request: Request, cart_id: str):
    """Explicit upsell/cross-sell/bundle recommendations for this cart.

    This is the dedicated 'Upsell Agent' step: the rule engine generates
    candidates from the real catalog, and — when GOOGLE_API_KEY is set —
    Gemini ranks and re-explains them for this specific cart. Response
    always reports which method actually ran via `recommendation_method`.
    """
    cart_service = request.app.state.cart_service
    if cart_id not in cart_service._carts:
        raise HTTPException(status_code=404, detail=f"Cart {cart_id} not found.")
    recs, method = cart_service.get_recommendations(cart_id)
    return {
        "cart_id": cart_id,
        "recommendation_method": method,
        "count": len(recs),
        "recommendations": [r.to_dict() for r in recs],
    }


@router.post("/cart/{cart_id}/items", tags=["cart"])
async def add_item_to_cart(request: Request, cart_id: str, body: AddItemRequest):
    """Add an item to cart. Enforces spending bounds and stock limits."""
    cart_service = request.app.state.cart_service
    cart, explanation = cart_service.add_item(
        cart_id=cart_id,
        product_id=body.product_id,
        quantity=body.quantity,
    )
    if cart is None:
        raise HTTPException(status_code=404, detail=explanation)

    view = cart_service.get_cart_view(cart_id)
    return {
        "message": explanation,
        "cart": view,
    }


@router.delete("/cart/{cart_id}/items/{product_id}", tags=["cart"])
async def remove_item_from_cart(request: Request, cart_id: str, product_id: str):
    """Remove an item from the cart."""
    cart_service = request.app.state.cart_service
    cart, explanation = cart_service.remove_item(cart_id=cart_id, product_id=product_id)
    if cart is None:
        raise HTTPException(status_code=404, detail=explanation)
    view = cart_service.get_cart_view(cart_id)
    return {"message": explanation, "cart": view}


# ---------------------------------------------------------------------------
# Checkout (Two-Phase)
# ---------------------------------------------------------------------------


@router.post("/cart/{cart_id}/checkout", tags=["checkout"])
async def preview_checkout(request: Request, cart_id: str):
    """Phase 1: Preview checkout — shows breakdown, recommendations, and requires confirmation."""
    checkout_service = request.app.state.checkout_service
    preview, explanation = checkout_service.preview_checkout(cart_id)
    if preview is None:
        raise HTTPException(status_code=400, detail=explanation)
    return preview


@router.post("/cart/{cart_id}/confirm", tags=["checkout"])
async def confirm_checkout(request: Request, cart_id: str, body: ConfirmCheckoutRequest):
    """Phase 2: Confirm checkout — creates Razorpay order + payment link.
    No money moves without this explicit confirmation.
    """
    checkout_service = request.app.state.checkout_service
    result, explanation = checkout_service.confirm_checkout(
        cart_id=cart_id,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        customer_contact=body.customer_contact,
    )
    if result is None:
        raise HTTPException(status_code=400, detail=explanation)
    return result


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@router.get("/campaigns", tags=["campaigns"])
async def list_campaigns(request: Request):
    """List active promotional campaigns."""
    campaign_service = request.app.state.campaign_service
    campaigns = campaign_service.list_active()
    return {
        "count": len(campaigns),
        "campaigns": [
            {
                "code": c.code,
                "name": c.name,
                "description": c.description,
                "discount_type": c.discount_type.value,
                "discount_value": c.discount_value,
                "max_discount_display": f"₹{c.max_discount_paise / 100:.2f}",
                "min_cart_display": f"₹{c.min_cart_paise / 100:.2f}",
                "eligible_categories": c.eligible_categories or ["all"],
                "uses_remaining": c.max_uses - c.current_uses,
            }
            for c in campaigns
        ],
    }


@router.post("/campaigns", tags=["campaigns"])
async def create_campaign(request: Request, body: CreateCampaignRequest):
    """Create a new promotional campaign (merchant action)."""
    from app.models.campaign import Campaign, DiscountType

    campaign_service = request.app.state.campaign_service
    campaign = Campaign(
        code=body.code,
        name=body.name,
        description=body.description,
        discount_type=DiscountType(body.discount_type),
        discount_value=body.discount_value,
        max_discount_paise=body.max_discount_paise,
        min_cart_paise=body.min_cart_paise,
        eligible_categories=body.eligible_categories,
        max_uses=body.max_uses,
    )
    created = campaign_service.create_campaign(campaign)
    return {"message": f"Campaign '{created.code}' created.", "campaign_id": created.id}


@router.post("/cart/{cart_id}/apply-campaign", tags=["campaigns"])
async def apply_campaign_to_cart(request: Request, cart_id: str, body: ApplyCampaignRequest):
    """Apply a campaign/coupon code to a cart."""
    cart_service = request.app.state.cart_service
    campaign_service = request.app.state.campaign_service
    audit = request.app.state.audit

    cart = cart_service.get_cart(cart_id)
    if not cart:
        raise HTTPException(status_code=404, detail=f"Cart {cart_id} not found.")

    if not cart.items:
        raise HTTPException(status_code=400, detail="Cart is empty. Add items first.")

    # Determine eligible amount (if category-specific)
    campaign = campaign_service.get_campaign(body.code)
    if campaign and campaign.eligible_categories:
        catalog = request.app.state.catalog
        eligible_paise = 0
        for item in cart.items:
            product = catalog.get_product(item.product_id)
            if product and product.category in campaign.eligible_categories:
                eligible_paise += item.total_paise
    else:
        eligible_paise = cart.subtotal_paise

    discount, explanation, success = campaign_service.apply_campaign(
        code=body.code,
        cart_subtotal_paise=cart.subtotal_paise,
        eligible_amount_paise=eligible_paise,
    )

    if success:
        cart.discount_paise = discount
        cart.campaign_code = body.code
        cart_service.persist(cart)
        audit.log_action(
            action=AuditAction.CAMPAIGN_APPLIED,
            actor=cart.agent_id,
            explanation=f"Campaign '{body.code}' applied: {explanation}",
            amount_paise=discount,
            cart_id=cart_id,
            gate_check=GateResult.PASSED,
            gate_details=explanation,
        )
    else:
        audit.log_action(
            action=AuditAction.CAMPAIGN_REJECTED,
            actor=cart.agent_id,
            explanation=f"Campaign '{body.code}' rejected: {explanation}",
            cart_id=cart_id,
            gate_check=GateResult.REJECTED,
            gate_details=explanation,
        )

    view = cart_service.get_cart_view(cart_id)
    return {
        "success": success,
        "message": explanation,
        "discount_applied_paise": discount if success else 0,
        "cart": view,
    }


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------


@router.get("/audit", tags=["audit"])
async def get_recent_audit(
    request: Request,
    limit: int = Query(default=50, le=200, description="Max entries to return"),
):
    """Recent audit trail entries."""
    audit = request.app.state.audit
    entries = audit.get_recent(limit)
    return {
        "count": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


@router.get("/audit/failures", tags=["audit"])
async def get_audit_failures(request: Request):
    """Recent failure/rejection entries."""
    audit = request.app.state.audit
    entries = audit.get_failures()
    return {
        "count": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


@router.get("/audit/{order_id}", tags=["audit"])
async def get_order_audit(request: Request, order_id: str):
    """Full audit trail for a specific order."""
    audit = request.app.state.audit
    entries = audit.get_trail(order_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"No audit entries for order {order_id}.")
    return {
        "order_id": order_id,
        "count": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


# ---------------------------------------------------------------------------
# Revenue Metrics — computed live from the audit trail. Every number here
# is traceable to a specific AuditEntry; nothing is estimated or fabricated.
# ---------------------------------------------------------------------------


@router.get("/metrics/revenue", tags=["metrics"])
async def get_revenue_metrics(request: Request):
    """Revenue and growth metrics, computed directly from the audit log.

    This is the evidence for 'grow the merchant's revenue': confirmed GMV,
    discount cost, the AI-ranked vs rule-based split for recommendations,
    and every gated rejection — all derived from real AuditEntry records,
    not simulated or hardcoded.
    """
    audit = request.app.state.audit
    metrics = audit.get_metrics()

    total_gmv_paise = metrics["total_gmv_paise"]
    orders_confirmed = metrics["orders_confirmed"]
    total_discount_paise = metrics["total_discount_paise"]
    campaigns_applied = metrics["campaigns_applied"]
    ai_ranked_events = metrics["ai_ranked_events"]
    rule_based_events = metrics["rule_based_events"]
    spending_bound_rejections = metrics["spending_bound_rejections"]
    campaign_rejections = metrics["campaign_rejections"]
    payment_failures = metrics["payment_failures"]
    razorpay_errors = metrics["razorpay_errors"]

    net_revenue_paise = total_gmv_paise  # order.total_paise is already post-discount
    avg_order_paise = (total_gmv_paise // orders_confirmed) if orders_confirmed else 0

    def inr(paise: int) -> str:
        return f"₹{paise / 100:,.2f}"

    return {
        "summary": {
            "orders_confirmed": orders_confirmed,
            "total_gmv_paise": total_gmv_paise,
            "total_gmv_display": inr(total_gmv_paise),
            "average_order_value_paise": avg_order_paise,
            "average_order_value_display": inr(avg_order_paise),
        },
        "discounts": {
            "campaigns_applied": campaigns_applied,
            "campaigns_rejected": campaign_rejections,
            "total_discount_given_paise": total_discount_paise,
            "total_discount_given_display": inr(total_discount_paise),
        },
        "recommendation_engine": {
            "ai_ranked_events": ai_ranked_events,
            "rule_based_events": rule_based_events,
            "note": (
                "ai_ranked means Gemini ranked/explained the rule engine's candidates; "
                "rule_based means the deterministic fallback ran (no API key, SDK missing, "
                "or the AI call failed and degraded safely)."
            ),
        },
        "gated_rejections": {
            "spending_bound_exceeded": spending_bound_rejections,
            "payment_failures": payment_failures,
            "razorpay_errors": razorpay_errors,
        },
        "note": (
            "Every figure above is aggregated live from the audit trail (GET /audit) — "
            "each is traceable back to the specific AuditEntry that produced it."
        ),
    }


# ---------------------------------------------------------------------------
# Order Status
# ---------------------------------------------------------------------------


@router.get("/orders/{order_id}/status", tags=["orders"])
async def get_order_status(request: Request, order_id: str):
    """Check order + payment status (polls Razorpay if needed)."""
    checkout_service = request.app.state.checkout_service
    status = checkout_service.get_order_status(order_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found.")
    return status


# ---------------------------------------------------------------------------
# Razorpay Webhook
# ---------------------------------------------------------------------------


@router.post("/webhooks/razorpay", tags=["webhooks"])
async def razorpay_webhook(request: Request):
    """Receive and process Razorpay webhook events.
    Verifies signature, handles known events, ignores unknowns gracefully.
    """
    audit = request.app.state.audit
    rz_client = request.app.state.razorpay_client
    webhook_handler = request.app.state.webhook_handler
    checkout_service = request.app.state.checkout_service

    # Get raw body for signature verification
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8")
    signature = request.headers.get("x-razorpay-signature", "")
    event_id = request.headers.get("x-razorpay-event-id", "")

    # Check idempotency
    if event_id and webhook_handler.is_duplicate(event_id):
        logger.info("Duplicate webhook event ignored: %s", event_id)
        return {"status": "duplicate_ignored"}

    # Verify signature
    if signature:
        valid, sig_explanation = rz_client.verify_webhook_signature(body_str, signature)
        if not valid:
            audit.log_action(
                action=AuditAction.WEBHOOK_SIGNATURE_INVALID,
                actor="razorpay_webhook",
                explanation=f"SECURITY: {sig_explanation} Event ID: {event_id}.",
                gate_check=GateResult.REJECTED,
                gate_details=sig_explanation,
            )
            raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    # Parse event
    event, parse_error = webhook_handler.parse_event(body_str)
    if not event:
        logger.warning("Failed to parse webhook: %s", parse_error)
        return {"status": "parse_error", "detail": parse_error}

    # Process event → audit entries
    audit_entries = webhook_handler.process_event(event)
    for entry in audit_entries:
        audit.log(entry)

    # Update order status if payment event
    payment = event.payment_entity
    if payment:
        rz_order_id = payment.get("order_id", "")
        payment_id = payment.get("id", "")
        status = payment.get("status", "")
        if rz_order_id:
            checkout_service.handle_payment_update(rz_order_id, payment_id, status)

    return {"status": "processed", "event": event.event_type}
