# Architecture — Agentic Commerce Platform

Track 01: AI Growth & Agentic Commerce. This document is the standalone
architecture reference for the buildathon submission — pair it with the
README (setup/usage) and the pitch video.

## System diagram

```
 Customer / AI Buyer Agent
            │
            ▼
   ┌─────────────────┐
   │   AI Agent       │   agent/langgraph_agent.py (Gemini ReAct)
   │  (buyer_agent.py │   or agent/buyer_agent.py (scripted CLI)
   │   / LangGraph)   │
   └────────┬─────────┘
            │  HTTP (FastAPI)
            ▼
   ┌─────────────────┐
   │   Discovery      │   GET /            (Schema.org WebAPI manifest)
   │                  │   GET /catalog     (Schema.org ItemList/Product JSON-LD)
   └────────┬─────────┘
            ▼
   ┌─────────────────┐
   │  Cart / Upsell   │   POST /cart, POST /cart/{id}/items
   │     Agent        │   GET  /cart/{id}/recommendations   ← explicit AI-judgment step
   │                  │   (rule engine generates candidates → Gemini ranks/explains them,
   │                  │    or falls back to rule-based order — see below)
   └────────┬─────────┘
            ▼
   ┌─────────────────┐
   │    Checkout      │   POST /cart/{id}/checkout   (preview — Phase 1)
   │  (two-phase,     │   POST /cart/{id}/confirm    (confirm — Phase 2)
   │   gated)         │   Every gate (spending bound, stock, campaign cap)
   │                  │   is checked BEFORE Razorpay is ever touched.
   └────────┬─────────┘
            ▼
   ┌─────────────────┐
   │    Payment        │   Razorpay Order + Payment Link (test mode)
   │   (Razorpay)       │   POST /webhooks/razorpay (signature-verified, idempotent)
   └────────┬─────────┘
            ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Audit Trail (every money-touching action, always)           │
   │  GET /audit · GET /audit/failures · GET /audit/{order_id}    │
   │  GET /metrics/revenue  ← growth evidence, computed from audit│
   └─────────────────────────────────────────────────────────────┘
```

## The bar: "every money action explainable, bounded, and gated"

| Requirement | How it's implemented |
|---|---|
| **Explainable** | Every mutation that touches money (add item, apply campaign, checkout, payment capture, webhook) writes an `AuditEntry` with a human-readable `explanation` string — not just an event code. `GET /audit/{order_id}` returns the full, ordered story of one order. |
| **Bounded** | Two independent bounds: (1) `SpendingBound` on the cart — `add_item` computes the item's cost *before* adding it and rejects if it would exceed the agent's stated budget; (2) campaign bounds — `max_discount_paise` and `max_uses` cap how much revenue a coupon can give away, enforced server-side, not client-side. |
| **Gated** | Checkout is two-phase: `preview_checkout` computes the full breakdown but moves no money; `confirm_checkout` re-validates the spending bound and stock *again* immediately before calling Razorpay. A gate is never "trust the client's last read" — it's re-checked at the moment of the money-moving call. |

## Data flow: recommendations (the "Upsell Agent" node)

This is deliberately a two-stage pipeline, not a single LLM call:

1. **Candidate generation (deterministic)** — `app/recommendations/engine.py` matches the cart's contents against fixed rule tables (`CROSS_SELL_RULES`, `UPSELL_RULES`, `BUNDLE_RULES`) built from the real, in-stock catalog. This stage can never hallucinate a product — it only ever returns real `product_id`s.
2. **Ranking/explanation (AI, optional)** — `app/recommendations/ai_ranker.py` sends the candidate set (never the whole catalog) to Gemini and asks it to reorder them by relevance to *this* cart and rewrite each `reason` to be cart-specific. The model is constrained to only return `product_id`s that were in the candidate set; anything else is discarded.
3. **Fallback (always safe)** — if `GOOGLE_API_KEY` isn't set, the SDK isn't installed, the call times out, or the response doesn't validate, step 2 is skipped entirely and the rule-based order/reasons from step 1 are returned unchanged. Every API response reports `recommendation_method: "ai_ranked" | "rule_based"` so this is never hidden.

This keeps AI in a **judgment** role (which real option fits best, and why) rather than a **catalog** role (inventing what exists) — a deliberate design choice for a system that touches real money.

## Persistence

Everything is backed by a single SQLite file (`agentic_commerce.db`, path
configurable via `DATABASE_PATH`): carts, orders, campaign usage counts, and
stock levels are all write-through persisted on every mutation and reloaded
on boot. A server restart does not lose an in-progress cart, a partially
redeemed coupon's usage count, or stock adjustments. The audit trail is a
separate append-only JSONL file (`audit_log.jsonl`) — deliberately
append-only rather than mutable rows, since an audit trail that can be
edited after the fact isn't one.

## Failure handling (evidence, not assertion)

- **Spending bound exceeded** → `add_item` rejects before mutating the cart, logs `SPENDING_BOUND_EXCEEDED` with `gate_check=REJECTED`, returns a clear message. Covered by `tests/test_cart_and_spending_bound.py::test_add_item_over_budget_is_rejected`.
- **Insufficient stock** → same pattern, before any cart mutation.
- **Invalid/expired/exhausted campaign code** → `apply_campaign` returns `success=False` with a specific reason; never silently no-ops.
- **Razorpay unreachable / misconfigured keys** → `MerchantRazorpayClient` wraps every call in a `RazorpayResult(success, data, error)`; a failure logs `RAZORPAY_ERROR` and returns HTTP 400 with the underlying error message, never a raw 500 crash. Covered by `tests/test_checkout_and_audit.py::test_confirm_checkout_with_no_razorpay_keys_fails_gracefully`.
- **Tampered webhook signature** → `WebhookHandler` verifies HMAC signature before processing; a mismatch is rejected and logged as `WEBHOOK_SIGNATURE_INVALID`, never processed as if valid.

## Growth evidence

`GET /metrics/revenue` aggregates live from the audit trail: confirmed GMV,
total discount cost, the AI-ranked vs. rule-based recommendation split, and
every gated rejection. Nothing in this endpoint is hardcoded or simulated —
every number is traceable back to a specific `AuditEntry` via `GET /audit`.

## Known limitations (stated plainly, not hidden)

- In-memory working state is per-process; horizontal scaling would need a shared store (e.g. swap `SqliteStore` for a Postgres-backed equivalent — the interface is already narrow enough to do that as a drop-in).
- The recommendation rule tables are hand-authored for the 12 seeded products; a real merchant integration would need these generated from actual catalog/sales data, not hardcoded by product ID.
- No authentication/authorization layer — every endpoint is open, appropriate for a hackathon/test-mode demo, not for production merchant traffic.
