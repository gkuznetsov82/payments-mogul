"""Unit tests for tools/sync_iso4217.py — parsing only, no network.

Uses synthetic XML fixtures patterned after SIX List One / List Three.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as pyyaml

from tools.sync_iso4217 import (
    diff_against_existing,
    merge,
    parse_list_one,
    parse_list_three,
    render_yaml,
)


LIST_ONE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ISO_4217 Pblshd="2026-01-01">
  <CcyTbl>
    <CcyNtry>
      <CtryNm>UNITED STATES OF AMERICA</CtryNm>
      <CcyNm>US Dollar</CcyNm>
      <Ccy>USD</Ccy>
      <CcyNbr>840</CcyNbr>
      <CcyMnrUnts>2</CcyMnrUnts>
    </CcyNtry>
    <CcyNtry>
      <CtryNm>EUROPEAN UNION</CtryNm>
      <CcyNm>Euro</CcyNm>
      <Ccy>EUR</Ccy>
      <CcyNbr>978</CcyNbr>
      <CcyMnrUnts>2</CcyMnrUnts>
    </CcyNtry>
    <CcyNtry>
      <CtryNm>JAPAN</CtryNm>
      <CcyNm>Yen</CcyNm>
      <Ccy>JPY</Ccy>
      <CcyNbr>392</CcyNbr>
      <CcyMnrUnts>0</CcyMnrUnts>
    </CcyNtry>
    <CcyNtry>
      <CtryNm>SOMEWHERE</CtryNm>
      <CcyNm>Gold</CcyNm>
      <Ccy>XAU</Ccy>
      <CcyNbr>959</CcyNbr>
      <CcyMnrUnts>N.A.</CcyMnrUnts>
    </CcyNtry>
    <CcyNtry>
      <CtryNm>UNITED STATES (THE)</CtryNm>
      <CcyNm>US Dollar</CcyNm>
      <Ccy>USD</Ccy>
      <CcyNbr>840</CcyNbr>
      <CcyMnrUnts>2</CcyMnrUnts>
    </CcyNtry>
  </CcyTbl>
</ISO_4217>"""

LIST_THREE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ISO_4217 Pblshd="2026-01-01">
  <HstrcCcyTbl>
    <HstrcCcyNtry>
      <CtryNm>BULGARIA</CtryNm>
      <CcyNm>Lev A/52</CcyNm>
      <Ccy>BGL</Ccy>
      <CcyNbr>100</CcyNbr>
      <WthdrwlDt>1999-07</WthdrwlDt>
    </HstrcCcyNtry>
    <HstrcCcyNtry>
      <CtryNm>EAST TIMOR</CtryNm>
      <CcyNm>Timor Escudo</CcyNm>
      <Ccy>TPE</Ccy>
      <CcyNbr>626</CcyNbr>
      <WthdrwlDt>2002</WthdrwlDt>
    </HstrcCcyNtry>
    <HstrcCcyNtry>
      <CtryNm>SOMEWHERE</CtryNm>
      <CcyNm>Old Real</CcyNm>
      <Ccy>BRR</Ccy>
      <CcyNbr>987</CcyNbr>
      <WthdrwlDt>1994-08-01</WthdrwlDt>
    </HstrcCcyNtry>
  </HstrcCcyTbl>
