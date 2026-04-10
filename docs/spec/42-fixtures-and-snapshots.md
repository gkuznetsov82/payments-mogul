# Fixtures & Snapshots

**Status:** Draft

## Purpose

Golden runs and regression artifacts for economics and engine behavior.

**Cross-references:** end-of-day aggregates **`33-transaction-pipeline.md`**, **`30-architecture.md`**; determinism **`30-architecture.md`**.

---

## What CI should compare (normal play)

- Regression tests should anchor on **end-of-tick** (end-of-day) **aggregates**: key ledger balances, posting totals, KPI buckets, and scenario counters—not on **full debug bucket logs** (optional **smoke** tests may enable a **short** debug window for pipeline tests).

---

## Contents (to complete)

- Snapshot schema (time step, key aggregates, sample agent states)
- How to record and diff snapshots
- CI expectations (which fixtures run on each PR)
- Optional: separate **debug-window** fixture profile with capped **N** ticks
