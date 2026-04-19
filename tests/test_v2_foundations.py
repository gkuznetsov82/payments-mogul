"""Prototype v2 foundations: Money / Currency / FX / Calendar / Region / start_date.

Validates the engine wiring against `configs/prototype_v2_foundations_example.yaml`
and the acceptance fixture file `configs/reference/v2_foundations_acceptance_fixtures.yaml`.
"""

from __future__ import annotations

from datetime import date as _date_t, datetime as _datetime_t, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml as pyyaml

from engine.calendars import CalendarRegistry, RegionRegistry
from engine.calendars.local import LocalHolidaySource
from engine.calendars.nager import NagerDateHolidaySource
from engine.config.loader import ConfigValidationError, load_config
from engine.config.models import NagerDateSource
from engine.fx import FXService, FrankfurterFXSource, LocalFXSource
from engine.fx.rates import FXLookupError, FXRate
from engine.money import CurrencyCatalog, Money, MoneyError
from engine.scenario import ScenarioDates


ROOT = Path(__file__).parent.parent
V2_VALID = ROOT / "configs" / "prototype_v2_foundations_example.yaml"
V2_FIXTURES = ROOT / "configs" / "reference" / "v2_foundations_acceptance_fixtures.yaml"
CCY_SAMPLE = ROOT / "configs" / "reference" / "currency_catalog_iso4217_sample.yaml"
FX_SAMPLE = ROOT / "configs" / "reference" / "fx_rates_local_example.yaml"
CAL_SAMPLE = ROOT / "configs" / "reference" / "calendar_local_example.yaml"


# ---------------------------------------------------------------- v2 example loads cleanly

def test_v2_example_config_loads():
    cfg, _warns = load_config(V2_VALID)
    assert cfg.scenario.start_date in ("today", None) or cfg.scenario.start_date.startswith("20")
    assert cfg.money is not None
    assert cfg.money.default_currency == "USD"
    assert cfg.currency_catalog is not None
    assert cfg.fx is not None
    assert cfg.fx.source_policy == "local_override_then_frankfurter"
    assert {r.region_id for r in cfg.regions} == {"region_main", "region_gcc"}
    assert {c.calendar_id for c in cfg.calendars} == {"cal_global_default", "cal_gcc_fri_sat"}


def test_v0_config_still_loads_without_v2_sections():
    """Backward compat: existing v0 config must load with all v2 fields absent."""
    cfg, _ = load_config(ROOT / "configs" / "prototype_v0.yaml")
    assert cfg.money is None
    assert cfg.currency_catalog is None
    assert cfg.fx is None
    assert cfg.calendars == []
    assert cfg.regions == []


# ---------------------------------------------------------------- referential integrity

def _v2_data() -> dict:
    return pyyaml.safe_load(V2_VALID.read_text(encoding="utf-8"))


def _write_tmp(tmp_path, data: dict) -> Path:
    p = tmp_path / "cfg.yaml"
    p.write_text(pyyaml.dump(data))
    return p


def test_unknown_region_id_on_vendor_rejected(tmp_path):
    data = _v2_data()
    data["world"]["vendor_agents"][0]["region_id"] = "region_does_not_exist"
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_REGION_NOT_FOUND"


def test_unknown_calendar_id_on_region_rejected(tmp_path):
    data = _v2_data()
    data["regions"][0]["calendar_id"] = "cal_does_not_exist"
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_CALENDAR_NOT_FOUND"


def test_unknown_fx_source_ref_rejected(tmp_path):
    data = _v2_data()
    data["fx"]["source_refs"] = ["frankfurter_ecb", "not_defined_anywhere"]
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_FX_SOURCE_REF_NOT_FOUND"


def test_frankfurter_source_must_resolve_provider(tmp_path):
    data = _v2_data()
    data["fx"]["frankfurter_sources"][0]["country_provider_map"] = None
    data["fx"]["frankfurter_sources"][0]["default_provider"] = None
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_FRANKFURTER_PROVIDER_UNRESOLVED"


def test_fx_policy_source_mismatch(tmp_path):
    """policy=local_only but no enabled local file => E_FX_POLICY_SOURCE_MISMATCH."""
    data = _v2_data()
    data["fx"]["source_policy"] = "local_only"
    data["fx"]["sources"]["local_file"]["enabled"] = False
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_FX_POLICY_SOURCE_MISMATCH"


