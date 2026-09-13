# agentic commerce gemini

## Overview
An autonomous merchant storefront designed for **AI buyer agents**, fully built on Razorpay's test-mode APIs. This platform eliminates the need for human-driven UI checkouts, allowing AI agents to discover, browse, add to cart, apply discounts, and complete purchases entirely via API.

## Features

1. **Agent-Readable Catalog**: Structured product data via `Schema.org JSON-LD` enabling AI agents to reason about product specs, pricing, and availability.
2. **Bounded Shopping Carts**: AI agents declare a budget upfront (e.g., `spending_bound_paise`). Any action exceeding this budget is hard-rejected with a clear explanation.
3. **Conversational Checkout**: A two-phase process (`preview` -> `confirm`) ensures no money moves without explicit agent confirmation.
4. **Contextual Upsell/Cross-sell**: Rule-based recommendation engine offering contextually relevant alternatives with explainable logic.
5. **Campaign Orchestrator**: Supports flat, percentage, and category-bounded promotional discounts.
6. **Robust Audit Trail**: Every money-touching action (cart edits, discounts, bounding checks, payment updates) generates an immutable audit log entry containing the exact logic and outcome.
7. **Graceful Failures**: Fully resilient to payment failures, webhook signature tampering, inventory exhaustion, and Razorpay API transient errors.

## Getting Started

### Prerequisites

- Python 3.11+
- Razorpay Test Account

### Setup

1. **Install Dependencies**:
   ```bash
   pip install fastapi uvicorn razorpay pydantic python-dotenv httpx rich
   ```

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

## Architecture

- **`app/api/routes.py`**: FastAPI controller definitions for Discovery, Catalog, Cart, Checkout, Campaigns, and Webhooks.
- **`app/razorpay_client/client.py`**: Wrapper around Razorpay's Python SDK, embedding resilient retry patterns.
- **`app/models/`**: Pydantic v2 schemas representing the system state with automated JSON-LD bindings.
- **`app/audit/audit_service.py`**: High-fidelity logging engine writing to `audit_log.jsonl`.

## Autonomous LangGraph Agent

The repository now includes a true autonomous AI agent built with **LangChain** and **LangGraph** using Google Gemini!

To run it:
1. Ensure your Gemini API key is in the `.env` file as `GOOGLE_API_KEY=AQ.Ab...`
2. Double-click `run_agent.bat` or run:
   ```bash
   python -m agent.langgraph_agent
   ```

## Getting Started
Please refer to the source files for specific installation and usage instructions. Ensure that your local environment meets the standard requirements for the associated technologies.

## Project Structure
This project is organized into standard directories. Key configuration files and primary source code are located in the root directory.
