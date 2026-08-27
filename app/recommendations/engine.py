"""Upsell and cross-sell recommendation engine.

Rule-based recommendations with explainability.
Every recommendation includes a human/AI-readable `reason`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models.product import Product


@dataclass
class Recommendation:
    """A product recommendation with explanation."""
    product: Product
    rec_type: str  # "cross_sell", "upsell", "bundle"
    reason: str  # Human-readable explanation
    discount_hint: Optional[str] = None  # e.g., "10% off when bundled"
    confidence: float = 0.8  # 0-1 confidence score

    def to_dict(self) -> dict:
        return {
            "product_id": self.product.id,
            "product_name": self.product.name,
            "price": self.product.price_display,
            "price_paise": self.product.price_paise,
            "type": self.rec_type,
            "reason": self.reason,
            "discount_hint": self.discount_hint,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Cross-sell rules: product_id -> list of complementary product IDs
# ---------------------------------------------------------------------------
CROSS_SELL_RULES: dict[str, list[str]] = {
    # Phones -> cases, chargers, screen protectors, earbuds
    "prod_pixel9pro": ["prod_case_pixel9pro", "prod_charger_30w", "prod_buds_pro", "prod_screen_protector"],
    "prod_pixel9": ["prod_case_pixel9", "prod_charger_30w", "prod_buds_a", "prod_screen_protector"],
    # Earbuds -> chargers, cables
    "prod_buds_pro": ["prod_cable_usbc", "prod_charger_30w"],
    "prod_buds_a": ["prod_cable_usbc", "prod_charger_30w"],
    # Watch -> charger
    "prod_watch3": ["prod_charger_wireless", "prod_cable_usbc"],
    # Tablet -> charger, cable
    "prod_tablet": ["prod_charger_30w", "prod_cable_usbc"],
}

CROSS_SELL_REASONS: dict[str, dict[str, str]] = {
    "prod_pixel9pro": {
        "prod_case_pixel9pro": "Protect your Pixel 9 Pro — this clear case shows off the design while absorbing shocks.",
        "prod_charger_30w": "Get the fastest charging speed for your Pixel 9 Pro with this 30W USB-C charger.",
        "prod_buds_pro": "Complete your Pixel ecosystem with Pixel Buds Pro 2 — AI-powered noise cancellation.",
        "prod_screen_protector": "Shield your 6.3-inch OLED display from scratches and drops.",
    },
    "prod_pixel9": {
        "prod_case_pixel9": "Keep your Pixel 9 safe with this silicone case — soft-touch grip, MagSafe ready.",
        "prod_charger_30w": "Charge your Pixel 9 to 50% in about 30 minutes with this fast charger.",
        "prod_buds_a": "Pair with affordable Pixel Buds A-Series for hands-free Google Assistant.",
        "prod_screen_protector": "Protect your display with 9H tempered glass — easy bubble-free install.",
    },
}

# ---------------------------------------------------------------------------
# Upsell rules: product_id -> (upgrade_product_id, reason)
# ---------------------------------------------------------------------------
UPSELL_RULES: dict[str, tuple[str, str]] = {
    "prod_pixel9": (
        "prod_pixel9pro",
        "Upgrade to Pixel 9 Pro for a superior triple camera system, 16GB RAM, and advanced AI features (+₹3,000).",
    ),
    "prod_buds_a": (
        "prod_buds_pro",
        "Upgrade to Pixel Buds Pro 2 for active noise cancellation, Tensor A1 chip, and 12h battery (+₹1,300).",
    ),
}

# ---------------------------------------------------------------------------
# Bundle rules: frozenset of product_ids -> discount description
# ---------------------------------------------------------------------------
BUNDLE_RULES: list[tuple[set[str], str, str]] = [
    (
        {"prod_pixel9pro", "prod_case_pixel9pro"},
        "Phone + Case Bundle: 10% off the case!",
        "BUNDLE10",
    ),
    (
        {"prod_pixel9", "prod_case_pixel9"},
        "Phone + Case Bundle: 10% off the case!",
        "BUNDLE10",
    ),
    (
        {"prod_pixel9pro", "prod_buds_pro"},
        "Phone + Earbuds Bundle: ₹500 off earbuds!",
        "BUNDLE500",
    ),
]


class RecommendationEngine:
    """Rule-based recommendation engine with explainability."""

    def __init__(self, catalog_products: dict[str, Product]):
        self._products = catalog_products

    def update_catalog(self, products: dict[str, Product]) -> None:
        self._products = products

    def get_recommendations(
        self,
        cart_product_ids: list[str],
        max_recommendations: int = 5,
    ) -> list[Recommendation]:
        """Generate recommendations based on cart contents."""
        recs: list[Recommendation] = []
        cart_set = set(cart_product_ids)

        # 1. Cross-sell: suggest complementary products not already in cart
        for pid in cart_product_ids:
            cross_ids = CROSS_SELL_RULES.get(pid, [])
            reasons = CROSS_SELL_REASONS.get(pid, {})
            for cross_id in cross_ids:
                if cross_id in cart_set:
                    continue  # Already in cart
                product = self._products.get(cross_id)
                if product and product.stock > 0:
                    reason = reasons.get(
                        cross_id,
                        f"Frequently bought together with {self._products[pid].name}.",
                    )
                    recs.append(Recommendation(
                        product=product,
                        rec_type="cross_sell",
                        reason=reason,
                        confidence=0.85,
                    ))

        # 2. Upsell: suggest premium alternatives
        for pid in cart_product_ids:
            upsell = UPSELL_RULES.get(pid)
            if upsell:
                upgrade_id, reason = upsell
                if upgrade_id not in cart_set:
                    product = self._products.get(upgrade_id)
                    if product and product.stock > 0:
                        recs.append(Recommendation(
                            product=product,
                            rec_type="upsell",
                            reason=reason,
                            confidence=0.75,
                        ))

        # 3. Bundle deals: detect partial bundles
        for bundle_set, description, hint_code in BUNDLE_RULES:
            overlap = cart_set & bundle_set
            missing = bundle_set - cart_set
            if len(overlap) >= 1 and len(missing) >= 1:
                for mid in missing:
                    product = self._products.get(mid)
                    if product and product.stock > 0:
                        recs.append(Recommendation(
                            product=product,
                            rec_type="bundle",
                            reason=description,
                            discount_hint=f"Use code {hint_code} at checkout.",
                            confidence=0.9,
                        ))

        # Deduplicate by product_id, keep highest confidence
        seen: dict[str, Recommendation] = {}
        for r in recs:
            if r.product.id not in seen or r.confidence > seen[r.product.id].confidence:
                seen[r.product.id] = r

        # Sort by confidence descending, limit
        result = sorted(seen.values(), key=lambda r: r.confidence, reverse=True)
        return result[:max_recommendations]

    def explain_recommendations(self, recs: list[Recommendation]) -> str:
        """Human-readable summary of all recommendations."""
        if not recs:
            return "No recommendations for current cart."
        lines = []
        for i, r in enumerate(recs, 1):
            lines.append(
                f"{i}. [{r.rec_type.upper()}] {r.product.name} ({r.product.price_display}) — {r.reason}"
            )
            if r.discount_hint:
                lines.append(f"   💡 {r.discount_hint}")
        return "\n".join(lines)
