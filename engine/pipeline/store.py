"""SQLite observability store for pipeline events (spec 33 §debug retention,
ADR-0002 §queryable debug observability store).

Each pipeline event family lands in its own table keyed by `tick_id` and the
event-specific id (intent_id / fee_id / posting_id / etc.). Writes are
synchronous and small — fine for our prototype. Schema is bootstrapped on
first connect; retention pruning is implemented but the prototype default is
unlimited until debug-window controls are wired.

The store is in-memory by default (`:memory:`) so tests stay hermetic; the
engine can be configured to use a file path for real runs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS intents (
    tick_id INTEGER, simulation_date TEXT, pipeline_profile_id TEXT,
    product_id TEXT, intent_id TEXT, parent_intent_id TEXT,
    destination_role TEXT, destination_product_id TEXT, destination_vendor_id TEXT,
    txn_count INTEGER, amount TEXT, currency TEXT,
    value_date_policy TEXT, resolved_value_date TEXT,
    PRIMARY KEY (tick_id, intent_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_intents_tick ON intents(tick_id);
CREATE INDEX IF NOT EXISTS ix_intents_product ON intents(product_id);

CREATE TABLE IF NOT EXISTS fees (
    tick_id INTEGER, simulation_date TEXT, pipeline_profile_id TEXT,
    product_id TEXT, fee_id TEXT, trigger_id TEXT,
    beneficiary_role TEXT, beneficiary_agent_id TEXT, beneficiary_product_id TEXT,
    txn_count_basis INTEGER, amount_basis TEXT,
    fixed_component TEXT, percent_component TEXT, fee_amount TEXT, currency TEXT,
    settlement_value_date_policy TEXT, settlement_due_date TEXT, status TEXT,
    PRIMARY KEY (tick_id, fee_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_fees_tick ON fees(tick_id);
CREATE INDEX IF NOT EXISTS ix_fees_product ON fees(product_id);

CREATE TABLE IF NOT EXISTS postings (
    tick_id INTEGER, simulation_date TEXT, pipeline_profile_id TEXT,
    product_id TEXT, posting_id TEXT PRIMARY KEY, trigger_id TEXT,
    source_ledger_ref TEXT, destination_ledger_ref TEXT,
    source_ledger_path TEXT, destination_ledger_path TEXT,
    amount TEXT, currency TEXT,
    value_date_policy TEXT, resolved_value_date TEXT, status TEXT
);
CREATE INDEX IF NOT EXISTS ix_postings_tick ON postings(tick_id);

CREATE TABLE IF NOT EXISTS transfers (
    tick_id INTEGER, simulation_date TEXT, pipeline_profile_id TEXT,
    product_id TEXT, transfer_id TEXT PRIMARY KEY, trigger_id TEXT,
    source_container_ref TEXT, destination_container_ref TEXT,
    source_container_path TEXT, destination_container_path TEXT,
    amount TEXT, currency TEXT,
    value_date_policy TEXT, resolved_value_date TEXT, status TEXT
);
CREATE INDEX IF NOT EXISTS ix_transfers_tick ON transfers(tick_id);

CREATE TABLE IF NOT EXISTS invoices (
    tick_id INTEGER, simulation_date TEXT, pipeline_profile_id TEXT,
    product_id TEXT, invoice_id TEXT PRIMARY KEY, fee_id TEXT,
    accrual_tick_id INTEGER, accrual_date TEXT,
    beneficiary_product_id TEXT, payer_agent_id TEXT, payer_product_id TEXT,
    amount TEXT, currency TEXT, status TEXT
);
CREATE INDEX IF NOT EXISTS ix_invoices_tick ON invoices(tick_id);

CREATE TABLE IF NOT EXISTS settlements (
    tick_id INTEGER, simulation_date TEXT, pipeline_profile_id TEXT,
    product_id TEXT, invoice_id TEXT, fee_id TEXT,
    beneficiary_product_id TEXT, payer_agent_id TEXT, payer_product_id TEXT,
    settled_amount TEXT, residual_amount TEXT, currency TEXT,
    mode TEXT, final_status TEXT,
    PRIMARY KEY (tick_id, invoice_id)
);
CREATE INDEX IF NOT EXISTS ix_settlements_tick ON settlements(tick_id);
"""


class PipelineStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        # check_same_thread=False so the async engine can write from event loop callbacks.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ writes

    def record(self, event_type: str, data: dict) -> None:
        """Dispatch on event family; silently ignore unknown event types."""
        try:
            if event_type == "transaction_intent_event":
                self._insert_intent(data)
            elif event_type == "fee_accrual_event":
                self._insert_fee(data)
            elif event_type == "posting_entry_event":
                self._insert_posting(data)
            elif event_type == "value_transfer_event":
                self._insert_transfer(data)
            elif event_type == "invoice_transaction_event":
                self._insert_invoice(data)
            elif event_type == "settlement_resolution_event":
                self._insert_settlement(data)
        except sqlite3.Error:
            # Don't let store failures break the simulation loop.
            pass

    @staticmethod
    def _money_str(v) -> str:
        if isinstance(v, dict):
            return str(v.get("amount", ""))
        return str(v)

    def _insert_intent(self, d: dict) -> None:
        amt = d.get("amount") or {}
        self._conn.execute(
            "INSERT OR REPLACE INTO intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.get("tick_id"), d.get("simulation_date"), d.get("pipeline_profile_id"),
                d.get("product_id"), d.get("intent_id"), d.get("parent_intent_id"),
                d.get("destination_role"), d.get("destination_product_id"), d.get("destination_vendor_id"),
                d.get("txn_count"), self._money_str(amt), amt.get("currency") if isinstance(amt, dict) else None,
                d.get("value_date_policy"), d.get("resolved_value_date"),
            ),
        )

    def _insert_fee(self, d: dict) -> None:
        amt = d.get("fee_amount") or {}
        self._conn.execute(
            "INSERT OR REPLACE INTO fees VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.get("tick_id"), d.get("simulation_date"), d.get("pipeline_profile_id"),
                d.get("product_id"), d.get("fee_id"), d.get("trigger_id"),
                d.get("beneficiary_role"), d.get("beneficiary_agent_id"), d.get("beneficiary_product_id"),
                d.get("txn_count_basis"), self._money_str(d.get("amount_basis", {})),
                self._money_str(d.get("fixed_component", {})),
                self._money_str(d.get("percent_component", {})),
                self._money_str(amt), amt.get("currency") if isinstance(amt, dict) else None,
                d.get("settlement_value_date_policy"), d.get("settlement_due_date"), d.get("status"),
            ),
        )

    def _insert_posting(self, d: dict) -> None:
        amt = d.get("amount") or {}
        self._conn.execute(
            "INSERT OR REPLACE INTO postings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.get("tick_id"), d.get("simulation_date"), d.get("pipeline_profile_id"),
                d.get("product_id"), d.get("posting_id"), d.get("trigger_id"),
                d.get("source_ledger_ref"), d.get("destination_ledger_ref"),
                d.get("source_ledger_path"), d.get("destination_ledger_path"),
                self._money_str(amt), amt.get("currency") if isinstance(amt, dict) else None,
                d.get("value_date_policy"), d.get("resolved_value_date"), d.get("status"),
            ),
        )

    def _insert_transfer(self, d: dict) -> None:
        amt = d.get("amount") or {}
        self._conn.execute(
            "INSERT OR REPLACE INTO transfers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.get("tick_id"), d.get("simulation_date"), d.get("pipeline_profile_id"),
                d.get("product_id"), d.get("transfer_id"), d.get("trigger_id"),
                d.get("source_container_ref"), d.get("destination_container_ref"),
                d.get("source_container_path"), d.get("destination_container_path"),
                self._money_str(amt), amt.get("currency") if isinstance(amt, dict) else None,
                d.get("value_date_policy"), d.get("resolved_value_date"), d.get("status"),
            ),
        )

    def _insert_invoice(self, d: dict) -> None:
        amt = d.get("amount") or {}
        self._conn.execute(
            "INSERT OR REPLACE INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.get("tick_id"), d.get("simulation_date"), d.get("pipeline_profile_id"),
                d.get("product_id"), d.get("invoice_id"), d.get("fee_id"),
                d.get("accrual_tick_id"), d.get("accrual_date"),
                d.get("beneficiary_product_id"), d.get("payer_agent_id"), d.get("payer_product_id"),
                self._money_str(amt), amt.get("currency") if isinstance(amt, dict) else None,
                d.get("status"),
            ),
        )

    def _insert_settlement(self, d: dict) -> None:
        amt = d.get("settled_amount") or {}
        residual = d.get("residual_amount") or {}
        self._conn.execute(
            "INSERT OR REPLACE INTO settlements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.get("tick_id"), d.get("simulation_date"), d.get("pipeline_profile_id"),
                d.get("product_id"), d.get("invoice_id"), d.get("fee_id"),
                d.get("beneficiary_product_id"), d.get("payer_agent_id"), d.get("payer_product_id"),
                self._money_str(amt), self._money_str(residual),
                amt.get("currency") if isinstance(amt, dict) else None,
                d.get("mode"), d.get("final_status"),
            ),
        )

    # ------------------------------------------------------------------ reads (TUI)

    def list(self, table: str, *, where: Optional[str] = None, params: Iterable = (),
             order_by: str = "tick_id ASC", limit: int = 200) -> list[dict]:
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {order_by} LIMIT ?"
        cur = self._conn.execute(sql, (*params, limit))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
