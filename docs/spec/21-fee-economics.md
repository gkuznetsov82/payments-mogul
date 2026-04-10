# Fee Economics

**Status:** Draft

## Purpose

Fee types and constraints valid in simulation (including "laws of physics" like interchange vs MDR), and how fee outcomes connect to **aggregate** pipeline output and **ledger postings**.

**Cross-references:** pipeline and buckets **`33-transaction-pipeline.md`**; rails and settlement **`20-payment-rails.md`**; group consolidation **`31-agents.md`**.

---

## Fees from aggregate activity

- **Fee calculations** apply to **aggregate transaction intents and buckets** produced within a tick (**`33-transaction-pipeline.md`**), not to per-cardholder rows in normal play.
- Results post as **aggregated accounting lines** on institutional **P&L** (and balance sheet where relevant) and to **pop sinks** when modeled. **Intercompany elimination** and group reporting rules remain as specified in **`31-agents.md`** and still **to complete** in this chapter for numeric alignment.

---

## Contents (to complete)

- Fee taxonomy (interchange, assessment, markup, MDR, etc.)
- Pass-through vs bundled pricing
- Caps, floors, and scheme rules as enforced constraints
- **Intercompany elimination** and numeric alignment with **`31-agents.md`** (BIN sponsor fees, transfer pricing)
- Variable naming and formula reference (prose + symbols; implementation derives)