def test_invalid_start_date_rejected(tmp_path):
    data = _v2_data()
    data["scenario"]["start_date"] = "tomorrow"
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_START_DATE_INVALID"


# ---------------------------------------------------------------- Money quantization

def test_money_quantizes_to_minor_unit_usd():
    cat = CurrencyCatalog.from_file(CCY_SAMPLE)
    usd = cat.get("USD")
    m = Money.of("10.127", usd, rounding_mode="half_up")  # acceptance fixture #1
    assert m.amount == Decimal("10.13")
    assert m.currency.code == "USD"
    assert m.to_dict() == {"amount": "10.13", "currency": "USD"}


def test_money_quantizes_jpy_zero_minor_unit():
    cat = CurrencyCatalog.from_file(CCY_SAMPLE)
    jpy = cat.get("JPY")
    m = Money.of("100.49", jpy, rounding_mode="half_up")
    assert m.amount == Decimal("100")


def test_money_quantizes_bhd_three_minor_units():
    cat = CurrencyCatalog.from_file(CCY_SAMPLE)
    bhd = cat.get("BHD")
    m = Money.of("1.2345", bhd, rounding_mode="half_up")
    assert m.amount == Decimal("1.235")


def test_money_currency_mismatch_raises():
    cat = CurrencyCatalog.from_file(CCY_SAMPLE)
    usd = cat.get("USD")
    eur = cat.get("EUR")
    a = Money.of("1", usd)
    b = Money.of("1", eur)
    with pytest.raises(MoneyError):
        a.add(b)


# ---------------------------------------------------------------- CurrencyCatalog

def test_currency_catalog_lookup_by_code():
    cat = CurrencyCatalog.from_file(CCY_SAMPLE)
    assert "USD" in cat.codes()
    assert cat.get("EUR").minor_unit == 2
    assert cat.get("JPY").minor_unit == 0


def test_currency_catalog_historical_record_by_date():
    cat = CurrencyCatalog.from_file(CCY_SAMPLE)
    # BGN is active 1999..2025-12-31 in the sample
    valid_date = _date_t(2020, 1, 1)
    bgn = cat.get("BGN", on_date=valid_date)
    assert bgn.code == "BGN"
    expired_date = _date_t(2030, 1, 1)
    with pytest.raises(Exception):
        cat.get("BGN", on_date=expired_date)


# ---------------------------------------------------------------- FX local + service

def test_fx_local_lookup_matches_fixture():
    src = LocalFXSource.from_file(FX_SAMPLE)
    rate = src.get_rate(_date_t(2026, 1, 1), "EUR", "USD")
    assert rate is not None
    assert rate.rate == Decimal("1.102500")
    assert rate.provider_id == "ECB"


def test_fx_service_local_only_returns_local_record():
    cfg, _ = load_config(V2_VALID)
    cfg_fx = cfg.fx
    cfg_fx.source_policy = "local_only"
    local = LocalFXSource.from_file(FX_SAMPLE)
    svc = FXService(cfg_fx, local_source=local, frankfurter_sources=[])
    rate = svc.get_rate(_date_t(2026, 1, 1), "EUR", "USD")
    assert rate.provider_id == "ECB"
    assert rate.rate == Decimal("1.102500")


def test_fx_service_addresses_specific_frankfurter_source():
    """Acceptance fixture #4: scenario may reference multiple Frankfurter sources
    and pick a specific source_id at lookup."""
    cfg, _ = load_config(V2_VALID)
    cfg.fx.source_policy = "frankfurter_only"
    fr_ecb = FrankfurterFXSource(cfg.fx.frankfurter_sources[0])  # base_country=DE -> ECB
    fr_fed = FrankfurterFXSource(cfg.fx.frankfurter_sources[1])  # base_country=US -> FED
    # Seed both caches with deterministic rates so no network is required.
    fr_ecb.seed_cache(FXRate(
        date=_date_t(2026, 1, 2), base_currency="USD", quote_currency="EUR",
        rate=Decimal("0.910"), provider_id="ECB",
        retrieved_at=_datetime_t(2026, 1, 2, tzinfo=timezone.utc),
    ))
    fr_fed.seed_cache(FXRate(
        date=_date_t(2026, 1, 2), base_currency="USD", quote_currency="EUR",
        rate=Decimal("0.911"), provider_id="FED",
        retrieved_at=_datetime_t(2026, 1, 2, tzinfo=timezone.utc),
    ))
    svc = FXService(cfg.fx, local_source=None, frankfurter_sources=[fr_ecb, fr_fed])
    rate = svc.get_rate(_date_t(2026, 1, 2), "USD", "EUR",
                        requested_source_id="frankfurter_usfrb")
    assert rate.provider_id == "FED"


