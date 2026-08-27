"""Audit trail model — every money-touching action gets logged."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Any


class AuditAction(str, Enum):
    CART_CREATED = "cart_created"
    ITEM_ADDED = "item_added"
    ITEM_REMOVED = "item_removed"
    SPENDING_BOUND_SET = "spending_bound_set"
    SPENDING_BOUND_EXCEEDED = "spending_bound_exceeded"
    CAMPAIGN_APPLIED = "campaign_applied"
    CAMPAIGN_REJECTED = "campaign_rejected"
    DISCOUNT_APPLIED = "discount_applied"
    CHECKOUT_PREVIEWED = "checkout_previewed"
    CHECKOUT_CONFIRMED = "checkout_confirmed"
    ORDER_CREATED = "order_created"
    PAYMENT_LINK_CREATED = "payment_link_created"
    PAYMENT_CAPTURED = "payment_captured"
    PAYMENT_FAILED = "payment_failed"
    WEBHOOK_RECEIVED = "webhook_received"
    WEBHOOK_SIGNATURE_INVALID = "webhook_signature_invalid"
    RECOMMENDATION_MADE = "recommendation_made"
    RAZORPAY_ERROR = "razorpay_error"
    ITEM_SYNCED = "item_synced_to_razorpay"


class GateResult(str, Enum):
    PASSED = "passed"
    REJECTED = "rejected"
    NOT_APPLICABLE = "n/a"


class AuditEntry(BaseModel):
    """Immutable audit log entry for money-touching actions."""
    id: str = Field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: AuditAction
    actor: str = Field(description="Agent ID, 'system', or 'merchant'")
    amount_paise: Optional[int] = None
    currency: str = "INR"
    explanation: str = Field(description="Human/AI-readable explanation of why this action occurred")
    gate_check: GateResult = GateResult.NOT_APPLICABLE
    gate_details: Optional[str] = None

    # References
    cart_id: Optional[str] = None
    order_id: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_payment_link_id: Optional[str] = None

    # Extra context
    metadata: Optional[dict[str, Any]] = None
