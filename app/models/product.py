"""Product domain models with Schema.org JSON-LD serialization."""
from __future__ import annotations
import uuid
from pydantic import BaseModel, Field
from typing import Optional


class Product(BaseModel):
    """A product in the merchant catalog."""
    id: str = Field(default_factory=lambda: f"prod_{uuid.uuid4().hex[:12]}")
    name: str
    description: str
    price_paise: int = Field(gt=0, description="Price in paise (smallest currency unit)")
    currency: str = "INR"
    category: str
    tags: list[str] = Field(default_factory=list)
    stock: int = Field(ge=0, default=100)
    image_url: Optional[str] = None
    sku: str = ""
    razorpay_item_id: Optional[str] = None  # Synced Razorpay item ID

    @property
    def price_display(self) -> str:
        """Human-readable price."""
        major = self.price_paise // 100
        minor = self.price_paise % 100
        return f"₹{major}.{minor:02d}"

    def to_jsonld(self) -> dict:
        """Serialize to Schema.org Product JSON-LD for AI agent consumption."""
        return {
            "@context": "https://schema.org/",
            "@type": "Product",
            "@id": f"urn:merchant:product:{self.id}",
            "name": self.name,
            "description": self.description,
            "sku": self.sku or self.id,
            "category": self.category,
            "image": self.image_url,
            "additionalProperty": [
                {"@type": "PropertyValue", "name": "tags", "value": ",".join(self.tags)}
            ],
            "offers": {
                "@type": "Offer",
                "priceCurrency": self.currency,
                "price": str(self.price_paise / 100),
                "availability": "https://schema.org/InStock" if self.stock > 0 else "https://schema.org/OutOfStock",
                "itemCondition": "https://schema.org/NewCondition",
            },
        }


class ProductCatalog(BaseModel):
    """A collection of products as Schema.org ItemList."""
    products: list[Product] = Field(default_factory=list)

    def to_jsonld(self) -> dict:
        """Full catalog as Schema.org ItemList."""
        return {
            "@context": "https://schema.org/",
            "@type": "ItemList",
            "name": "Merchant Product Catalog",
            "numberOfItems": len(self.products),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "item": p.to_jsonld(),
                }
                for i, p in enumerate(self.products)
            ],
        }