def test_fx_service_local_override_then_frankfurter_falls_through():
    cfg, _ = load_config(V2_VALID)
    cfg.fx.source_policy = "local_override_then_frankfurter"
    local = LocalFXSource.from_file(FX_SAMPLE)  # has 2026-01-02 EUR->USD
    fr = FrankfurterFXSource(cfg.fx.frankfurter_sources[0])
    fr.seed_cache(FXRate(
        date=_date_t(2026, 6, 1), base_currency="GBP", quote_currency="USD",
        rate=Decimal("1.250"), provider_id="ECB",
        retrieved_at=_datetime_t(2026, 6, 1, tzinfo=timezone.utc),
    ))
    svc = FXService(cfg.fx, local_source=local, frankfurter_sources=[fr])
    # Local hit
    a = svc.get_rate(_date_t(2026, 1, 2), "EUR", "USD")
    assert a.provider_id == "ECB"
    # Local miss → Frankfurter fallback
    b = svc.get_rate(_date_t(2026, 6, 1), "GBP", "USD")
    assert b.provider_id == "ECB"
    assert b.rate == Decimal("1.250")


def test_fx_service_raises_when_nothing_resolves():
    cfg, _ = load_config(V2_VALID)
    cfg.fx.source_policy = "local_only"
    local = LocalFXSource([])
    svc = FXService(cfg.fx, local_source=local, frankfurter_sources=[])
    with pytest.raises(FXLookupError):
        svc.get_rate(_date_t(2099, 1, 1), "ZZZ", "YYY")


# ---------------------------------------------------------------- Calendar + Region

def test_calendar_weekend_sat_sun():
    cfg, _ = load_config(V2_VALID)
    reg = CalendarRegistry.from_config(cfg)
    cal = reg.get("cal_global_default")
    # 2026-04-25 is a Saturday
    assert cal.is_weekend(_date_t(2026, 4, 25)) is True
    assert cal.is_weekend(_date_t(2026, 4, 24)) is False  # Friday


def test_calendar_weekend_fri_sat():
    cfg, _ = load_config(V2_VALID)
    reg = CalendarRegistry.from_config(cfg)
    gcc = reg.get("cal_gcc_fri_sat")
    # Acceptance fixture #3: in cal_gcc_fri_sat, Friday 2026-04-24 must be non-working.
    assert gcc.is_weekend(_date_t(2026, 4, 24)) is True
    assert gcc.is_working_day(_date_t(2026, 4, 24)) is False


def test_calendar_inline_non_working_override():
    cfg, _ = load_config(V2_VALID)
    reg = CalendarRegistry.from_config(cfg)
    cal = reg.get("cal_global_default")
    # 2026-12-31 is in non_working_overrides
    assert cal.is_holiday(_date_t(2026, 12, 31)) is True


def test_calendar_local_source_holiday():
    cfg, _ = load_config(V2_VALID)
    reg = CalendarRegistry.from_config(cfg)
    cal = reg.get("cal_global_default")
    # 2026-11-27 is in local example file
    assert cal.is_holiday(_date_t(2026, 11, 27)) is True


def test_calendar_nager_seeded_holiday():
    cfg, _ = load_config(V2_VALID)
    reg = CalendarRegistry.from_config(cfg)
    cal = reg.get("cal_global_default")
    # Seed Nager source so we don't hit network. Pick a working day (Wed 2026-07-15).
    cal.nager_source.seed_year(2026, {_date_t(2026, 7, 15)})
    assert cal.is_holiday(_date_t(2026, 7, 15)) is True


def test_region_resolves_calendar():
    cfg, _ = load_config(V2_VALID)
    cal_reg = CalendarRegistry.from_config(cfg)
    reg = RegionRegistry.from_config(cfg, cal_reg)
    cal = reg.calendar_for_region("region_gcc")
    assert cal.calendar_id == "cal_gcc_fri_sat"


