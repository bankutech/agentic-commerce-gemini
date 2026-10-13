"""AI-powered recommendation ranker.

Architecture: the RULE ENGINE (recommendations/engine.py) always generates
the candidate set — a fixed, known-good list of real product IDs from
the catalog. The LLM is only ever allowed to RANK and RE-EXPLAIN those
candidates, never to invent a product. This keeps AI in the judgment
role (which of these real options is most relevant to this cart right
now, and why) rather than the catalog role (which must stay
deterministic — a hallucinated product ID would break checkout).

Fails safe: if no API key is configured, the SDK isn't installed, the
call times out, errors, or returns something that doesn't validate
against the candidate set, this falls back to the original rule-based
order/reasons untouched. The caller always gets a usable result and
the failure mode is silent-degrade, never silent-corrupt.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.recommendations.engine import Recommendation
    from app.models.cart import CartItem

logger = logging.getLogger(__name__)


class AIRecommendationRanker:
    """Ranks and re-explains rule-generated recommendation candidates using Gemini."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-3.6-flash",
    ):
        self._api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
        self._model = model
        self._client = None

        if not self._api_key or "REPLACE_ME" in self._api_key:
            logger.info(
                "AIRecommendationRanker: no GOOGLE_API_KEY configured — "
                "recommendations will use rule-based ranking only."
            )
            return

        try:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
            logger.info("AIRecommendationRanker: Gemini client initialized (%s).", self._model)
        except ImportError:
            logger.warning(
                "AIRecommendationRanker: 'google-genai' not installed — "
                "recommendations will use rule-based ranking only. "
                "Install with: pip install google-genai"
            )
        except Exception as e:
            logger.warning(
                "AIRecommendationRanker: failed to init Gemini client (%s) — "
                "recommendations will use rule-based ranking only.", e,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def rank(
        self,
        cart_items: list["CartItem"],
        candidates: list["Recommendation"],
    ) -> tuple[list["Recommendation"], str]:
        """Re-rank and re-explain candidates using Gemini.

        Returns (recommendations, method) where method is "ai_ranked" if
        Gemini's ranking was used, or "rule_based" on any fallback path.
        Never raises.
        """
        if not self.enabled or not candidates:
            return candidates, "rule_based"

        candidate_by_id = {c.product.id: c for c in candidates}
        cart_summary = ", ".join(f"{i.quantity}x {i.product_name}" for i in cart_items) or "(empty)"
        candidate_summary = "\n".join(
            f"- id={c.product.id} | {c.product.name} | {c.product.price_display} | "
            f"type={c.rec_type} | rule_reason=\"{c.reason}\""
            for c in candidates
        )

        prompt = (
            "You are ranking upsell/cross-sell recommendations for a live agentic "
            "checkout. You MUST only use product ids from the candidate list below — "
            "never invent one, and never include an id that is not listed.\n\n"
            f"Customer's current cart: {cart_summary}\n\n"
            f"Candidate recommendations:\n{candidate_summary}\n\n"
            "Return a JSON array, ordered by how likely each candidate is to be "
            "accepted by this customer right now, most compelling first. "
            "For each item return an object with exactly these keys: "
            '"product_id" (must be one of the candidate ids above) and '
            '"reason" (one persuasive sentence grounded in the actual cart '
            "contents, under 25 words). Return ONLY the JSON array, no other text, "
            "no markdown fences."
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config={"response_mime_type": "application/json", "temperature": 0.3},
            )
            raw = (getattr(response, "text", None) or "").strip()
            if not raw:
                raise ValueError("Empty response from model")

            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON array")

            ranked: list["Recommendation"] = []
            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                pid = entry.get("product_id")
                candidate = candidate_by_id.get(pid)
                if candidate is None:
                    # Refuse anything not in the deterministic candidate set —
                    # this is the anti-hallucination guardrail.
                    continue
                reason = entry.get("reason")
                if isinstance(reason, str) and 0 < len(reason) <= 300:
                    candidate.reason = reason
                if not any(r.product.id == candidate.product.id for r in ranked):
                    ranked.append(candidate)

            # Anything the model dropped or malformed still gets appended at
            # the end, so a partial/bad response never loses a valid rec.
            seen_ids = {r.product.id for r in ranked}
            for c in candidates:
                if c.product.id not in seen_ids:
                    ranked.append(c)

            if not ranked:
                raise ValueError("AI ranking produced no valid candidates")

            return ranked, "ai_ranked"

        except Exception as e:
            logger.warning(
                "AIRecommendationRanker: ranking failed (%s) — falling back to rule-based order.", e,
            )
            return candidates, "rule_based"