</ISO_4217>"""


def test_parse_list_one_skips_na_minor_units():
    entries = parse_list_one(LIST_ONE_XML)
    codes = {e["code"] for e in entries}
    assert "USD" in codes and "EUR" in codes and "JPY" in codes
    assert "XAU" not in codes  # CcyMnrUnts=N.A. → skipped per project schema


def test_parse_list_one_dedupes_repeated_codes():
    entries = parse_list_one(LIST_ONE_XML)
    usd_entries = [e for e in entries if e["code"] == "USD"]
    assert len(usd_entries) == 1
    assert usd_entries[0]["minor_unit"] == 2
    assert usd_entries[0]["numeric_code"] == "840"


def test_parse_list_three_normalizes_withdrawal_dates():
    entries = parse_list_three(LIST_THREE_XML)
    by_code = {e["code"]: e for e in entries}
    assert by_code["BGL"]["active_to"] == "1999-07-31"      # YYYY-MM → end of month
    assert by_code["TPE"]["active_to"] == "2002-12-31"      # YYYY → end of year
    assert by_code["BRR"]["active_to"] == "1994-08-01"      # full date preserved


def test_parse_list_three_handles_mm_yyyy_form():
    """SIX List Three sometimes writes WthdrwlDt as MM-YYYY (month-year, not year-month)."""
    xml = b"""<?xml version="1.0"?>
<ISO_4217>
  <HstrcCcyTbl>
    <HstrcCcyNtry>
      <Ccy>XYZ</Ccy>
      <CcyNbr>999</CcyNbr>
      <CcyNm>Foo</CcyNm>
      <CcyMnrUnts>2</CcyMnrUnts>
      <WthdrwlDt>12-1990</WthdrwlDt>
    </HstrcCcyNtry>
  </HstrcCcyTbl>
</ISO_4217>"""
    entries = parse_list_three(xml)
    assert entries[0]["active_to"] == "1990-12-31"


def test_parse_list_three_skips_unparseable_withdrawal_date_without_crashing():
    """Any single bad WthdrwlDt must NOT crash the whole sync — entry survives with active_to=None."""
    xml = b"""<?xml version="1.0"?>
<ISO_4217>
  <HstrcCcyTbl>
    <HstrcCcyNtry>
      <Ccy>JNK</Ccy>
      <CcyNbr>000</CcyNbr>
      <CcyNm>Junk</CcyNm>
      <CcyMnrUnts>2</CcyMnrUnts>
      <WthdrwlDt>not-a-date-at-all</WthdrwlDt>
    </HstrcCcyNtry>
  </HstrcCcyTbl>
</ISO_4217>"""
    entries = parse_list_three(xml)
    assert entries[0]["code"] == "JNK"
    assert entries[0]["active_to"] is None


def test_merge_prefers_current_over_historical():
    current = parse_list_one(LIST_ONE_XML)
    historical = parse_list_three(LIST_THREE_XML)
    merged = merge(current, historical)
    by_code = {e["code"]: e for e in merged}
    # USD is in current → no active_to set
    assert "active_to" not in by_code["USD"]
    # BGL is historical-only → active_to preserved
    assert by_code["BGL"]["active_to"] == "1999-07-31"


def test_render_yaml_is_deterministic_and_sorted():
    current = parse_list_one(LIST_ONE_XML)
    historical = parse_list_three(LIST_THREE_XML)
    merged = merge(current, historical)
    out = render_yaml(merged)
    parsed = pyyaml.safe_load(out)
    codes = [e["code"] for e in parsed["currencies"]]
    assert codes == sorted(codes)


def test_diff_against_existing(tmp_path: Path):
    current = parse_list_one(LIST_ONE_XML)
    merged_v1 = merge(current, [])
    out = tmp_path / "ccy.yaml"
    out.write_text(render_yaml(merged_v1), encoding="utf-8")

    # Now imagine v2 adds historical entries and changes JPY name.
    merged_v2 = list(merged_v1)
    for e in merged_v2:
        if e["code"] == "JPY":
            e["name"] = "Japanese Yen"
    historical = parse_list_three(LIST_THREE_XML)
    merged_v2 = merge(parse_list_one(LIST_ONE_XML), historical)
    for e in merged_v2:
        if e["code"] == "JPY":
            e["name"] = "Japanese Yen"

    added, changed, removed = diff_against_existing(merged_v2, out)
    assert "BGL" in added
    assert "TPE" in added
    assert "JPY" in changed
    assert removed == []
