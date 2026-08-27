"""Catalog service — product management with Schema.org JSON-LD output."""
from __future__ import annotations

import logging
from typing import Optional

from app.models.product import Product, ProductCatalog
from app.catalog.seed_data import get_seed_products

logger = logging.getLogger(__name__)


class CatalogService:
    """In-memory product catalog with CRUD and JSON-LD serialization."""

    def __init__(self):
        self._products: dict[str, Product] = {}
        self._seeded = False

    def seed(self) -> int:
        """Seed catalog with sample products. Returns count."""
        if self._seeded:
            return len(self._products)
        for product in get_seed_products():
            self._products[product.id] = product
        self._seeded = True
        logger.info("Catalog seeded with %d products.", len(self._products))
        return len(self._products)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_product(self, product_id: str) -> Optional[Product]:
        return self._products.get(product_id)

    def list_products(self) -> list[Product]:
        return list(self._products.values())

    def add_product(self, product: Product) -> Product:
        self._products[product.id] = product
        return product

    def update_stock(self, product_id: str, delta: int) -> Optional[Product]:
        """Adjust stock by delta (negative to decrease)."""
        product = self._products.get(product_id)
        if product:
            product.stock = max(0, product.stock + delta)
        return product

    def set_razorpay_item_id(self, product_id: str, rz_item_id: str) -> None:
        """Link local product to Razorpay item ID."""
        product = self._products.get(product_id)
        if product:
            product.razorpay_item_id = rz_item_id

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        max_price_paise: Optional[int] = None,
        min_price_paise: Optional[int] = None,
        tags: Optional[list[str]] = None,
        in_stock_only: bool = True,
    ) -> list[Product]:
        """Search products with filters."""
        results = list(self._products.values())

        if in_stock_only:
            results = [p for p in results if p.stock > 0]

        if category:
            results = [p for p in results if p.category.lower() == category.lower()]

        if max_price_paise is not None:
            results = [p for p in results if p.price_paise <= max_price_paise]

        if min_price_paise is not None:
            results = [p for p in results if p.price_paise >= min_price_paise]

        if tags:
            tag_set = {t.lower() for t in tags}
            results = [p for p in results if tag_set & {t.lower() for t in p.tags}]

        if query:
            q = query.lower()
            results = [
                p for p in results
                if q in p.name.lower()
                or q in p.description.lower()
                or q in p.category.lower()
                or any(q in t.lower() for t in p.tags)
            ]

        return results

    # ------------------------------------------------------------------
    # JSON-LD serialization
    # ------------------------------------------------------------------

    def get_catalog_jsonld(self) -> dict:
        """Full catalog as Schema.org ItemList JSON-LD."""
        catalog = ProductCatalog(products=self.list_products())
        return catalog.to_jsonld()

    def get_product_jsonld(self, product_id: str) -> Optional[dict]:
        """Single product as Schema.org Product JSON-LD."""
        product = self.get_product(product_id)
        return product.to_jsonld() if product else None
