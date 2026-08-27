"""Checkout service — orchestrates cart → order → Razorpay payment link.

Two-phase checkout: preview then confirm.
No money moves without explicit confirmation.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Any

from app.models.cart import Cart
from app.models.order import Order, OrderStatus
from app.models.audit import AuditAction, GateResult
from app.audit.audit_service import AuditService
from app.catalog.catalog_service import CatalogService
from app.campaigns.campaign_service import CampaignService
from app.checkout.cart_service import CartService
from app.razorpay_client.client import MerchantRazorpayClient

logger = logging.getLogger(__name__)


class CheckoutService:
    """Two-phase checkout: preview → confirm."""

    def __init__(
        self,
        cart_service: CartService,
        catalog: CatalogService,
        campaign_service: CampaignService,
        razorpay_client: MerchantRazorpayClient,
        audit: AuditService,
    ):
        self._cart_service = cart_service
        self._catalog = catalog
        self._campaigns = campaign_service
        self._razorpay = razorpay_client
        self._audit = audit
        self._orders: dict[str, Order] = {}  # order_id -> Order
        self._orders_by_rz: dict[str, str] = {}  # razorpay_order_id -> order_id

    # ------------------------------------------------------------------
    # Phase 1: Preview
    # ------------------------------------------------------------------

    def preview_checkout(self, cart_id: str) -> tuple[Optional[dict], str]:
        """Preview checkout — show breakdown without creating Razorpay order.
        Returns (preview_dict, explanation).
        """
        cart = self._cart_service.get_cart(cart_id)
        if not cart:
            return None, f"Cart {cart_id} not found."
        if not cart.items:
            return None, "Cart is empty. Add items before checkout."

        # Check spending bound
        within, bound_msg = cart.check_spending_bound()
        if not within:
            return None, bound_msg

        # Get recommendations
        recs = self._cart_service.get_recommendations(cart_id)

        preview = {
            "cart_id": cart.id,
            "status": "preview",
            "message": "Review your order. Send confirm=true to proceed.",
            "items": [
                {
                    "product_id": i.product_id,
                    "name": i.product_name,
                    "quantity": i.quantity,
                    "unit_price_paise": i.unit_price_paise,
                    "line_total_paise": i.total_paise,
                }
                for i in cart.items
            ],
            "subtotal_paise": cart.subtotal_paise,
            "discount_paise": cart.discount_paise,
            "total_paise": cart.total_paise,
            "total_display": f"₹{cart.total_paise / 100:.2f}",
            "campaign_code": cart.campaign_code,
            "spending_bound_status": bound_msg,
            "recommendations": [r.to_dict() for r in recs],
            "requires_confirmation": True,
        }

        self._audit.log_action(
            action=AuditAction.CHECKOUT_PREVIEWED,
            actor=cart.agent_id,
            explanation=(
                f"Checkout preview for cart {cart_id}. "
                f"Total: ₹{cart.total_paise / 100:.2f} "
                f"({len(cart.items)} items). Awaiting confirmation."
            ),
            amount_paise=cart.total_paise,
            cart_id=cart_id,
        )

        return preview, "Preview generated. Confirm to proceed."

    # ------------------------------------------------------------------
    # Phase 2: Confirm & Create Order
    # ------------------------------------------------------------------

    def confirm_checkout(
        self,
        cart_id: str,
        customer_name: str = "AI Buyer Agent",
        customer_email: str = "agent@test.example.com",
        customer_contact: str = "+919999999999",
    ) -> tuple[Optional[dict], str]:
        """Confirm checkout — creates Razorpay order + payment link.
        Returns (order_dict, explanation).
        """
        cart = self._cart_service.get_cart(cart_id)
        if not cart:
            return None, f"Cart {cart_id} not found."
        if not cart.items:
            return None, "Cart is empty."

        # Final spending bound check
        within, bound_msg = cart.check_spending_bound()
        if not within:
            self._audit.log_action(
                action=AuditAction.SPENDING_BOUND_EXCEEDED,
                actor=cart.agent_id,
                explanation=f"Checkout BLOCKED: {bound_msg}",
                amount_paise=cart.total_paise,
                cart_id=cart_id,
                gate_check=GateResult.REJECTED,
                gate_details=bound_msg,
            )
            return None, bound_msg

        # Check stock for all items
        for item in cart.items:
            product = self._catalog.get_product(item.product_id)
            if not product or product.stock < item.quantity:
                msg = f"Insufficient stock for {item.product_name}."
                self._audit.log_action(
                    action=AuditAction.CHECKOUT_CONFIRMED,
                    actor=cart.agent_id,
                    explanation=f"Checkout BLOCKED: {msg}",
                    cart_id=cart_id,
                    gate_check=GateResult.REJECTED,
                    gate_details=msg,
                )
                return None, msg

        self._audit.log_action(
            action=AuditAction.CHECKOUT_CONFIRMED,
            actor=cart.agent_id,
            explanation=f"Checkout confirmed for cart {cart_id}. Creating Razorpay order.",
            amount_paise=cart.total_paise,
            cart_id=cart_id,
            gate_check=GateResult.PASSED,
            gate_details="All gates passed: spending bound, stock check.",
        )

        # Create internal order
        order = Order(
            cart_id=cart_id,
            agent_id=cart.agent_id,
            items=list(cart.items),
            subtotal_paise=cart.subtotal_paise,
            discount_paise=cart.discount_paise,
            total_paise=cart.total_paise,
            campaign_code=cart.campaign_code,
        )

        # Create Razorpay order
        receipt = f"ord_{order.id}_{int(time.time())}"
        rz_result = self._razorpay.create_order(
            amount_paise=order.total_paise,
            currency=order.currency,
            receipt=receipt[:40],
            notes={
                "internal_order_id": order.id,
                "cart_id": cart_id,
                "agent_id": cart.agent_id,
                "items_count": str(len(cart.items)),
            },
        )

        if not rz_result.success:
            self._audit.log_action(
                action=AuditAction.RAZORPAY_ERROR,
                actor="system",
                explanation=(
                    f"Razorpay order creation FAILED: {rz_result.error}. "
                    f"Error code: {rz_result.error_code}. "
                    f"Recovery: Retry checkout or contact support."
                ),
                amount_paise=order.total_paise,
                cart_id=cart_id,
                order_id=order.id,
                gate_check=GateResult.REJECTED,
                gate_details=f"Razorpay error: {rz_result.error_code}",
            )
            return None, f"Payment provider error: {rz_result.error}. Please retry."

        order.razorpay_order_id = rz_result.data.get("id")

        self._audit.log_action(
            action=AuditAction.ORDER_CREATED,
            actor=cart.agent_id,
            explanation=(
                f"Razorpay order {order.razorpay_order_id} created. "
                f"Amount: ₹{order.total_paise / 100:.2f}."
            ),
            amount_paise=order.total_paise,
            cart_id=cart_id,
            order_id=order.id,
            razorpay_order_id=order.razorpay_order_id,
        )

        # Create payment link
        item_desc = ", ".join(f"{i.quantity}x {i.product_name}" for i in cart.items)
        plink_result = self._razorpay.create_payment_link(
            amount_paise=order.total_paise,
            currency=order.currency,
            description=f"Order {order.id}: {item_desc}"[:250],
            customer={
                "name": customer_name,
                "email": customer_email,
                "contact": customer_contact,
            },
            reference_id=order.id,
            notes={
                "internal_order_id": order.id,
                "razorpay_order_id": order.razorpay_order_id or "",
            },
            expire_by=int(time.time()) + 3600,  # 1 hour expiry
        )

        if not plink_result.success:
            self._audit.log_action(
                action=AuditAction.RAZORPAY_ERROR,
                actor="system",
                explanation=(
                    f"Payment link creation FAILED: {plink_result.error}. "
                    f"Razorpay order {order.razorpay_order_id} exists but no link. "
                    f"Recovery: Retry or create link manually."
                ),
                amount_paise=order.total_paise,
                cart_id=cart_id,
                order_id=order.id,
                razorpay_order_id=order.razorpay_order_id,
                gate_check=GateResult.REJECTED,
            )
            return None, f"Payment link error: {plink_result.error}. Order created but link failed."

        order.razorpay_payment_link_id = plink_result.data.get("id")
        order.payment_link_url = plink_result.data.get("short_url")

        # Deduct stock
        for item in cart.items:
            self._catalog.update_stock(item.product_id, -item.quantity)

        # Store order
        self._orders[order.id] = order
        if order.razorpay_order_id:
            self._orders_by_rz[order.razorpay_order_id] = order.id

        self._audit.log_action(
            action=AuditAction.PAYMENT_LINK_CREATED,
            actor=cart.agent_id,
            explanation=(
                f"Payment link created: {order.payment_link_url}. "
                f"Amount: ₹{order.total_paise / 100:.2f}. "
                f"Expires in 1 hour. Pay using test card or UPI (success@razorpay)."
            ),
            amount_paise=order.total_paise,
            cart_id=cart_id,
            order_id=order.id,
            razorpay_order_id=order.razorpay_order_id,
            razorpay_payment_link_id=order.razorpay_payment_link_id,
        )

        return {
            "order_id": order.id,
            "status": order.status.value,
            "total_paise": order.total_paise,
            "total_display": f"₹{order.total_paise / 100:.2f}",
            "razorpay_order_id": order.razorpay_order_id,
            "payment_link_id": order.razorpay_payment_link_id,
            "payment_link_url": order.payment_link_url,
            "expires_in": "1 hour",
            "items": [
                {"name": i.product_name, "qty": i.quantity, "total_paise": i.total_paise}
                for i in order.items
            ],
            "discount_paise": order.discount_paise,
            "campaign_code": order.campaign_code,
            "test_payment_info": {
                "card": "5104 0600 0000 0008 (any future expiry, any CVV)",
                "upi_success": "success@razorpay",
                "upi_failure": "failure@razorpay",
            },
            "audit_trail": [
                {
                    "action": e.action.value,
                    "explanation": e.explanation,
                    "timestamp": e.timestamp.isoformat(),
                    "gate": e.gate_check.value,
                }
                for e in self._audit.get_cart_trail(cart_id)
            ],
        }, "Order created successfully. Use the payment link to complete payment."

    # ------------------------------------------------------------------
    # Order queries
    # ------------------------------------------------------------------

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_order_by_razorpay_id(self, rz_order_id: str) -> Optional[Order]:
        oid = self._orders_by_rz.get(rz_order_id)
        return self._orders.get(oid) if oid else None

    def get_order_status(self, order_id: str) -> Optional[dict[str, Any]]:
        """Get enriched order status, polling Razorpay if needed."""
        order = self._orders.get(order_id)
        if not order:
            return None

        # If still 'created', poll Razorpay for updates
        if order.status == OrderStatus.CREATED and order.razorpay_payment_link_id:
            plink = self._razorpay.fetch_payment_link(order.razorpay_payment_link_id)
            if plink.success:
                rz_status = plink.data.get("status", "")
                if rz_status == "paid":
                    order.mark_paid(plink.data.get("payments", [{}])[0].get("payment_id", "poll_detected") if isinstance(plink.data.get("payments"), list) else "poll_detected")
                    self._audit.log_action(
                        action=AuditAction.PAYMENT_CAPTURED,
                        actor="system",
                        explanation=f"Payment detected via polling for order {order.id}.",
                        amount_paise=order.total_paise,
                        order_id=order.id,
                        razorpay_order_id=order.razorpay_order_id,
                    )
                elif rz_status == "expired":
                    order.mark_failed("Payment link expired")
                elif rz_status == "cancelled":
                    order.mark_failed("Payment link cancelled")

        return {
            "order_id": order.id,
            "status": order.status.value,
            "total_paise": order.total_paise,
            "total_display": f"₹{order.total_paise / 100:.2f}",
            "razorpay_order_id": order.razorpay_order_id,
            "payment_link_url": order.payment_link_url,
            "razorpay_payment_id": order.razorpay_payment_id,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "created_at": order.created_at.isoformat(),
            "audit_trail": [
                {
                    "action": e.action.value,
                    "explanation": e.explanation,
                    "timestamp": e.timestamp.isoformat(),
                    "gate": e.gate_check.value,
                }
                for e in self._audit.get_trail(order.id)
            ],
        }

    def handle_payment_update(
        self, razorpay_order_id: str, payment_id: str, status: str
    ) -> Optional[Order]:
        """Update order based on webhook payment event."""
        order = self.get_order_by_razorpay_id(razorpay_order_id)
        if not order:
            return None
        if status == "captured":
            order.mark_paid(payment_id)
        elif status == "failed":
            order.mark_failed(f"Payment {payment_id} failed")
        return order
