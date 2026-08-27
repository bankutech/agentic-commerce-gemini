"""Campaign service — manage promotional campaigns with bounds."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.campaign import Campaign, DiscountType

logger = logging.getLogger(__name__)


class CampaignService:
    """Manage bounded promotional campaigns."""

    def __init__(self):
        self._campaigns: dict[str, Campaign] = {}  # code -> Campaign
        self._seeded = False

    def seed_defaults(self) -> int:
        """Create default campaigns for demo purposes."""
        if self._seeded:
            return len(self._campaigns)

        defaults = [
            Campaign(
                code="WELCOME10",
                name="Welcome Discount",
                description="10% off for new customers, up to ₹500",
                discount_type=DiscountType.PERCENTAGE,
                discount_value=10,
                max_discount_paise=50000,
                min_cart_paise=100000,  # Min ₹1,000
                max_uses=50,
                valid_until=datetime.now(timezone.utc) + timedelta(days=30),
            ),
            Campaign(
                code="FLAT200",
                name="Flat ₹200 Off",
                description="Flat ₹200 off on orders above ₹2,000",
                discount_type=DiscountType.FLAT,
                discount_value=20000,  # ₹200 in paise
                max_discount_paise=20000,
                min_cart_paise=200000,  # Min ₹2,000
                max_uses=100,
                valid_until=datetime.now(timezone.utc) + timedelta(days=14),
            ),
            Campaign(
                code="BUNDLE10",
                name="Bundle Deal: 10% Off Accessories",
                description="10% off accessories when bought with a phone",
                discount_type=DiscountType.PERCENTAGE,
                discount_value=10,
                max_discount_paise=100000,  # Max ₹1,000
                eligible_categories=["accessories"],
                max_uses=200,
                valid_until=datetime.now(timezone.utc) + timedelta(days=60),
            ),
            Campaign(
                code="AUDIO15",
                name="Audio Sale",
                description="15% off all audio products, up to ₹750",
                discount_type=DiscountType.PERCENTAGE,
                discount_value=15,
                max_discount_paise=75000,
                eligible_categories=["audio"],
                max_uses=30,
                valid_until=datetime.now(timezone.utc) + timedelta(days=7),
            ),
        ]

        for c in defaults:
            self._campaigns[c.code.upper()] = c

        self._seeded = True
        logger.info("Seeded %d default campaigns.", len(defaults))
        return len(defaults)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_campaign(self, campaign: Campaign) -> Campaign:
        self._campaigns[campaign.code.upper()] = campaign
        return campaign

    def get_campaign(self, code: str) -> Optional[Campaign]:
        return self._campaigns.get(code.upper())

    def list_active(self) -> list[Campaign]:
        return [c for c in self._campaigns.values() if c.is_valid()[0]]

    def list_all(self) -> list[Campaign]:
        return list(self._campaigns.values())

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    def apply_campaign(
        self,
        code: str,
        cart_subtotal_paise: int,
        eligible_amount_paise: int,
    ) -> tuple[int, str, bool]:
        """Apply a campaign code.
        Returns (discount_paise, explanation, success).
        """
        campaign = self.get_campaign(code)
        if not campaign:
            return 0, f"Campaign code '{code}' not found.", False

        valid, reason = campaign.is_valid()
        if not valid:
            return 0, reason, False

        discount, explanation = campaign.calculate_discount(
            cart_subtotal_paise, eligible_amount_paise
        )

        if discount <= 0:
            return 0, explanation, False

        # Increment usage
        campaign.current_uses += 1

        return discount, explanation, True
