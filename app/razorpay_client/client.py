"""Razorpay API client wrapper with retry logic and structured error handling.

Every Razorpay interaction returns structured results suitable for audit logging.
Retries on transient 5xx errors with exponential backoff.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any, Optional

import razorpay
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured result types
# ---------------------------------------------------------------------------

class RazorpayResult:
    """Wrapper for Razorpay API responses — success or failure."""

    def __init__(
        self,
        success: bool,
        data: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        retries: int = 0,
    ):
        self.success = success
        self.data = data or {}
        self.error = error
        self.error_code = error_code
        self.retries = retries

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"success": self.success}
        if self.success:
            d["data"] = self.data
        else:
            d["error"] = self.error
            d["error_code"] = self.error_code
        if self.retries:
            d["retries"] = self.retries
        return d


# ---------------------------------------------------------------------------
# Client wrapper
# ---------------------------------------------------------------------------

class MerchantRazorpayClient:
    """Thin wrapper around the razorpay SDK with retry + structured errors."""

    MAX_RETRIES = 3
    BACKOFF_BASE = 0.5  # seconds

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ):
        self.key_id = key_id or os.getenv("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET", "")
        self.webhook_secret = webhook_secret or os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

        if not self.key_id or not self.key_secret:
            logger.warning(
                "Razorpay credentials not configured — API calls will fail. "
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env"
            )

        self._client = razorpay.Client(auth=(self.key_id, self.key_secret))

    # ------------------------------------------------------------------
    # Internal retry helper
    # ------------------------------------------------------------------

    def _call_with_retry(self, operation: str, fn, *args, **kwargs) -> RazorpayResult:
        """Execute a Razorpay SDK call with exponential-backoff retry on 5xx."""
        last_error = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                result = fn(*args, **kwargs)
                return RazorpayResult(success=True, data=result, retries=attempt)
            except razorpay.errors.BadRequestError as e:
                return RazorpayResult(
                    success=False,
                    error=str(e),
                    error_code="BAD_REQUEST",
                )
            except razorpay.errors.GatewayError as e:
                last_error = str(e)
                wait = self.BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Razorpay %s: gateway error (attempt %d/%d), retrying in %.1fs: %s",
                    operation, attempt + 1, self.MAX_RETRIES, wait, e,
                )
                time.sleep(wait)
            except razorpay.errors.ServerError as e:
                last_error = str(e)
                wait = self.BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Razorpay %s: server error (attempt %d/%d), retrying in %.1fs: %s",
                    operation, attempt + 1, self.MAX_RETRIES, wait, e,
                )
                time.sleep(wait)
            except Exception as e:
                return RazorpayResult(
                    success=False,
                    error=str(e),
                    error_code="UNKNOWN_ERROR",
                )

        return RazorpayResult(
            success=False,
            error=f"Failed after {self.MAX_RETRIES} retries: {last_error}",
            error_code="MAX_RETRIES_EXHAUSTED",
            retries=self.MAX_RETRIES,
        )

    # ------------------------------------------------------------------
    # Items API (catalog sync)
    # ------------------------------------------------------------------

    def create_item(
        self,
        name: str,
        amount_paise: int,
        currency: str = "INR",
        description: str = "",
    ) -> RazorpayResult:
        """Create a product item in Razorpay's catalog."""
        payload: dict[str, Any] = {
            "name": name,
            "amount": amount_paise,
            "currency": currency,
        }
        if description:
            payload["description"] = description
        return self._call_with_retry(
            "create_item",
            self._client.item.create,
            payload,
        )

    def fetch_items(self) -> RazorpayResult:
        """Fetch all items from Razorpay."""
        return self._call_with_retry("fetch_items", self._client.item.all)

    # ------------------------------------------------------------------
    # Orders API
    # ------------------------------------------------------------------

    def create_order(
        self,
        amount_paise: int,
        currency: str = "INR",
        receipt: str = "",
        notes: Optional[dict[str, str]] = None,
    ) -> RazorpayResult:
        """Create a Razorpay order (payment intent)."""
        payload: dict[str, Any] = {
            "amount": amount_paise,
            "currency": currency,
        }
        if receipt:
            payload["receipt"] = receipt
        if notes:
            payload["notes"] = notes
        return self._call_with_retry(
            "create_order",
            self._client.order.create,
            payload,
        )

    def fetch_order(self, order_id: str) -> RazorpayResult:
        """Fetch order details by Razorpay order ID."""
        return self._call_with_retry(
            "fetch_order",
            self._client.order.fetch,
            order_id,
        )

    def fetch_order_payments(self, order_id: str) -> RazorpayResult:
        """Fetch all payment attempts for a Razorpay order."""
        return self._call_with_retry(
            "fetch_order_payments",
            self._client.order.payments,
            order_id,
        )

    # ------------------------------------------------------------------
    # Payment Links API
    # ------------------------------------------------------------------

    def create_payment_link(
        self,
        amount_paise: int,
        currency: str = "INR",
        description: str = "",
        customer: Optional[dict[str, str]] = None,
        reference_id: str = "",
        notes: Optional[dict[str, str]] = None,
        expire_by: Optional[int] = None,
        callback_url: Optional[str] = None,
    ) -> RazorpayResult:
        """Create a shareable payment link."""
        payload: dict[str, Any] = {
            "amount": amount_paise,
            "currency": currency,
            "description": description or "Payment",
        }
        if customer:
            payload["customer"] = customer
        if reference_id:
            payload["reference_id"] = reference_id
        if notes:
            payload["notes"] = notes
        if expire_by:
            payload["expire_by"] = expire_by
        if callback_url:
            payload["callback_url"] = callback_url
            payload["callback_method"] = "get"
        # Enable reminders
        payload["reminder_enable"] = True
        payload["notify"] = {"sms": False, "email": False}  # Test mode: no real notifications

        return self._call_with_retry(
            "create_payment_link",
            self._client.payment_link.create,
            payload,
        )

    def fetch_payment_link(self, plink_id: str) -> RazorpayResult:
        """Fetch payment link status."""
        return self._call_with_retry(
            "fetch_payment_link",
            self._client.payment_link.fetch,
            plink_id,
        )

    # ------------------------------------------------------------------
    # Payments API
    # ------------------------------------------------------------------

    def fetch_payment(self, payment_id: str) -> RazorpayResult:
        """Fetch payment details."""
        return self._call_with_retry(
            "fetch_payment",
            self._client.payment.fetch,
            payment_id,
        )

    # ------------------------------------------------------------------
    # Customers API
    # ------------------------------------------------------------------

    def create_customer(
        self,
        name: str = "",
        email: str = "",
        contact: str = "",
        notes: Optional[dict[str, str]] = None,
    ) -> RazorpayResult:
        """Create a customer entity."""
        payload: dict[str, Any] = {}
        if name:
            payload["name"] = name
        if email:
            payload["email"] = email
        if contact:
            payload["contact"] = contact
        if notes:
            payload["notes"] = notes
        payload["fail_existing"] = 0  # Return existing if duplicate
        return self._call_with_retry(
            "create_customer",
            self._client.customer.create,
            payload,
        )

    # ------------------------------------------------------------------
    # Webhook signature verification
    # ------------------------------------------------------------------

    def verify_webhook_signature(
        self, body: str, signature: str
    ) -> tuple[bool, str]:
        """Verify Razorpay webhook signature. Returns (valid, explanation)."""
        if not self.webhook_secret:
            return False, "Webhook secret not configured."
        try:
            self._client.utility.verify_webhook_signature(
                body, signature, self.webhook_secret
            )
            return True, "Webhook signature verified successfully."
        except razorpay.errors.SignatureVerificationError:
            return False, "Webhook signature mismatch — possible tampering."
        except Exception as e:
            return False, f"Webhook verification error: {e}"

    # ------------------------------------------------------------------
    # Payment signature verification (checkout callback)
    # ------------------------------------------------------------------

    def verify_payment_signature(self, params: dict[str, str]) -> tuple[bool, str]:
        """Verify payment signature from checkout callback."""
        try:
            self._client.utility.verify_payment_signature(params)
            return True, "Payment signature verified."
        except razorpay.errors.SignatureVerificationError:
            return False, "Payment signature mismatch."
        except Exception as e:
            return False, f"Signature verification error: {e}"
