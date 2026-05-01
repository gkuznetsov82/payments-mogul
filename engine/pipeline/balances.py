"""ContainerBalanceStore — per-container running balances (spec 40 §Container balance handling).

Scope (v4):
- Opening balances seeded from `pipeline_role_bindings.value_container_balances`.
- Balance updates are applied on resolved value date (spec 40: "Balance updates
  are applied on resolved value date"). To keep arithmetic simple in this
  prototype iteration we maintain two structures per container:
    current_balance     -> sum of all posted deltas whose value_date <= today
    scheduled_deltas    -> list of (value_date, amount) pairs not yet applied
  Each tick, the executor calls `apply_due_deltas(simulation_date)` which
  promotes scheduled deltas whose value_date <= simulation_date into the
  current balance.
- Non-sink products enforce current_balance + delta >= 0 on credit-to-source
  (`reserve_and_debit`). Sink products allow negative current balances.
- All-or-nothing: `try_debit` returns (executed, reason); no partial path.

Determinism: iteration order is by container key insertion. The executor always
writes in a deterministic order (profile iteration is sorted) so opening-balance
seeding + scheduled-delta appending are replayable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date_t
from typing import Iterable, Optional


@dataclass
class _Container:
    product_id: str
    container_ref: str
    path: str
    currency: str
    is_sink: bool
    current_balance: float = 0.0
    # Spec 52 §Container balance visibility contract: authoritative opening
    # balance is preserved (separate from current_balance) so snapshot
    # consumers can present an authoritative current vs opening view alongside
    # movement-derived diagnostics (spec 60 §View D).
    opening_balance: float = 0.0
    # Pending deltas scheduled for a future value date. Applied on ticks where
    # simulation_date >= value_date. Stored as list; sorted on every append to
    # keep earliest-date promotion deterministic.
    scheduled_deltas: list[tuple[_date_t, float, str]] = field(default_factory=list)
    # Running sum of scheduled deltas that would raise this container above /
    # below the current balance. Used for projection only.
    scheduled_total: float = 0.0


class InsufficientFundsError(Exception):
    """Raised when a non-sink debit would drop below zero."""

    def __init__(self, container_ref: str, product_id: str,
                 available: float, requested: float) -> None:
        self.container_ref = container_ref
        self.product_id = product_id
        self.available = available
        self.requested = requested
        super().__init__(
            f"insufficient funds on container {container_ref!r} "
            f"(product {product_id!r}): available={available:.2f}, requested={requested:.2f}"
        )


class ContainerBalanceStore:
    """In-memory balance book keyed by (product_id, container_ref)."""

    def __init__(self) -> None:
        self._containers: dict[tuple[str, str], _Container] = {}

    # ------------------------------------------------------------------ registration

    def register(self,
                  product_id: str,
                  container_ref: str,
                  path: str,
                  currency: str,
                  is_sink: bool,
                  opening_amount: float = 0.0) -> None:
        """Register a container; idempotent on (product_id, container_ref).

        Called by the engine after profile index is built; opening amounts
        come from `pipeline_role_bindings.value_container_balances`.
        """
        key = (product_id, container_ref)
        if key in self._containers:
            return  # preserve existing (reload path shouldn't wipe balance)
        self._containers[key] = _Container(
            product_id=product_id,
            container_ref=container_ref,
            path=path,
            currency=currency,
            is_sink=is_sink,
            current_balance=float(opening_amount),
            opening_balance=float(opening_amount),
        )

    # ------------------------------------------------------------------ balance ops

    def balance(self, product_id: str, container_ref: str) -> float:
        c = self._containers.get((product_id, container_ref))
        return c.current_balance if c is not None else 0.0

    def exists(self, product_id: str, container_ref: str) -> bool:
        return (product_id, container_ref) in self._containers

    def apply_due_deltas(self, simulation_date: _date_t) -> None:
        """Promote scheduled deltas whose value_date <= simulation_date into
        current_balance. Called at the start of each tick's pipeline stage."""
        for c in self._containers.values():
            if not c.scheduled_deltas:
                continue
            still_scheduled: list[tuple[_date_t, float, str]] = []
            for vd, amt, _reason in c.scheduled_deltas:
                if vd <= simulation_date:
                    c.current_balance += amt
                    c.scheduled_total -= amt
                else:
                    still_scheduled.append((vd, amt, _reason))
            c.scheduled_deltas = still_scheduled

    def schedule_delta(self,
                        product_id: str,
                        container_ref: str,
                        value_date: _date_t,
                        amount: float,
                        reason: str = "") -> None:
        """Schedule a future-dated delta. Non-sink products cannot have a
        scheduled debit that would drop current_balance below zero *at the
        time the delta lands* — but this prototype enforces the check only at
        apply-time for simplicity. For immediate effect, pass a value_date <=
        simulation_date and call apply_due_deltas.
        """
        c = self._containers.get((product_id, container_ref))
        if c is None:
            return
        c.scheduled_deltas.append((value_date, amount, reason))
        c.scheduled_deltas.sort(key=lambda t: t[0])
        c.scheduled_total += amount

    def try_debit(self,
                   product_id: str,
                   container_ref: str,
                   amount: float,
                   value_date: _date_t,
                   simulation_date: _date_t,
                   reason: str = "") -> tuple[bool, str]:
        """Attempt to debit `amount` from the container.

        If value_date <= simulation_date the debit is applied immediately;
        otherwise it is scheduled for future apply.

        Non-sink: insufficient funds (current_balance - amount < 0) is an
        all-or-nothing failure. Returns (False, "INSUFFICIENT_FUNDS").

        Missing container returns (False, "CONTAINER_NOT_REGISTERED").
        """
        c = self._containers.get((product_id, container_ref))
        if c is None:
            return False, "CONTAINER_NOT_REGISTERED"
        if value_date <= simulation_date:
            # Immediate debit.
            if not c.is_sink and (c.current_balance - amount) < 0:
                return False, "INSUFFICIENT_FUNDS"
            c.current_balance -= amount
            return True, "OK"
        # Future-dated debit. For non-sink, only accept if projected balance
        # at value_date would remain >= 0 (current - pending debits >= amount).
        if not c.is_sink:
            projected_at_vd = c.current_balance + c.scheduled_total
            if projected_at_vd - amount < 0:
                return False, "INSUFFICIENT_FUNDS_PROJECTED"
        c.scheduled_deltas.append((value_date, -amount, reason))
        c.scheduled_deltas.sort(key=lambda t: t[0])
        c.scheduled_total -= amount
        return True, "OK"

    def credit(self,
                product_id: str,
                container_ref: str,
                amount: float,
                value_date: _date_t,
                simulation_date: _date_t,
                reason: str = "") -> None:
        """Credit `amount` to the container, applied immediately if value_date
        <= simulation_date, else scheduled."""
        c = self._containers.get((product_id, container_ref))
        if c is None:
            return
        if value_date <= simulation_date:
            c.current_balance += amount
            return
        c.scheduled_deltas.append((value_date, amount, reason))
        c.scheduled_deltas.sort(key=lambda t: t[0])
        c.scheduled_total += amount

    # ------------------------------------------------------------------ snapshots

    def snapshot(self) -> list[dict]:
        """Return a deterministic snapshot of all container balances.

        Spec 52 §Container balance visibility contract: payload includes
        `current_balance` (authoritative), `opening_balance`, and
        `scheduled_total` for Accounts/Obligations diagnostics.
        """
        out: list[dict] = []
        for (pid, cref), c in sorted(self._containers.items()):
            out.append({
                "product_id": pid,
                "container_ref": cref,
                "path": c.path,
                "currency": c.currency,
                "is_sink": c.is_sink,
                "current_balance": round(c.current_balance, 6),
                "opening_balance": round(c.opening_balance, 6),
                "scheduled_total": round(c.scheduled_total, 6),
                "scheduled_count": len(c.scheduled_deltas),
            })
        return out

    def iter_containers(self) -> Iterable[_Container]:
        """Deterministic iteration (sorted by key)."""
        for _, c in sorted(self._containers.items()):
            yield c
