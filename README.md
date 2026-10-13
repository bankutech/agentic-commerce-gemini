# AI Agentic Commerce Platform — Razorpay Test Mode

An autonomous merchant storefront designed for **AI buyer agents**, fully built on Razorpay's test-mode APIs. This platform eliminates the need for human-driven UI checkouts, allowing AI agents to discover, browse, add to cart, apply discounts, and complete purchases entirely via API.

## Features

1. **Agent-Readable Catalog**: Structured product data via `Schema.org JSON-LD` enabling AI agents to reason about product specs, pricing, and availability.
2. **Bounded Shopping Carts**: AI agents declare a budget upfront (e.g., `spending_bound_paise`). Any action exceeding this budget is hard-rejected with a clear explanation.
3. **Conversational Checkout**: A two-phase process (`preview` -> `confirm`) ensures no money moves without explicit agent confirmation.
4. **Contextual Upsell/Cross-sell**: A deterministic rule engine (`app/recommendations/engine.py`) generates the candidate recommendations — it always chooses from real, in-stock catalog products, so this step can never hallucinate a product. When `GOOGLE_API_KEY` is configured, `app/recommendations/ai_ranker.py` sends those candidates to Gemini to rank them by likely relevance to the current cart and rewrite each `reason` to be cart-specific, rather than the static rule text. Every recommendation response reports `recommendation_method`: `"ai_ranked"` or `"rule_based"`, and the `RECOMMENDATION_MADE` audit entry records which one ran and why — the AI is used to judge *which of the deterministic options fits best*, not to invent the catalog. If the key/SDK is missing or the call fails for any reason, it falls back to the rule-based order automatically — nothing breaks.
5. **Campaign Orchestrator**: Supports flat, percentage, and category-bounded promotional discounts.
6. **Robust Audit Trail**: Every money-touching action (cart edits, discounts, bounding checks, payment updates) generates an immutable audit log entry containing the exact logic and outcome.
7. **Graceful Failures**: Fully resilient to payment failures, webhook signature tampering, inventory exhaustion, and Razorpay API transient errors.
8. **Live Dashboard**: A control-room UI at `/dashboard` — catalog, cart, spending bound, recommendations, campaigns, two-phase checkout, and a live audit ledger, all in one place. See [Getting Started](#getting-started).

## Getting Started

### Prerequisites

- Python 3.11+
- Razorpay Test Account

### Setup

1. **Install Dependencies**:
   ```bash
   pip install fastapi uvicorn razorpay pydantic python-dotenv httpx rich
   ```
   To also run the autonomous LangGraph/Gemini agent (`agent/langgraph_agent.py`), install the extra dependencies too:
   ```bash
   pip install langgraph langchain langchain-google-genai google-genai
   ```
   (Or simply `pip install -e .` from the project root, which installs everything declared in `pyproject.toml`.)

2. **Configure Environment Variables**:
   Copy the `.env.example` file to `.env` and configure your Razorpay test-mode API keys:
   ```dotenv
   RAZORPAY_KEY_ID=rzp_test_...
   RAZORPAY_KEY_SECRET=...
   RAZORPAY_WEBHOOK_SECRET=...
   ```

3. **Start the API Server**:
   ```bash
   python main.py
   ```
   *The server runs locally at `http://localhost:8000`.*

4. **Open the Dashboard**:
   Visit `http://localhost:8000/dashboard` for a live control-room UI — browse
   the catalog, build a cart, watch the spending bound and upsell recommendations
   update in real time, apply a campaign, run the two-phase checkout, and watch
   every action land in the live audit ledger on the right, stamped PASSED or
   REJECTED as it happens. This is the fastest way to *see* the "explainable,
   bounded, gated" bar in action rather than reading about it — good for the
   pitch video. Agents should keep using the JSON API directly; the dashboard
   is a human-facing view onto the same audit trail.

## Running the Demo

The repository includes a comprehensive `AIBuyerAgent` showcasing different behaviors.

**Run the Full Interactive Suite:**
```bash
python -m agent.demo_scenarios
```

**Run a Specific Scenario:**
```bash
python -m agent.demo_scenarios --scenario happy_path
python -m agent.demo_scenarios --scenario upsell_accepted
python -m agent.demo_scenarios --scenario budget_exceeded
python -m agent.demo_scenarios --scenario payment_failure
```

**Run the Interactive Agent Shell:**
```bash
python -m agent.buyer_agent
```

## Running Tests

The repo includes an automated pytest suite (30 tests) covering catalog
discovery, cart/spending-bound gating, campaign discounts (including a
regression test for the `BUNDLE500` fix), two-phase checkout, the audit
trail, the revenue metrics endpoint, and the AI recommendation ranker's
fallback behavior. Tests run against an isolated temp SQLite DB and audit
log — they never touch your real `agentic_commerce.db` or `audit_log.jsonl`.

```bash
pip install pytest  # or: pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system diagram, the
explainable/bounded/gated breakdown, and the recommendation pipeline design.
Quick reference:

- **`app/api/routes.py`**: FastAPI controller definitions for Discovery, Catalog, Cart, Checkout, Campaigns, Metrics, and Webhooks.
- **`app/db/database.py`**: SQLite-backed persistence — carts, orders, campaign usage counts, and stock all survive a restart.
- **`app/razorpay_client/client.py`**: Wrapper around Razorpay's Python SDK, embedding resilient retry patterns.
- **`app/models/`**: Pydantic v2 schemas representing the system state with automated JSON-LD bindings.
- **`app/audit/audit_service.py`**: High-fidelity logging engine writing to `audit_log.jsonl`.

## Revenue Impact

The platform is designed to grow merchant revenue at three points in the funnel, each with a directly attributable, auditable amount:

1. **Cross-sell / upsell recommendations** (`app/recommendations/engine.py`): every product added via an accepted recommendation is traceable — the `upsell_accepted` demo scenario shows an agent trading a ₹9,999 budget earbud for a ₹22,999 premium one (+₹13,000 order value) after seeing an explained upsell.
2. **Bundle completion**: when a cart partially matches a bundle rule (e.g., phone + case, phone + earbuds), the engine surfaces the missing item with a discount hint (`BUNDLE10`, `BUNDLE500`) — nudging a single-item cart toward a multi-item order instead of losing the sale to cart abandonment.
3. **Campaign-driven conversion**: bounded, explainable discounts (`WELCOME10`, `FLAT200`, `AUDIO15`, `BUNDLE500`) are capped per-campaign (`max_discount_paise`, `max_uses`) so revenue given up is a known, controlled cost rather than an open-ended liability — every application (or rejection, e.g. an invalid/expired code) is logged with the exact math in `audit_log.jsonl`.

Because every cart/campaign/checkout action is audited with the resulting `amount_paise`, the audit log (`GET /audit`) doubles as a ledger an operator could aggregate to measure: incremental revenue from accepted upsells, bundle attach rate, and discount cost per campaign. `GET /metrics/revenue` computes exactly this aggregation live — confirmed GMV, total discount cost, the AI-ranked vs. rule-based recommendation split, and every gated rejection — with every figure traceable back to a specific `AuditEntry`.

## Persistence

Carts, orders, campaign usage counts, and stock levels are all persisted to
a local SQLite file (`agentic_commerce.db`, path configurable via
`DATABASE_PATH`). Every mutation is write-through persisted, and all state
is reloaded on boot — restarting the server does not lose an in-progress
cart, a partially-redeemed coupon's usage count, or a stock adjustment. The
audit trail remains a separate append-only `audit_log.jsonl` file.

## Autonomous LangGraph Agent

The repository now includes a true autonomous AI agent built with **LangChain** and **LangGraph** using Google Gemini!

To run it:
1. Ensure your Gemini API key is in the `.env` file as `GOOGLE_API_KEY=AQ.Ab...`
2. Double-click `run_agent.bat` or run:
   ```bash
   python -m agent.langgraph_agent
   ```
