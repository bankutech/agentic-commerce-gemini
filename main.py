"""Agentic Commerce Platform — FastAPI Application Entry Point.

Wires up all services and starts the server.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

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

# Server configuration
host = os.getenv("SERVER_HOST", "0.0.0.0")
port = int(os.getenv("SERVER_PORT", "8000"))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    # ------------------------------------------------------------------
    # Initialize services
    # ------------------------------------------------------------------
    from app.razorpay_client.client import MerchantRazorpayClient
    from app.razorpay_client.webhook_handler import WebhookHandler
    from app.catalog.catalog_service import CatalogService
    from app.recommendations.engine import RecommendationEngine
    from app.recommendations.ai_ranker import AIRecommendationRanker
    from app.audit.audit_service import AuditService
    from app.checkout.cart_service import CartService
    from app.checkout.checkout_service import CheckoutService
    from app.campaigns.campaign_service import CampaignService
    from app.db.database import init_db, SqliteStore

    # Persistence — a single SQLite file backs carts, orders, campaign
    # usage counts, and stock levels. Restarting the server does not
    # lose any of this state.
    db_conn = init_db()
    carts_store = SqliteStore("carts", db_conn)
    orders_store = SqliteStore("orders", db_conn)
    campaigns_store = SqliteStore("campaign_usage", db_conn)
    stock_store = SqliteStore("product_stock", db_conn)

    # Core services
    razorpay_client = MerchantRazorpayClient()
    audit = AuditService(log_path=os.getenv("AUDIT_LOG_PATH", "audit_log.jsonl"))
    catalog = CatalogService(store=stock_store)
    campaign_service = CampaignService(store=campaigns_store)
    webhook_handler = WebhookHandler()

    # Seed data (persisted overrides — stock, usage counts — are applied
    # automatically during seeding)
    catalog.seed()
    campaign_service.seed_defaults()

    # Dependent services
    ai_ranker = AIRecommendationRanker()  # Gemini-backed; falls back to rules if no GOOGLE_API_KEY
    recommendations = RecommendationEngine(catalog._products, ai_ranker=ai_ranker)
    cart_service = CartService(catalog, audit, recommendations, store=carts_store)
    checkout_service = CheckoutService(
        cart_service, catalog, campaign_service, razorpay_client, audit, store=orders_store
    )

    # ------------------------------------------------------------------
    # Lifespan — startup/shutdown logic (replaces the deprecated
    # @app.on_event("startup") pattern)
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("=" * 60)
        logger.info("  Agentic Commerce Platform — Starting")
        logger.info("=" * 60)
        logger.info("Catalog: %d products loaded", len(catalog.list_products()))
        logger.info("Campaigns: %d active", len(campaign_service.list_active()))
        logger.info(
            "Persistence: SQLite (%s) — %d cart(s), %d order(s) restored from previous runs.",
            os.getenv("DATABASE_PATH", "agentic_commerce.db"),
            len(cart_service._carts),
            len(checkout_service._orders),
        )
        logger.info(
            "AI recommendation ranking: %s",
            "ENABLED (Gemini)" if ai_ranker.enabled else "disabled — falling back to rule-based ranking (set GOOGLE_API_KEY to enable)",
        )

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

        yield  # ---- application runs here ----

        logger.info("Agentic Commerce Platform — shutting down.")

    app = FastAPI(
        title="Agentic Commerce Merchant API",
        description=(
            "AI-transactable merchant storefront on Razorpay Test Mode. "
            "Supports agent-driven catalog discovery, cart management, "
            "two-phase checkout, upsell/cross-sell, campaign discounts, "
            "and complete audit trails."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow all origins for agent access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Attach services to app state for access in routes
    app.state.razorpay_client = razorpay_client
    app.state.audit = audit
    app.state.catalog = catalog
    app.state.campaign_service = campaign_service
    app.state.webhook_handler = webhook_handler
    app.state.recommendations = recommendations
    app.state.cart_service = cart_service
    app.state.checkout_service = checkout_service

    # Register routes
    from app.api.routes import router

    app.include_router(router)

    # Dashboard — a demo/control-room UI at /dashboard, separate from the
    # agent-facing JSON manifest at "/". Serves static/index.html.
    from fastapi.staticfiles import StaticFiles
    import os as _os
    static_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "static")
    if _os.path.isdir(static_dir):
        app.mount("/dashboard", StaticFiles(directory=static_dir, html=True), name="dashboard")

    return app


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
