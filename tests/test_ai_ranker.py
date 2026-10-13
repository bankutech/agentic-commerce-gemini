"""Unit tests for AIRecommendationRanker — the fallback paths must never
break the recommendation flow, with or without a real Gemini key."""
import os

from app.models.product import Product
from app.models.cart import CartItem
from app.recommendations.engine import RecommendationEngine
from app.recommendations.ai_ranker import AIRecommendationRanker


def _sample_products() -> dict[str, Product]:
    return {
        "prod_pixel9": Product(
            id="prod_pixel9", name="Google Pixel 9", description="phone",
            price_paise=7999900, category="smartphones", stock=10,
        ),
        "prod_case_pixel9": Product(
            id="prod_case_pixel9", name="Pixel 9 Case", description="case",
            price_paise=299900, category="accessories", stock=10,
        ),
        "prod_charger_30w": Product(
            id="prod_charger_30w", name="30W Charger", description="charger",
            price_paise=299900, category="chargers", stock=10,
        ),
        "prod_buds_a": Product(
            id="prod_buds_a", name="Buds A", description="earbuds",
            price_paise=999900, category="audio", stock=10,
        ),
        "prod_screen_protector": Product(
            id="prod_screen_protector", name="Screen Protector", description="sp",
            price_paise=99900, category="accessories", stock=10,
        ),
    }


def test_ranker_disabled_without_api_key():
    os.environ.pop("GOOGLE_API_KEY", None)
    ranker = AIRecommendationRanker()
    assert ranker.enabled is False


def test_ranker_disabled_with_placeholder_key():
    ranker = AIRecommendationRanker(api_key="rzp_test_REPLACE_ME")
    assert ranker.enabled is False


def test_engine_falls_back_to_rule_based_without_ranker():
    engine = RecommendationEngine(_sample_products())  # no ai_ranker at all
    cart_items = [CartItem(
        product_id="prod_pixel9", product_name="Google Pixel 9",
        quantity=1, unit_price_paise=7999900,
    )]
    recs, method = engine.get_recommendations_for_cart(cart_items)
    assert method == "rule_based"
    assert len(recs) > 0


def test_engine_falls_back_to_rule_based_when_ranker_disabled():
    os.environ.pop("GOOGLE_API_KEY", None)
    ranker = AIRecommendationRanker()
    engine = RecommendationEngine(_sample_products(), ai_ranker=ranker)
    cart_items = [CartItem(
        product_id="prod_pixel9", product_name="Google Pixel 9",
        quantity=1, unit_price_paise=7999900,
    )]
    recs, method = engine.get_recommendations_for_cart(cart_items)
    assert method == "rule_based"
    assert len(recs) > 0
    # Every recommended product must be a real catalog product — the
    # anti-hallucination guarantee holds even on the fallback path.
    for r in recs:
        assert r.product.id in _sample_products()


def test_ranker_rank_returns_candidates_unchanged_when_disabled():
    ranker = AIRecommendationRanker()  # no key -> disabled
    engine = RecommendationEngine(_sample_products())
    candidates = engine.get_recommendations(["prod_pixel9"])
    ranked, method = ranker.rank([], candidates)
    assert method == "rule_based"
    assert ranked == candidates
