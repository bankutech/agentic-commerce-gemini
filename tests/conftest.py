"""Shared pytest fixtures.

Sets DATABASE_PATH and AUDIT_LOG_PATH to a fresh temp location BEFORE
`main` is imported anywhere, so the test suite never touches a
developer's real agentic_commerce.db / audit_log.jsonl, and each test
run starts from a clean, isolated state.
"""
import os
import tempfile
import uuid

_tmp_dir = tempfile.mkdtemp(prefix="agentic_commerce_test_")
os.environ["DATABASE_PATH"] = os.path.join(_tmp_dir, f"test_{uuid.uuid4().hex[:8]}.db")
os.environ["AUDIT_LOG_PATH"] = os.path.join(_tmp_dir, "test_audit.jsonl")
# No real Razorpay keys in CI — this keeps the app in "keys not configured"
# mode, which is itself one of the graceful-failure paths under test.
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_REPLACE_ME")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "REPLACE_ME")
os.environ.pop("GOOGLE_API_KEY", None)  # force rule-based recommendation fallback in tests

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def new_cart(client):
    """Create a fresh cart with a generous budget. Returns the cart_id."""
    resp = client.post(
        "/cart",
        json={"agent_id": "pytest_agent", "max_budget_paise": 10_000_000},
    )
    assert resp.status_code == 200
    return resp.json()["cart_id"]
