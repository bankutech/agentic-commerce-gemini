"""Agentic Commerce Platform — FastAPI Application Entry Point.

Wires up all services and starts the server.
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agentic_commerce")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agentic Commerce Merchant API",
        description=(
            "AI-transactable merchant storefront on Razorpay Test Mode. "
            "Supports agent-driven catalog discovery, cart management, "
            "two-phase checkout, upsell/cross-sell, campaign discounts, "
            "and complete audit trails."
        ),
        version="0.1.0",
    )

    # CORS — allow all origins for agent access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Initialize services
    # ------------------------------------------------------------------
    from app.razorpay_client.client import MerchantRazorpayClient
    from app.razorpay_client.webhook_handler import WebhookHandler
    from app.catalog.catalog_service import CatalogService
    from app.recommendations.engine import RecommendationEngine
    from app.audit.audit_service import AuditService
    from app.checkout.cart_service import CartService
    from app.checkout.checkout_service import CheckoutService
    from app.campaigns.campaign_service import CampaignService

    # Core services
    razorpay_client = MerchantRazorpayClient()
    audit = AuditService()
    catalog = CatalogService()
    campaign_service = CampaignService()
    webhook_handler = WebhookHandler()

    # Seed data
    catalog.seed()
    campaign_service.seed_defaults()

    # Dependent services
    recommendations = RecommendationEngine(catalog._products)
    cart_service = CartService(catalog, audit, recommendations)
    checkout_service = CheckoutService(
        cart_service, catalog, campaign_service, razorpay_client, audit
    )

    # Attach to app state for access in routes
    app.state.razorpay_client = razorpay_client
    app.state.audit = audit
    app.state.catalog = catalog
    app.state.campaign_service = campaign_service
    app.state.webhook_handler = webhook_handler
    app.state.recommendations = recommendations
    app.state.cart_service = cart_service
    app.state.checkout_service = checkout_service

    # ------------------------------------------------------------------
    # Register routes
    # ------------------------------------------------------------------
    from app.api.routes import router

    app.include_router(router)

    # ------------------------------------------------------------------
    # Startup event — sync catalog to Razorpay
    # ------------------------------------------------------------------
    @app.on_event("startup")
    async def on_startup():
        logger.info("=" * 60)
        logger.info("  Agentic Commerce Platform — Starting")
        logger.info("=" * 60)
        logger.info("Catalog: %d products loaded", len(catalog.list_products()))
        logger.info("Campaigns: %d active", len(campaign_service.list_active()))

        # Attempt to sync items to Razorpay (non-blocking, logs errors)
        if razorpay_client.key_id and "REPLACE_ME" not in razorpay_client.key_id:
            logger.info("Syncing catalog to Razorpay Items API...")
            synced = 0
            for product in catalog.list_products():
                if not product.razorpay_item_id:
                    result = razorpay_client.create_item(
                        name=product.name,
                        amount_paise=product.price_paise,
                        currency=product.currency,
                        description=product.description[:250],
                    )
                    if result.success:
                        catalog.set_razorpay_item_id(
                            product.id, result.data.get("id", "")
                        )
                        synced += 1
                        from app.models.audit import AuditAction
                        audit.log_action(
                            action=AuditAction.ITEM_SYNCED,
                            actor="system",
                            explanation=f"Product '{product.name}' synced to Razorpay as item {result.data.get('id')}.",
                        )
                    else:
                        logger.warning(
                            "Failed to sync '%s': %s", product.name, result.error
                        )
            logger.info("Synced %d/%d products to Razorpay.", synced, len(catalog.list_products()))
        else:
            logger.warning(
                "Razorpay keys not configured — skipping catalog sync. "
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env"
            )

        logger.info("Server ready at http://%s:%s", host, port)
        logger.info("API docs at http://%s:%s/docs", host, port)
        logger.info("=" * 60)

    return app


# Server configuration
host = os.getenv("SERVER_HOST", "0.0.0.0")
port = int(os.getenv("SERVER_PORT", "8000"))

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )
