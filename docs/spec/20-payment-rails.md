# Payment Rails

**Status:** Draft

## Purpose

Domain model of the 4-party (and extended) payment network as implemented in the sim: who moves value, when, and how that ties to **daily** aggregate simulation.

**Cross-references:** pipeline and tick aggregation **`33-transaction-pipeline.md`**; fees **`21-fee-economics.md`**; corporate graph **`31-agents.md`**.

---

## Time grain

- **Fund transfers and settlement** semantics apply to activity **within a simulated day** (one **tick**). The pipeline resolves how intra-day stages roll up to **postings** for that day (**`33-transaction-pipeline.md`**).

---

## Contents (to complete)

- Parties: consumer, merchant, acquirer, issuer, scheme, optional agents
- Money and information flows (simplified timeline)
- Settlement and timing assumptions
- Chargebacks, reserves, fraud: in/out of scope for v1
- **Commercial vs control relationship** — Rails describe **who settles with whom** (e.g. **BIN sponsor**, processing agreements). That is **not** the same as **corporate control** (same economic group). Sponsor fees may be **intercompany** or **third-party** depending on the **institution graph**; see **`31-agents.md`** (consolidation and BIN sponsor example) and **`21-fee-economics.md`** for how fees post and net in group reporting.