def test_world_vendor_calendar_resolved_via_region():
    """Acceptance fixture #5."""
    cfg, _ = load_config(V2_VALID)
    cal_reg = CalendarRegistry.from_config(cfg)
    reg = RegionRegistry.from_config(cfg, cal_reg)
    vendor = cfg.world.vendor_agents[0]
    cal = reg.calendar_for_entity(vendor.region_id)
    assert cal.calendar_id == "cal_global_default"


def test_region_default_used_when_pop_omits_region_id(tmp_path):
    """Pop without region_id falls back to default region (only one region defined)."""
    data = _v2_data()
    data["regions"] = [data["regions"][0]]  # single region only -> auto-default
    data["world"]["pops"][0].pop("region_id", None)
    cfg, _ = load_config(_write_tmp(tmp_path, data))
    cal_reg = CalendarRegistry.from_config(cfg)
    reg = RegionRegistry.from_config(cfg, cal_reg)
    pop = cfg.world.pops[0]
    cal = reg.calendar_for_entity(pop.region_id)
    assert cal.calendar_id == "cal_global_default"


# ---------------------------------------------------------------- ScenarioDates

def test_scenario_dates_today_resolved_once():
    fixed = _date_t(2026, 4, 19)
    sd = ScenarioDates.from_config("today", today_fn=lambda: fixed)
    assert sd.start_date == fixed
    assert sd.date_for_tick(0) == fixed
    assert sd.date_for_tick(7) == _date_t(2026, 4, 26)


def test_scenario_dates_fixed_date():
    sd = ScenarioDates.from_config("2026-01-15")
    assert sd.start_date == _date_t(2026, 1, 15)
    assert sd.date_for_tick(31) == _date_t(2026, 2, 15)


def test_scenario_dates_invalid():
    with pytest.raises(Exception):
        ScenarioDates.from_config("nope")


# ---------------------------------------------------------------- Acceptance fixtures alignment

def test_acceptance_fixtures_money_check():
    """Re-validate fixture #1 against the live Money primitive."""
    fixtures = pyyaml.safe_load(V2_FIXTURES.read_text(encoding="utf-8"))
    case = next(c for c in fixtures["checks"] if c["id"] == "money_minor_unit_enforced")
    cat = CurrencyCatalog.from_file(CCY_SAMPLE)
    cur = cat.get(case["input"]["currency"])
    m = Money.of(case["input"]["amount"], cur,
                 rounding_mode=case["input"]["rounding_mode"])
    assert format(m.amount, "f") == case["expected_output"]["amount"]


def test_acceptance_fixtures_fx_local_check():
    fixtures = pyyaml.safe_load(V2_FIXTURES.read_text(encoding="utf-8"))
    case = next(c for c in fixtures["checks"] if c["id"] == "fx_historical_local_lookup")
    src = LocalFXSource.from_file(FX_SAMPLE)
    rate = src.get_rate(_date_t.fromisoformat(case["input"]["date"]),
                        case["input"]["base"], case["input"]["quote"])
    assert rate is not None
    assert format(rate.rate, "f") == case["expected_output"]["rate"]
    assert rate.provider_id == case["expected_output"]["provider_id"]


# ---------------------------------------------------------------- engine v2 propagation

import asyncio  # noqa: E402  (need this for the async tests below)
from engine.simulation.engine import EngineState, SimulationEngine  # noqa: E402


async def _drain(q: asyncio.Queue, timeout: float = 0.1) -> list[dict]:
    out = []
    while True:
        try:
            ev = await asyncio.wait_for(q.get(), timeout=timeout)
            out.append(ev)
        except asyncio.TimeoutError:
            return out


def _v2_engine() -> SimulationEngine:
    cfg, _ = load_config(V2_VALID)
    eng = SimulationEngine(cfg, config_path=V2_VALID)
    eng.state_from_idle()
    return eng


def test_engine_resolves_scenario_dates_and_currency_catalog():
    eng = _v2_engine()
    assert eng.simulation_date is not None
    assert eng.scenario_start_date_resolved is not None
    assert eng.simulation_date == eng.scenario_start_date_resolved  # tick 0
    assert eng.money_object_mode is True
    assert eng.default_currency == "USD"
    assert eng._currency_catalog is not None
    assert "USD" in eng._currency_catalog.codes()


