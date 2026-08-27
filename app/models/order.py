"""Order domain model mapping to Razorpay order lifecycle."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional

from app.models.cart import CartItem


class OrderStatus(str, Enum):
    CREATED = "created"
    ATTEMPTED = "attempted"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class Order(BaseModel):
    """An order linked to a Razorpay order and payment link."""
    id: str = Field(default_factory=lambda: f"ord_{uuid.uuid4().hex[:12]}")
    cart_id: str
    agent_id: str
    items: list[CartItem]
    subtotal_paise: int
    discount_paise: int = 0
    total_paise: int
    currency: str = "INR"
    status: OrderStatus = OrderStatus.CREATED

    # Razorpay references
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_payment_link_id: Optional[str] = None
    payment_link_url: Optional[str] = None

    # Campaign
    campaign_code: Optional[str] = None
    discount_explanation: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    paid_at: Optional[datetime] = None

    def mark_paid(self, payment_id: str) -> None:
        """Transition to paid status."""
        self.status = OrderStatus.PAID
        self.razorpay_payment_id = payment_id
        self.paid_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def mark_failed(self, reason: str = "") -> None:
        """Transition to failed status."""
        self.status = OrderStatus.FAILED
        self.updated_at = datetime.now(timezone.utc)
