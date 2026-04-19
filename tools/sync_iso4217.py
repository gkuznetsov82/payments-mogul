r"""Sync the local ISO 4217 currency catalog from SIX List One + List Three.

SIX (the ISO 4217 maintenance agency) publishes two XML artifacts:
  * List One — currently active currencies + funds.
  * List Three — historic currencies (withdrawn / replaced).

This script downloads both, merges them, normalizes to the project schema used
by `currency_catalog.local_file`, and writes a deterministic YAML file (sorted
by code, stable layout).

Network fetch uses httpx (lazy import). XML parsing uses stdlib only so this
script is unit-testable without network access — `parse_list_one(bytes)` and
`parse_list_three(bytes)` accept raw XML and return list[dict].

Usage:
    # Refresh into the default reference path (rewrites file)
    python tools/sync_iso4217.py

    # Custom output path:
    python tools/sync_iso4217.py --output configs/reference/currency_catalog_iso4217.yaml

    # Dry-run: don't write anything; only log added/changed/removed entries vs.
    # the existing target file:
    python tools/sync_iso4217.py --dry-run

    # Use local XML files instead of network (handy for CI fixtures):
    python tools/sync_iso4217.py --list-one ./list-one.xml --list-three ./list-three.xml

PowerShell wrapper (recommended for Windows users):
    .\tools\sync_iso4217.ps1 [-DryRun]
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from calendar import monthrange as _monthrange
from datetime import date as _date_t
from pathlib import Path
from typing import Iterable

import yaml


DEFAULT_LIST_ONE_URL = (
    "https://www.six-group.com/dam/download/financial-information/data-center/"
    "iso-currrency/lists/list-one.xml"
)
DEFAULT_LIST_THREE_URL = (
    "https://www.six-group.com/dam/download/financial-information/data-center/"
    "iso-currrency/lists/list-three.xml"
)
DEFAULT_OUTPUT = Path("configs/reference/currency_catalog_iso4217.yaml")


# --------------------------------------------------------------------------- parsing

def parse_list_one(xml_bytes: bytes) -> list[dict]:
    """Parse SIX List One (current currencies). Returns list of dicts:
    {code, numeric_code, name, minor_unit, active_from?}."""
    root = ET.fromstring(xml_bytes)
    out: dict[str, dict] = {}
    for entry in root.iter("CcyNtry"):
        code = (entry.findtext("Ccy") or "").strip()
        if not code:
            continue
        if code in out:
            continue  # already seen — same currency shared across countries
        minor_text = (entry.findtext("CcyMnrUnts") or "").strip()
        try:
            minor_unit = int(minor_text)
        except ValueError:
            # "N.A." for non-decimal funds (e.g. XAU). Skip those for the project schema.
            continue
        out[code] = {
            "code": code,
            "numeric_code": (entry.findtext("CcyNbr") or "").strip(),
            "name": (entry.findtext("CcyNm") or "").strip(),
            "minor_unit": minor_unit,
        }
    return sorted(out.values(), key=lambda d: d["code"])


def parse_list_three(xml_bytes: bytes) -> list[dict]:
    """Parse SIX List Three (historical currencies). Returns list of dicts with
    `active_to` populated from WthdrwlDt where available.

    Robust to malformed entries: if a single record's WthdrwlDt can't be parsed,
    that record's `active_to` is set to None and the run continues. Per-entry
    failures must never crash the whole sync.
    """
    root = ET.fromstring(xml_bytes)
    out: dict[str, dict] = {}
    for entry in root.iter("HstrcCcyNtry"):
        code = (entry.findtext("Ccy") or "").strip()
        if not code:
            continue
        # SIX may list a code with multiple withdrawal dates across countries;
        # keep the most recent withdrawal date as the canonical end-of-life.
        withdrew = (entry.findtext("WthdrwlDt") or "").strip()
        try:
            active_to = _normalize_withdrawn_date(withdrew)
        except Exception:
            active_to = None
        existing = out.get(code)
        if existing and existing.get("active_to") and active_to:
            try:
                if active_to <= existing["active_to"]:
                    continue
            except TypeError:
                pass
        out[code] = {
            "code": code,
            "numeric_code": (entry.findtext("CcyNbr") or "").strip(),
            "name": (entry.findtext("CcyNm") or "").strip(),
            "minor_unit": _safe_minor(entry.findtext("CcyMnrUnts")),
            "active_to": active_to,
        }
    return sorted(out.values(), key=lambda d: d["code"])


def _safe_minor(text: str | None) -> int:
    try:
        return int((text or "").strip())
    except ValueError:
        return 0  # historical entries often lack minor_unit; default to 0


_YEAR_RE = re.compile(r"^\d{4}$")
_MONTH_RE = re.compile(r"^(?:0?[1-9]|1[0-2])$")


def _normalize_withdrawn_date(s: str) -> str | None:
    """Normalize SIX `WthdrwlDt` to a `YYYY-MM-DD` string.

    SIX is inconsistent across List Three entries. Observed shapes:
      - "" (empty) -> None
      - "YYYY"             -> end-of-year
      - "YYYY-MM"          -> end-of-month
      - "MM-YYYY"          -> end-of-month (year is the 4-digit part)
      - "YYYY-MM-DD"       -> exact date, passthrough
      - "YYYY-MM, YYYY-MM" -> first segment used
    Anything we can't confidently parse returns None (the caller treats the
    entry as having unknown active_to; it is NOT a crash).
    """
    if not s:
        return None
    # Take only the first segment if SIX concatenates multiple dates.
    s = s.split(",")[0].split(";")[0].strip()
    if not s:
        return None

    parts = s.split("-")

    # Single-token "YYYY"
    if len(parts) == 1:
        if _YEAR_RE.match(parts[0]):
            return f"{parts[0]}-12-31"
        return None

    # Two-token forms: figure out which side is the 4-digit year.
    if len(parts) == 2:
        a, b = parts[0].strip(), parts[1].strip()
        if _YEAR_RE.match(a) and _MONTH_RE.match(b):
            year, month = int(a), int(b)
        elif _YEAR_RE.match(b) and _MONTH_RE.match(a):
            year, month = int(b), int(a)
        else:
            return None
        try:
            last = _monthrange(year, month)[1]
        except Exception:
            return None
        return f"{year:04d}-{month:02d}-{last:02d}"

    # Three-token form: assume YYYY-MM-DD; validate before passthrough.
    if len(parts) == 3:
        try:
            return _date_t.fromisoformat(s).isoformat()
        except ValueError:
            return None

    return None


# --------------------------------------------------------------------------- merge

def merge(current: list[dict], historical: list[dict]) -> list[dict]:
    """Combine current + historical entries, deduped by `code`. Current entries
    win on metadata; historical entries contribute `active_to` for any code only
    present in historical (or supplement active_to where current is missing it).
    Output is sorted by code for deterministic file output."""
    by_code: dict[str, dict] = {}
    for c in current:
        by_code[c["code"]] = dict(c)
    for h in historical:
        if h["code"] in by_code:
            # Code is still active per List One; ignore historical metadata.
            continue
        by_code[h["code"]] = dict(h)
    return sorted(by_code.values(), key=lambda d: d["code"])


# --------------------------------------------------------------------------- output

def render_yaml(entries: list[dict],
                *,
                catalog_version: str = "iso4217-six-sync-v1") -> str:
    """Render to deterministic YAML (sorted, stable scalar order)."""
    body = {
        "catalog_version": catalog_version,
        "source": {
            "provider": "SIX-ISO4217",
            "list_one_url": DEFAULT_LIST_ONE_URL,
            "list_three_url": DEFAULT_LIST_THREE_URL,
            "generated_at": _date_t.today().isoformat(),
        },
        "currencies": [
            {k: v for k, v in entry.items() if v is not None}
            for entry in entries
        ],
    }
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True)


def diff_against_existing(new_entries: list[dict],
                          existing_path: Path) -> tuple[list[str], list[str], list[str]]:
    """Compute (added, changed, removed) currency code lists vs. the on-disk file."""
    if not existing_path.exists():
        return ([e["code"] for e in new_entries], [], [])
    try:
        prev = yaml.safe_load(existing_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ([e["code"] for e in new_entries], [], [])
    prev_by_code = {c["code"]: c for c in (prev.get("currencies") or [])}
    new_by_code = {c["code"]: c for c in new_entries}
    added = sorted(set(new_by_code) - set(prev_by_code))
    removed = sorted(set(prev_by_code) - set(new_by_code))
    changed = sorted(
        code for code in (set(new_by_code) & set(prev_by_code))
        if {k: prev_by_code[code].get(k) for k in ("name", "numeric_code", "minor_unit", "active_from", "active_to")}
        != {k: new_by_code[code].get(k) for k in ("name", "numeric_code", "minor_unit", "active_from", "active_to")}
    )
    return (added, changed, removed)


# --------------------------------------------------------------------------- CLI

def _fetch(url: str) -> bytes:
    try:
        import httpx
    except ImportError:
        sys.exit("httpx is required to fetch SIX lists; pip install httpx")
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content


def _read_xml(source: str | Path | None, default_url: str) -> bytes:
    if source is None:
        return _fetch(default_url)
    p = Path(source)
    if p.exists():
        return p.read_bytes()
    # Treat as URL otherwise.
    return _fetch(str(source))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync local ISO 4217 catalog from SIX")
    parser.add_argument("--list-one", default=None,
                        help="Path or URL for SIX List One XML (default: SIX URL)")
    parser.add_argument("--list-three", default=None,
                        help="Path or URL for SIX List Three XML (default: SIX URL)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Output YAML path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write; only log diff vs. existing output file")
    args = parser.parse_args(argv)

    print(f"[iso-sync] fetching List One ...")
    one_xml = _read_xml(args.list_one, DEFAULT_LIST_ONE_URL)
    print(f"[iso-sync] fetching List Three ...")
    three_xml = _read_xml(args.list_three, DEFAULT_LIST_THREE_URL)

    current = parse_list_one(one_xml)
    historical = parse_list_three(three_xml)
    merged = merge(current, historical)
    print(f"[iso-sync] parsed {len(current)} current, {len(historical)} historical -> {len(merged)} merged entries")

    out_path = Path(args.output)
    added, changed, removed = diff_against_existing(merged, out_path)
    if added:
        print(f"[iso-sync] added ({len(added)}): {', '.join(added)}")
    if changed:
        print(f"[iso-sync] changed ({len(changed)}): {', '.join(changed)}")
    if removed:
        print(f"[iso-sync] removed ({len(removed)}): {', '.join(removed)}")
    if not (added or changed or removed):
        print("[iso-sync] no changes")

    if args.dry_run:
        print("[iso-sync] dry-run: not writing")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_yaml(merged), encoding="utf-8")
    print(f"[iso-sync] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
