"""LangGraph AI Buyer Agent.

This module provides a LangGraph ReAct agent that interacts with the
Agentic Commerce API to autonomously fulfill natural language shopping requests.

Usage:
    set OPENAI_API_KEY=sk-...
    python -m agent.langgraph_agent "I have a budget of Rs 100,000. Buy a Pixel 9 and earbuds."
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from rich.console import Console
from rich.panel import Panel

# Support Windows console encoding for rich
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
console = Console(force_terminal=True)

load_dotenv()

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
AGENT_ID = "langgraph_buyer_001"


def _get(path: str) -> dict:
    try:
        r = httpx.get(f"{BASE_URL}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": e.response.text, "status_code": e.response.status_code}
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, json: dict | None = None) -> dict:
    try:
        r = httpx.post(f"{BASE_URL}{path}", json=json or {}, timeout=30)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": e.response.text, "status_code": e.response.status_code}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# LangChain Tools
# ---------------------------------------------------------------------------

@tool
def discover_store() -> dict:
    """Discover the store's capabilities and manifest information."""
    return _get("/")


@tool
def get_catalog() -> dict:
    """Get the full catalog of products available in the store as Schema.org JSON-LD."""
    return _get("/catalog")


@tool
def search_products(query: str = "", category: str = "") -> dict:
    """Search for products in the catalog by query or category."""
    params = []
    if query:
        params.append(f"q={query}")
    if category:
        params.append(f"category={category}")
    qs = "?" + "&".join(params) if params else ""
    return _get(f"/catalog/search{qs}")


@tool
def create_cart(budget_paise: int) -> dict:
    """Create a new shopping cart with a specific budget limit in paise (1 INR = 100 paise).
    Returns a cart_id which must be used for all subsequent cart operations.
    """
    return _post("/cart", {
        "agent_id": AGENT_ID,
        "max_budget_paise": budget_paise
    })


@tool
def add_to_cart(cart_id: str, product_id: str, quantity: int = 1) -> dict:
    """Add a product to the cart by its product_id. 
    IMPORTANT: The product_id must be the raw ID (e.g., 'prod_pixel9'), NOT the full URN.
    If you have a URN like 'urn:merchant:product:prod_pixel9', use only 'prod_pixel9'.
    If the addition exceeds the budget, it will return an error and the item will not be added.
    """
    if product_id.startswith("urn:merchant:product:"):
        product_id = product_id.replace("urn:merchant:product:", "")
        
    return _post(f"/cart/{cart_id}/items", {
        "product_id": product_id,
        "quantity": quantity
    })


@tool
def list_campaigns() -> dict:
    """List available promotional campaign codes and discounts."""
    return _get("/campaigns")


@tool
def apply_campaign(cart_id: str, code: str) -> dict:
    """Apply a promotional campaign code to a cart."""
    return _post(f"/cart/{cart_id}/apply-campaign", {"code": code})


@tool
def preview_checkout(cart_id: str) -> dict:
    """Preview the checkout to see the final total, subtotal, and any discounts applied.
    This must be called before confirming the checkout.
    """
    return _post(f"/cart/{cart_id}/checkout")


@tool
def confirm_checkout(cart_id: str, customer_name: str, customer_email: str) -> dict:
    """Confirm the checkout and place the order. 
    This creates the Razorpay order and returns the payment link.
    """
    return _post(f"/cart/{cart_id}/confirm", {
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_contact": "+919999999999"
    })


# Compile tools list
tools = [
    discover_store,
    get_catalog,
    search_products,
    create_cart,
    add_to_cart,
    list_campaigns,
    apply_campaign,
    preview_checkout,
    confirm_checkout,
]


def run_agent(prompt: str):
    """Initialize and run the LangGraph ReAct agent."""
    
    if not os.getenv("GOOGLE_API_KEY"):
        console.print("[red]Error: GOOGLE_API_KEY environment variable is not set.[/red]")
        console.print("Please set it to run the LangGraph agent: [bold]set GOOGLE_API_KEY=your-key[/bold]")
        sys.exit(1)

    console.print(Panel(
        f"[bold]LangGraph AI Buyer Agent[/bold]\n"
        f"Goal: {prompt}\n"
        f"Server: {BASE_URL}",
        title="🤖 Agentic Commerce",
        border_style="blue",
    ))

    # Initialize the LLM (Gemini)
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    
    # Create the ReAct agent graph
    from langchain.agents import create_agent
    # Actually, the modern langgraph import is still from langgraph.prebuilt import create_react_agent for graphs, but the warning said to use langchain.agents. Let me just suppress the warning or use the right import.
    from langgraph.prebuilt import create_react_agent
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    agent_executor = create_react_agent(llm, tools)

    console.print("\n[bold cyan]═══ Agent Execution ═══[/bold cyan]")
    
    # Stream events from the agent
    for event in agent_executor.stream(
        {"messages": [("user", prompt)]}, 
        stream_mode="values"
    ):
        message = event["messages"][-1]
        
        # Format the output beautifully using rich
        if message.type == "ai":
            if getattr(message, "tool_calls", None):
                for tc in message.tool_calls:
                    console.print(f"[magenta]🛠️  Calling Tool:[/magenta] {tc['name']} {tc['args']}")
            else:
                console.print(f"\n[green]🤖 Agent:[/green] {message.content}")
        
        elif message.type == "tool":
            # For tool responses, truncate if they are too long
            content = message.content
            if len(content) > 300:
                content = content[:300] + "... [truncated]"
            console.print(f"[dim]🔧 Tool Response ([/dim]{message.name}[dim]):[/dim] {content}")

    console.print("\n[bold green]✅ Agent execution completed![/bold green]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LangGraph AI Buyer Agent")
    parser.add_argument("prompt", type=str, nargs="?", 
                        default="I have a budget of Rs 120,000. Please search for a Pixel 9 (without the word phone) and a charger, create a cart, add them, apply any relevant campaigns you can find, and confirm the checkout.",
                        help="The shopping goal for the agent.")
    args = parser.parse_args()

    run_agent(args.prompt)
