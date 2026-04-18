"""PaymentsMogulModel — Mesa Model that owns agents and drives the tick."""

from __future__ import annotations

import mesa

from engine.agents.pop import ActionOutcome, GenericPop
from engine.agents.vendor import VendorAgent
from engine.config.models import PrototypeConfig


class PaymentsMogulModel(mesa.Model):
    """Pure simulation model.  No async, no I/O — only Mesa scheduling logic."""

    def __init__(self, cfg: PrototypeConfig) -> None:
        super().__init__(rng=cfg.scenario.seed)  # rng= is the Mesa 3.5+ API; seed= is deprecated
        self.cfg = cfg
        self._tick_outcomes: list[ActionOutcome] = []

        # Domain-keyed lookups (agents also live in self.agents AgentSet)
        self.vendors: dict[str, VendorAgent] = {}
        self.pops: dict[str, GenericPop] = {}

        # Create agents in stable sorted order so registration order is deterministic
        for vc in sorted(cfg.world.vendor_agents, key=lambda v: v.vendor_id):
            agent = VendorAgent(self, vc, cfg.control_defaults)
            self.vendors[vc.vendor_id] = agent

        for pc in sorted(cfg.world.pops, key=lambda p: p.pop_id):
            agent = GenericPop(self, pc)
            self.pops[pc.pop_id] = agent

    def record_outcome(self, outcome: ActionOutcome) -> None:
        """Called by agents during their Onboard/Transact steps."""
        self._tick_outcomes.append(outcome)

    def step(self) -> None:
        """Run one simulated day.

        Phase order (spec 30-architecture, 31-agents, 33-transaction-pipeline):
          1. Onboard() on all agents in stable sorted order
          2. Transact() on all agents in stable sorted order

        Mesa's step() contract is void; outcomes accumulate in self._tick_outcomes
        and are read by the engine immediately after calling step().
        model.random (Python random.Random seeded at init) is the sole RNG source.
        """
        self._tick_outcomes = []

        # Onboard phase — vendors are noop; pops generate requests
        for vendor in sorted(self.vendors.values(), key=lambda a: a.vendor_id):
            vendor.Onboard()
        for pop in sorted(self.pops.values(), key=lambda a: a.pop_id):
            pop.Onboard()

        # Transact phase
        for vendor in sorted(self.vendors.values(), key=lambda a: a.vendor_id):
            vendor.Transact()
        for pop in sorted(self.pops.values(), key=lambda a: a.pop_id):
            pop.Transact()

    def snapshot(self) -> dict:
        """Build a rounded snapshot per spec 40/52 numeric typing. Agents keep
        float precision internally; only the emitted snapshot is coerced."""
        sim = self.cfg.simulation
        cm = sim.count_rounding_mode
        adp = sim.amount_scale_dp
        am = sim.amount_rounding_mode
        return {
            "vendors": {vid: v.snapshot(cm, adp, am) for vid, v in self.vendors.items()},
            "pops": {pid: p.snapshot(cm, adp, am) for pid, p in self.pops.items()},
        }
