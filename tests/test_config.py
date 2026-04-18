"""Config loader validation tests — covers all hard error codes."""

import pytest
from pathlib import Path
from engine.config.loader import ConfigValidationError, ConfigWarning, load_config

CONFIGS = Path(__file__).parent.parent / "configs"
VALID = CONFIGS / "prototype_v0.yaml"


def test_valid_config_loads():
    cfg, warns = load_config(VALID)
    assert cfg.scenario.id == "prototype_vendor_pop_v1"
    assert cfg.simulation.agent_method_order == ["Onboard", "Transact"]
    assert len(cfg.world.vendor_agents) >= 1
    assert len(cfg.world.pops) >= 1


def test_valid_config_no_blocking_warns(tmp_path):
    cfg, warns = load_config(VALID)
    codes = {w.code for w in warns}
    blocking = {c for c in codes if c.startswith("E_")}
    assert not blocking, f"Unexpected hard errors in warnings: {blocking}"


def test_invalid_scenario_id():
    with pytest.raises(ConfigValidationError) as exc:
        load_config(CONFIGS / "invalid_scenario_id.yaml")
    assert exc.value.code == "E_SCENARIO_ID_UNSUPPORTED"


def test_invalid_method_order():
    with pytest.raises(ConfigValidationError) as exc:
        load_config(CONFIGS / "invalid_method_order.yaml")
    assert exc.value.code == "E_METHOD_ORDER_INVALID"


def _write(tmp_path, data: str) -> Path:
    p = tmp_path / "cfg.yaml"
    p.write_text(data)
    return p


def test_debug_window_invalid(tmp_path):
    yaml = (VALID.read_text()
            .replace("debug_history_default_ticks: 7", "debug_history_default_ticks: 99"))
    p = _write(tmp_path, yaml)
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_DEBUG_WINDOW_INVALID"


def test_missing_vendor(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["vendor_agents"] = []
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_WORLD_MISSING_VENDOR"


def test_missing_pop(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["pops"] = []
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_WORLD_MISSING_POP"


def test_link_target_missing(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["pops"][0]["product_links"][0]["vendor_id"] = "nonexistent_vendor"
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_LINK_TARGET_MISSING"


def test_pop_count_invalid(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["pops"][0]["pop_count"] = 0
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_POP_COUNT_INVALID"


def test_rate_out_of_range(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["pops"][0]["daily_onboard"] = 1.5
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_RATE_OUT_OF_RANGE"


def test_onboarded_count_exceeds_pop(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["pops"][0]["product_links"][0]["onboarded_count"] = 99999
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_ONBOARDED_COUNT_INVALID"


def test_friction_range_invalid(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["vendor_agents"][0]["products"][0]["onboarding_friction"] = {
        "min": 0.8, "max": 0.2  # min > max
    }
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_FRICTION_RANGE_INVALID"


def test_warning_intake_window_low(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["intake_window_ms"] = 10
    p = _write(tmp_path, pyyaml.dump(data))
    _, warns = load_config(p)
    codes = {w.code for w in warns}
    assert "W_INTAKE_WINDOW_LOW" in codes


def test_warning_no_pacing(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["tick_wall_clock_base_ms"] = 0
    p = _write(tmp_path, pyyaml.dump(data))
    _, warns = load_config(p)
    codes = {w.code for w in warns}
    assert "W_NO_PACING" in codes


# ------------------------------------------------------------------ spec 40 §simulation strict bounds

def test_intake_window_must_be_positive(tmp_path):
    """40-yaml-config: intake_window_ms must be >= 1."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["intake_window_ms"] = 0
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_INTAKE_WINDOW_INVALID"


def test_tick_wall_clock_must_be_non_negative(tmp_path):
    """40-yaml-config: tick_wall_clock_base_ms must be >= 0."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["tick_wall_clock_base_ms"] = -1
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_TICK_WALL_CLOCK_INVALID"


def test_debug_history_max_must_be_positive(tmp_path):
    """40-yaml-config: debug_history_max_ticks must be >= 1."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["debug_history_max_ticks"] = 0
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_DEBUG_WINDOW_INVALID"


def test_debug_history_default_must_be_positive(tmp_path):
    """40-yaml-config: debug_history_default_ticks must be >= 1."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["debug_history_default_ticks"] = 0
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_DEBUG_WINDOW_INVALID"


def test_intake_cannot_exceed_tick_total(tmp_path):
    """40-yaml-config: intake_window_ms is a PORTION of tick_wall_clock_base_ms,
    not additive. If intake > total (and total > 0), reject."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["tick_wall_clock_base_ms"] = 1000
    data["simulation"]["intake_window_ms"] = 9500
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_INTAKE_EXCEEDS_TICK"


def test_intake_equal_to_tick_total_is_allowed(tmp_path):
    """Edge case: intake == total is valid (zero inter-tick wait)."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["tick_wall_clock_base_ms"] = 500
    data["simulation"]["intake_window_ms"] = 500
    p = _write(tmp_path, pyyaml.dump(data))
    cfg, _ = load_config(p)
    assert cfg.simulation.tick_wall_clock_base_ms == 500
    assert cfg.simulation.intake_window_ms == 500


def test_no_pacing_mode_allows_any_intake(tmp_path):
    """When tick_wall_clock_base_ms=0 (no-pacing mode), intake can be any positive value
    because pacing is disabled entirely."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["tick_wall_clock_base_ms"] = 0
    data["simulation"]["intake_window_ms"] = 500
    p = _write(tmp_path, pyyaml.dump(data))
    cfg, _ = load_config(p)
    assert cfg.simulation.tick_wall_clock_base_ms == 0
    assert cfg.simulation.intake_window_ms == 500


# ------------------------------------------------------------------ spec 40 §numeric typing

def test_rounding_mode_defaults():
    """v0 config carries half_up defaults per spec 40."""
    cfg, _ = load_config(VALID)
    assert cfg.simulation.count_rounding_mode == "half_up"
    assert cfg.simulation.amount_rounding_mode == "half_up"
    assert cfg.simulation.amount_scale_dp == 2


def test_invalid_rounding_mode_rejected(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["count_rounding_mode"] = "banker"
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_ROUNDING_MODE_INVALID"


def test_negative_amount_scale_rejected(tmp_path):
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["simulation"]["amount_scale_dp"] = -1
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError) as exc:
        load_config(p)
    assert exc.value.code == "E_AMOUNT_SCALE_INVALID"


def test_non_integer_pop_count_coerced_or_rejected(tmp_path):
    """pop_count must be an integer per spec 40. Float values like 10000.5 should be rejected."""
    import yaml as pyyaml
    data = pyyaml.safe_load(VALID.read_text())
    data["world"]["pops"][0]["pop_count"] = 10000.5
    p = _write(tmp_path, pyyaml.dump(data))
    with pytest.raises(ConfigValidationError):
        load_config(p)