def test_v2_snapshot_includes_date_and_currency_context():
    eng = _v2_engine()
    snap = eng.build_snapshot()
    assert "simulation_date" in snap
    assert "scenario_start_date_resolved" in snap
    assert snap["default_currency"] == "USD"
    assert snap["money_object_mode"] is True
    assert snap["config"]["amount_scale_dp"] == 2
    assert snap["config"]["amount_rounding_mode"] == "half_up"


@pytest.mark.asyncio
async def test_v2_action_outcome_amount_is_money_object():
    eng = _v2_engine()
    q = eng.subscribe()
    await eng._run_one_tick(next_day_mode=True)
    events = await _drain(q)
    transact_outcomes = [e for e in events
                         if e["event"] == "action_outcome"
                         and e["data"]["action_type"] == "Transact"]
    assert transact_outcomes, "expected at least one Transact outcome"
    first = transact_outcomes[0]["data"]
    # Critical contract decision #1: no scalar fallback in v2.
    assert isinstance(first["successful_total_amount"], dict)
    assert first["successful_total_amount"]["currency"] == "USD"
    assert "amount" in first["successful_total_amount"]
    assert first["simulation_date"] == eng.simulation_date.isoformat()


@pytest.mark.asyncio
async def test_v2_tick_committed_carries_simulation_date_and_money_object_amount():
    eng = _v2_engine()
    q = eng.subscribe()
    await eng._run_one_tick(next_day_mode=True)
    events = await _drain(q)
    committed = next(e for e in events if e["event"] == "tick_committed")
    d = committed["data"]
    assert "simulation_date" in d
    assert d["simulation_date"] == eng.simulation_date.isoformat()
    assert isinstance(d["transact_amount"], dict)
    assert d["transact_amount"]["currency"] == "USD"


@pytest.mark.asyncio
async def test_v2_product_snapshot_amount_is_money_object():
    eng = _v2_engine()
    await eng._run_one_tick(next_day_mode=True)
    snap = eng.build_snapshot()
    p = snap["vendors"]["vendor_alpha"]["products"]["prod_prepaid_alpha"]
    assert isinstance(p["successful_transact_amount"], dict)
    assert p["successful_transact_amount"]["currency"] == "USD"


def test_tick_to_date_progression():
    cfg, _ = load_config(V2_VALID)
    cfg.scenario.start_date = "2026-01-15"
    eng = SimulationEngine(cfg, config_path=V2_VALID)
    eng.state_from_idle()
    assert eng.simulation_date == _date_t(2026, 1, 15)
    # Step a few ticks via the model directly (avoid running async tick loop here).
    eng.model.steps = 7
    assert eng.simulation_date == _date_t(2026, 1, 22)


# ---------------------------------------------------------------- v0 backward compat (scalar amounts)

@pytest.mark.asyncio
async def test_v0_action_outcome_amount_is_scalar_not_money_object():
    """v0 config has no `money` section → money_object_mode is False → amount fields stay scalar."""
    cfg, _ = load_config(ROOT / "configs" / "prototype_v0.yaml")
    eng = SimulationEngine(cfg, config_path=ROOT / "configs" / "prototype_v0.yaml")
    eng.state_from_idle()
    assert eng.money_object_mode is False
    q = eng.subscribe()
    await eng._run_one_tick(next_day_mode=True)
    events = await _drain(q)
    transact_outcomes = [e for e in events
                         if e["event"] == "action_outcome"
                         and e["data"]["action_type"] == "Transact"]
    assert transact_outcomes
    first = transact_outcomes[0]["data"]
    assert isinstance(first["successful_total_amount"], (int, float))


# ---------------------------------------------------------------- authoring symmetry

def test_pop_daily_transact_amount_money_object_form_accepted(tmp_path):
    """v2 example uses {amount, currency} form; loader must accept and tag the currency."""
    cfg, _ = load_config(V2_VALID)
    pop = cfg.world.pops[0]
    assert pop.daily_transact_amount == 22.5
    assert pop.daily_transact_amount_currency == "USD"


def test_pop_daily_transact_amount_currency_must_match_default(tmp_path):
    data = pyyaml.safe_load(V2_VALID.read_text(encoding="utf-8"))
    data["world"]["pops"][0]["daily_transact_amount"] = {"amount": 22.5, "currency": "EUR"}
    p = tmp_path / "cfg.yaml"
    p.write_text(pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_AMOUNT_CURRENCY_MISMATCH"
