# Payment Rails

**Status:** Draft

## Purpose

Domain model of the 4-party (and extended) payment network as implemented in the sim.

## Contents (to complete)

- Parties: consumer, merchant, acquirer, issuer, scheme, optional agents
- Money and information flows (simplified timeline)
- Settlement and timing assumptions
- Chargebacks, reserves, fraud: in/out of scope for v1
- **Commercial vs control relationship** — Rails describe **who settles with whom** (e.g. **BIN sponsor**, processing agreements). That is **not** the same as **corporate control** (same economic group). Sponsor fees may be **intercompany** or **third-party** depending on the **institution graph**; see **`31-agents.md`** (consolidation and BIN sponsor example) and **`21-fee-economics.md`** for how fees post and net in group reporting.
