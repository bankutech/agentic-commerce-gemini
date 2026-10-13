"""SQLite-backed persistence.

Every service (carts, orders, campaign usage counts, product stock)
keeps its live working state in memory for speed, but every mutation
is write-through persisted here. On startup, each service reloads its
state from SQLite before serving traffic. This means a server restart
does not lose carts, orders, discount usage counts, or stock levels —
the single biggest gap between a "demo" and something a merchant could
actually run.

Deliberately NOT an ORM: a single generic JSON key-value table is
enough for this system's access patterns (load-all-on-boot,
point-writes on mutation) and keeps every service's persistence code
to 2-3 lines instead of a bespoke schema per model.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "agentic_commerce.db")

_connection: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return the process-wide SQLite connection, creating it on first use."""
    global _connection
    if _connection is None:
        path = db_path or DB_PATH
        _connection = sqlite3.connect(path, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        logger.info("SQLite persistence: connected to %s", path)
    return _connection


def init_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = get_db(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kv_store (
            namespace  TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (namespace, key)
        );
        """
    )
    conn.commit()
    return conn


def reset_db(db_path: Optional[str] = None) -> None:
    """Close and clear the cached connection — used by tests to get a fresh DB."""
    global _connection
    if _connection is not None:
        _connection.close()
    _connection = None


class SqliteStore:
    """A namespaced JSON key-value store backed by the shared SQLite connection.

    Each service gets its own namespace (e.g. "carts", "orders") so
    unrelated data never collides on key names.
    """

    def __init__(self, namespace: str, conn: Optional[sqlite3.Connection] = None):
        self._ns = namespace
        self._conn = conn or get_db()

    def set(self, key: str, value: dict[str, Any]) -> None:
        with _lock:
            self._conn.execute(
                """
                INSERT INTO kv_store (namespace, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (self._ns, key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def get(self, key: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT value FROM kv_store WHERE namespace = ? AND key = ?",
            (self._ns, key),
        ).fetchone()
        return json.loads(row["value"]) if row else None

    def get_all(self) -> dict[str, dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT key, value FROM kv_store WHERE namespace = ?",
            (self._ns,),
        ).fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def delete(self, key: str) -> None:
        with _lock:
            self._conn.execute(
                "DELETE FROM kv_store WHERE namespace = ? AND key = ?",
                (self._ns, key),
            )
            self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM kv_store WHERE namespace = ?",
            (self._ns,),
        ).fetchone()
        return row["c"] if row else 0
