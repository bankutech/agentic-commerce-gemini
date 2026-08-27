"""Cart domain models with spending bound enforcement."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Optional


class SpendingBound(BaseModel):
    """Maximum spending limit declared by an AI buyer agent."""
    max_amount_paise: int = Field(gt=0, description="Maximum cart value in paise")
    currency: str = "INR"
    declared_by: str = Field(description="Agent or user identifier")
    declared_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CartItem(BaseModel):
    """An item in the shopping cart."""
    product_id: str
    product_name: str
    quantity: int = Field(gt=0, default=1)
    unit_price_paise: int = Field(gt=0)
    currency: str = "INR"

    @property
    def total_paise(self) -> int:
        return self.unit_price_paise * self.quantity


class Cart(BaseModel):
    """Shopping cart with spending bound enforcement."""
    id: str = Field(default_factory=lambda: f"cart_{uuid.uuid4().hex[:12]}")
    agent_id: str = Field(description="The AI buyer agent or session identifier")
    items: list[CartItem] = Field(default_factory=list)
    spending_bound: Optional[SpendingBound] = None
    campaign_code: Optional[str] = None
    discount_paise: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def subtotal_paise(self) -> int:
        return sum(item.total_paise for item in self.items)

    @property
    def total_paise(self) -> int:
        return max(0, self.subtotal_paise - self.discount_paise)

    def check_spending_bound(self, additional_paise: int = 0) -> tuple[bool, str]:
        """Check if cart + additional amount is within spending bound.
        Returns (is_within_bound, explanation)."""
        if self.spending_bound is None:
            return True, "No spending bound set — unlimited budget."
        projected = self.total_paise + additional_paise
        limit = self.spending_bound.max_amount_paise
        if projected <= limit:
            return True, f"Within budget: ₹{projected/100:.2f} / ₹{limit/100:.2f} ({projected*100//limit}% used)."
        return False, (
            f"REJECTED: ₹{projected/100:.2f} exceeds spending bound of ₹{limit/100:.2f} "
            f"(over by ₹{(projected - limit)/100:.2f}). Remove items or increase bound."
        )
