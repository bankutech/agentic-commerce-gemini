"""Audit trail service — append-only log for every money-touching action."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.audit import AuditEntry, AuditAction, GateResult

logger = logging.getLogger(__name__)


class AuditService:
    """Append-only audit trail with in-memory index and JSONL persistence."""

    def __init__(self, log_path: str = "audit_log.jsonl"):
        self._entries: list[AuditEntry] = []
        self._by_order: dict[str, list[AuditEntry]] = {}  # order_id -> entries
        self._by_cart: dict[str, list[AuditEntry]] = {}  # cart_id -> entries
        self._log_path = Path(log_path)
        # Ensure log directory exists
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: AuditEntry) -> AuditEntry:
        """Append an audit entry. Returns the logged entry."""
        # In-memory storage
        self._entries.append(entry)

        # Index by order and cart
        if entry.order_id:
            self._by_order.setdefault(entry.order_id, []).append(entry)
        if entry.cart_id:
            self._by_cart.setdefault(entry.cart_id, []).append(entry)

        # Persist to JSONL
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        except Exception as e:
            logger.error("Failed to persist audit entry: %s", e)

        logger.info(
            "AUDIT | %s | %s | %s | %s",
            entry.action.value,
            entry.actor,
            f"₹{entry.amount_paise / 100:.2f}" if entry.amount_paise else "-",
            entry.explanation[:80],
        )
        return entry

    def log_action(
        self,
        action: AuditAction,
        actor: str,
        explanation: str,
        amount_paise: Optional[int] = None,
        cart_id: Optional[str] = None,
        order_id: Optional[str] = None,
        razorpay_order_id: Optional[str] = None,
        razorpay_payment_id: Optional[str] = None,
        razorpay_payment_link_id: Optional[str] = None,
        gate_check: GateResult = GateResult.NOT_APPLICABLE,
        gate_details: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> AuditEntry:
        """Convenience method to create and log an entry."""
        entry = AuditEntry(
            action=action,
            actor=actor,
            explanation=explanation,
            amount_paise=amount_paise,
            cart_id=cart_id,
            order_id=order_id,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_payment_link_id=razorpay_payment_link_id,
            gate_check=gate_check,
            gate_details=gate_details,
            metadata=metadata,
        )
        return self.log(entry)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_trail(self, order_id: str) -> list[AuditEntry]:
        """Get full audit trail for an order."""
        return self._by_order.get(order_id, [])

    def get_cart_trail(self, cart_id: str) -> list[AuditEntry]:
        """Get audit trail for a cart."""
        return self._by_cart.get(cart_id, [])

    def get_recent(self, limit: int = 50) -> list[AuditEntry]:
        """Get most recent audit entries."""
        return list(reversed(self._entries[-limit:]))

    def get_failures(self, limit: int = 20) -> list[AuditEntry]:
        """Get recent failure entries."""
        failures = [
            e for e in self._entries
            if e.gate_check == GateResult.REJECTED
            or e.action in (AuditAction.PAYMENT_FAILED, AuditAction.RAZORPAY_ERROR,
                           AuditAction.SPENDING_BOUND_EXCEEDED, AuditAction.WEBHOOK_SIGNATURE_INVALID)
        ]
        return list(reversed(failures[-limit:]))

    def get_all_entries(self) -> list[AuditEntry]:
        """Get all entries (careful with large logs)."""
        return list(self._entries)
