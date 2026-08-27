"""Webhook handler — processes Razorpay webhook events with signature verification."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.models.audit import AuditAction, AuditEntry, GateResult

logger = logging.getLogger(__name__)


class WebhookEvent:
    """Parsed webhook event."""

    def __init__(self, event_type: str, payload: dict[str, Any], raw_body: str):
        self.event_type = event_type
        self.payload = payload
        self.raw_body = raw_body

    @property
    def order_entity(self) -> Optional[dict[str, Any]]:
        return self.payload.get("order", {}).get("entity")

    @property
    def payment_entity(self) -> Optional[dict[str, Any]]:
        return self.payload.get("payment", {}).get("entity")

    @property
    def payment_link_entity(self) -> Optional[dict[str, Any]]:
        return self.payload.get("payment_link", {}).get("entity")


class WebhookHandler:
    """Process Razorpay webhook events and generate audit entries."""

    # Events we know how to handle
    SUPPORTED_EVENTS = {
        "payment.captured",
        "payment.failed",
        "payment.authorized",
        "order.paid",
        "payment_link.paid",
        "payment_link.expired",
        "payment_link.cancelled",
    }

    def __init__(self):
        self._processed_event_ids: set[str] = set()  # Idempotency

    def parse_event(self, raw_body: str) -> tuple[Optional[WebhookEvent], str]:
        """Parse raw webhook body into a WebhookEvent.
        Returns (event, error_message).
        """
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON in webhook body: {e}"

        event_type = data.get("event")
        if not event_type:
            return None, "Missing 'event' field in webhook payload."

        payload = data.get("payload", {})
        return WebhookEvent(event_type, payload, raw_body), ""

    def is_duplicate(self, event_id: str) -> bool:
        """Check if we've already processed this event (idempotency)."""
        if event_id in self._processed_event_ids:
            return True
        self._processed_event_ids.add(event_id)
        return False

    def process_event(self, event: WebhookEvent) -> list[AuditEntry]:
        """Process a webhook event and return audit entries.
        Handles unknown events gracefully.
        """
        handler = {
            "payment.captured": self._handle_payment_captured,
            "payment.failed": self._handle_payment_failed,
            "payment.authorized": self._handle_payment_authorized,
            "order.paid": self._handle_order_paid,
            "payment_link.paid": self._handle_payment_link_paid,
            "payment_link.expired": self._handle_payment_link_expired,
            "payment_link.cancelled": self._handle_payment_link_cancelled,
        }.get(event.event_type)

        if handler is None:
            logger.info("Ignoring unsupported webhook event: %s", event.event_type)
            return [
                AuditEntry(
                    action=AuditAction.WEBHOOK_RECEIVED,
                    actor="razorpay_webhook",
                    explanation=f"Received unsupported event type '{event.event_type}' — ignored gracefully.",
                    metadata={"event_type": event.event_type},
                )
            ]

        return handler(event)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_payment_captured(self, event: WebhookEvent) -> list[AuditEntry]:
        payment = event.payment_entity or {}
        order_id = payment.get("order_id")
        return [
            AuditEntry(
                action=AuditAction.PAYMENT_CAPTURED,
                actor="razorpay_webhook",
                amount_paise=payment.get("amount"),
                explanation=(
                    f"Payment {payment.get('id')} captured via {payment.get('method', 'unknown')}. "
                    f"Amount: ₹{payment.get('amount', 0) / 100:.2f}."
                ),
                razorpay_payment_id=payment.get("id"),
                razorpay_order_id=order_id,
                gate_check=GateResult.PASSED,
                gate_details="Payment successfully captured by Razorpay.",
                metadata={"method": payment.get("method"), "vpa": payment.get("vpa")},
            )
        ]

    def _handle_payment_failed(self, event: WebhookEvent) -> list[AuditEntry]:
        payment = event.payment_entity or {}
        error_desc = payment.get("error_description", "Unknown error")
        error_code = payment.get("error_code", "UNKNOWN")
        return [
            AuditEntry(
                action=AuditAction.PAYMENT_FAILED,
                actor="razorpay_webhook",
                amount_paise=payment.get("amount"),
                explanation=(
                    f"Payment {payment.get('id')} FAILED. "
                    f"Error: {error_code} — {error_desc}. "
                    f"Recovery: Customer can retry via the same payment link."
                ),
                razorpay_payment_id=payment.get("id"),
                razorpay_order_id=payment.get("order_id"),
                gate_check=GateResult.REJECTED,
                gate_details=f"Payment rejected: {error_code}",
                metadata={"error_code": error_code, "error_description": error_desc},
            )
        ]

    def _handle_payment_authorized(self, event: WebhookEvent) -> list[AuditEntry]:
        payment = event.payment_entity or {}
        return [
            AuditEntry(
                action=AuditAction.WEBHOOK_RECEIVED,
                actor="razorpay_webhook",
                amount_paise=payment.get("amount"),
                explanation=(
                    f"Payment {payment.get('id')} authorized (pending capture). "
                    f"Method: {payment.get('method', 'unknown')}."
                ),
                razorpay_payment_id=payment.get("id"),
                razorpay_order_id=payment.get("order_id"),
            )
        ]

    def _handle_order_paid(self, event: WebhookEvent) -> list[AuditEntry]:
        order = event.order_entity or {}
        payment = event.payment_entity or {}
        return [
            AuditEntry(
                action=AuditAction.PAYMENT_CAPTURED,
                actor="razorpay_webhook",
                amount_paise=order.get("amount"),
                explanation=(
                    f"Order {order.get('id')} fully paid. "
                    f"Amount: ₹{order.get('amount', 0) / 100:.2f}. "
                    f"Payment: {payment.get('id')}."
                ),
                razorpay_payment_id=payment.get("id"),
                razorpay_order_id=order.get("id"),
                gate_check=GateResult.PASSED,
                gate_details="Order fully paid.",
            )
        ]

    def _handle_payment_link_paid(self, event: WebhookEvent) -> list[AuditEntry]:
        plink = event.payment_link_entity or {}
        payment = event.payment_entity or {}
        return [
            AuditEntry(
                action=AuditAction.PAYMENT_CAPTURED,
                actor="razorpay_webhook",
                amount_paise=plink.get("amount"),
                explanation=(
                    f"Payment link {plink.get('id')} paid. "
                    f"Amount: ₹{plink.get('amount', 0) / 100:.2f}. "
                    f"Reference: {plink.get('reference_id', 'N/A')}."
                ),
                razorpay_payment_id=payment.get("id"),
                razorpay_payment_link_id=plink.get("id"),
                gate_check=GateResult.PASSED,
            )
        ]

    def _handle_payment_link_expired(self, event: WebhookEvent) -> list[AuditEntry]:
        plink = event.payment_link_entity or {}
        return [
            AuditEntry(
                action=AuditAction.PAYMENT_FAILED,
                actor="razorpay_webhook",
                amount_paise=plink.get("amount"),
                explanation=(
                    f"Payment link {plink.get('id')} EXPIRED without payment. "
                    f"Amount: ₹{plink.get('amount', 0) / 100:.2f}. "
                    f"Recovery: Create a new payment link for the order."
                ),
                razorpay_payment_link_id=plink.get("id"),
                gate_check=GateResult.REJECTED,
                gate_details="Payment link expired.",
            )
        ]

    def _handle_payment_link_cancelled(self, event: WebhookEvent) -> list[AuditEntry]:
        plink = event.payment_link_entity or {}
        return [
            AuditEntry(
                action=AuditAction.PAYMENT_FAILED,
                actor="razorpay_webhook",
                amount_paise=plink.get("amount"),
                explanation=(
                    f"Payment link {plink.get('id')} cancelled. "
                    f"No payment was collected."
                ),
                razorpay_payment_link_id=plink.get("id"),
                gate_check=GateResult.REJECTED,
                gate_details="Payment link cancelled.",
            )
        ]
