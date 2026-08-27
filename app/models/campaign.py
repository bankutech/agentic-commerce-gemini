"""Campaign and discount models with bounds enforcement."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FLAT = "flat"
    BUY_X_GET_Y = "buy_x_get_y"


class Campaign(BaseModel):
    """A bounded promotional campaign."""
    id: str = Field(default_factory=lambda: f"camp_{uuid.uuid4().hex[:8]}")
    code: str = Field(description="Campaign/coupon code")
    name: str
    description: str
    discount_type: DiscountType
    discount_value: int = Field(description="Percentage (0-100) or flat amount in paise")
    max_discount_paise: int = Field(gt=0, description="Maximum discount cap in paise")
    min_cart_paise: int = Field(ge=0, default=0, description="Minimum cart value to qualify")
    eligible_categories: list[str] = Field(default_factory=list, description="Empty = all categories")
    max_uses: int = Field(gt=0, default=100)
    current_uses: int = 0
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    active: bool = True

    def is_valid(self) -> tuple[bool, str]:
        """Check if campaign is currently valid."""
        now = datetime.now(timezone.utc)
        if not self.active:
            return False, "Campaign is inactive."
        if self.current_uses >= self.max_uses:
            return False, f"Campaign exhausted ({self.current_uses}/{self.max_uses} uses)."
        if now < self.valid_from:
            return False, f"Campaign not yet active (starts {self.valid_from.isoformat()})."
        if self.valid_until and now > self.valid_until:
            return False, f"Campaign expired (ended {self.valid_until.isoformat()})."
        return True, "Campaign is valid."

    def calculate_discount(self, cart_subtotal_paise: int, eligible_amount_paise: int) -> tuple[int, str]:
        """Calculate discount amount. Returns (discount_paise, explanation)."""
        if cart_subtotal_paise < self.min_cart_paise:
            return 0, f"Cart ₹{cart_subtotal_paise/100:.2f} below minimum ₹{self.min_cart_paise/100:.2f}."

        if self.discount_type == DiscountType.PERCENTAGE:
            raw = int(eligible_amount_paise * self.discount_value / 100)
            capped = min(raw, self.max_discount_paise)
            return capped, (
                f"{self.discount_value}% off = ₹{raw/100:.2f}, "
                f"capped at ₹{self.max_discount_paise/100:.2f} → ₹{capped/100:.2f} discount."
            )
        elif self.discount_type == DiscountType.FLAT:
            capped = min(self.discount_value, self.max_discount_paise)
            return capped, f"Flat ₹{capped/100:.2f} discount applied."
        return 0, "Unknown discount type."
