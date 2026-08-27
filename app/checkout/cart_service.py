"""Cart service — session-based cart management with spending bound enforcement."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.cart import Cart, CartItem, SpendingBound
from app.models.audit import AuditAction, GateResult
from app.audit.audit_service import AuditService
from app.catalog.catalog_service import CatalogService
from app.recommendations.engine import RecommendationEngine, Recommendation

logger = logging.getLogger(__name__)


class CartService:
    """Manage shopping carts with spending bound enforcement and recommendations."""

    def __init__(
        self,
        catalog: CatalogService,
        audit: AuditService,
        recommendations: RecommendationEngine,
    ):
        self._carts: dict[str, Cart] = {}
        self._catalog = catalog
        self._audit = audit
        self._recommendations = recommendations

    def create_cart(
        self,
        agent_id: str,
        max_budget_paise: Optional[int] = None,
    ) -> Cart:
        """Create a new cart with optional spending bound."""
        cart = Cart(agent_id=agent_id)

        if max_budget_paise and max_budget_paise > 0:
            cart.spending_bound = SpendingBound(
                max_amount_paise=max_budget_paise,
                declared_by=agent_id,
            )
            self._audit.log_action(
                action=AuditAction.SPENDING_BOUND_SET,
                actor=agent_id,
                explanation=(
                    f"Spending bound set to ₹{max_budget_paise / 100:.2f} "
                    f"for cart {cart.id}."
                ),
                amount_paise=max_budget_paise,
                cart_id=cart.id,
                gate_check=GateResult.PASSED,
                gate_details=f"Budget: ₹{max_budget_paise / 100:.2f}",
            )

        self._carts[cart.id] = cart

        self._audit.log_action(
            action=AuditAction.CART_CREATED,
            actor=agent_id,
            explanation=f"Cart {cart.id} created for agent {agent_id}.",
            cart_id=cart.id,
        )

        return cart

    def get_cart(self, cart_id: str) -> Optional[Cart]:
        return self._carts.get(cart_id)

    def add_item(
        self,
        cart_id: str,
        product_id: str,
        quantity: int = 1,
    ) -> tuple[Optional[Cart], str]:
        """Add an item to cart. Returns (cart, explanation).
        Enforces spending bounds and stock.
        """
        cart = self._carts.get(cart_id)
        if not cart:
            return None, f"Cart {cart_id} not found."

        product = self._catalog.get_product(product_id)
        if not product:
            return None, f"Product {product_id} not found in catalog."

        if product.stock < quantity:
            self._audit.log_action(
                action=AuditAction.ITEM_ADDED,
                actor=cart.agent_id,
                explanation=(
                    f"REJECTED: {product.name} out of stock. "
                    f"Requested: {quantity}, available: {product.stock}."
                ),
                cart_id=cart_id,
                gate_check=GateResult.REJECTED,
                gate_details=f"Insufficient stock: {product.stock} < {quantity}",
            )
            return cart, f"Insufficient stock for {product.name}. Available: {product.stock}, requested: {quantity}."

        # Check spending bound before adding
        item_total = product.price_paise * quantity
        within, bound_explanation = cart.check_spending_bound(item_total)
        if not within:
            self._audit.log_action(
                action=AuditAction.SPENDING_BOUND_EXCEEDED,
                actor=cart.agent_id,
                explanation=bound_explanation,
                amount_paise=item_total,
                cart_id=cart_id,
                gate_check=GateResult.REJECTED,
                gate_details=bound_explanation,
            )
            return cart, bound_explanation

        # Check if item already in cart -> update quantity
        existing = next((i for i in cart.items if i.product_id == product_id), None)
        if existing:
            existing.quantity += quantity
        else:
            cart.items.append(CartItem(
                product_id=product.id,
                product_name=product.name,
                quantity=quantity,
                unit_price_paise=product.price_paise,
                currency=product.currency,
            ))

        cart.updated_at = datetime.now(timezone.utc)

        self._audit.log_action(
            action=AuditAction.ITEM_ADDED,
            actor=cart.agent_id,
            explanation=(
                f"Added {quantity}x {product.name} ({product.price_display} each) to cart. "
                f"Cart total: ₹{cart.total_paise / 100:.2f}. {bound_explanation}"
            ),
            amount_paise=item_total,
            cart_id=cart_id,
            gate_check=GateResult.PASSED,
            gate_details=bound_explanation,
        )

        return cart, f"Added {quantity}x {product.name}. Cart total: ₹{cart.total_paise / 100:.2f}."

    def remove_item(
        self,
        cart_id: str,
        product_id: str,
    ) -> tuple[Optional[Cart], str]:
        """Remove an item from the cart."""
        cart = self._carts.get(cart_id)
        if not cart:
            return None, f"Cart {cart_id} not found."

        item = next((i for i in cart.items if i.product_id == product_id), None)
        if not item:
            return cart, f"Product {product_id} not in cart."

        removed_name = item.product_name
        removed_amount = item.total_paise
        cart.items = [i for i in cart.items if i.product_id != product_id]
        cart.updated_at = datetime.now(timezone.utc)

        self._audit.log_action(
            action=AuditAction.ITEM_REMOVED,
            actor=cart.agent_id,
            explanation=f"Removed {removed_name} from cart. Refunded ₹{removed_amount / 100:.2f}.",
            amount_paise=removed_amount,
            cart_id=cart_id,
        )

        return cart, f"Removed {removed_name}. New total: ₹{cart.total_paise / 100:.2f}."

    def get_recommendations(self, cart_id: str) -> list[Recommendation]:
        """Get product recommendations for the cart."""
        cart = self._carts.get(cart_id)
        if not cart or not cart.items:
            return []
        product_ids = [item.product_id for item in cart.items]
        return self._recommendations.get_recommendations(product_ids)

    def get_cart_view(self, cart_id: str) -> Optional[dict]:
        """Rich cart view with items, totals, bound status, and recommendations."""
        cart = self._carts.get(cart_id)
        if not cart:
            return None

        recs = self.get_recommendations(cart_id)
        within, bound_status = cart.check_spending_bound()

        return {
            "cart_id": cart.id,
            "agent_id": cart.agent_id,
            "items": [
                {
                    "product_id": i.product_id,
                    "product_name": i.product_name,
                    "quantity": i.quantity,
                    "unit_price_display": f"₹{i.unit_price_paise / 100:.2f}",
                    "line_total_display": f"₹{i.total_paise / 100:.2f}",
                    "line_total_paise": i.total_paise,
                }
                for i in cart.items
            ],
            "subtotal_paise": cart.subtotal_paise,
            "discount_paise": cart.discount_paise,
            "total_paise": cart.total_paise,
            "subtotal_display": f"₹{cart.subtotal_paise / 100:.2f}",
            "discount_display": f"-₹{cart.discount_paise / 100:.2f}" if cart.discount_paise else "₹0.00",
            "total_display": f"₹{cart.total_paise / 100:.2f}",
            "campaign_code": cart.campaign_code,
            "spending_bound": {
                "max_amount_display": f"₹{cart.spending_bound.max_amount_paise / 100:.2f}",
                "status": bound_status,
                "within_bound": within,
            } if cart.spending_bound else None,
            "recommendations": [r.to_dict() for r in recs],
        }
