"""YAML config loader with cross-entity validation and warnings."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from engine.config.models import PrototypeConfig


@dataclass
class ConfigWarning:
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigValidationError(Exception):
    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        self.code = code
        self.message = message
        self.field = field
        super().__init__(f"[{code}] {message}")


def load_config(path: str | Path) -> tuple[PrototypeConfig, list[ConfigWarning]]:
    """Load, parse, and validate a v0 prototype config YAML.

    Returns (config, warnings) on success.
    Raises ConfigValidationError on any hard error.
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigValidationError("E_YAML_PARSE", str(exc))

    try:
        cfg = PrototypeConfig.model_validate(data)
    except ValidationError as exc:
        # Surface the first meaningful error code from the message text
        first = exc.errors()[0]
        msg = str(first.get("msg", ""))
        # Extract stable code if embedded
        code = _extract_code(msg)
        field = ".".join(str(p) for p in first.get("loc", []))
        raise ConfigValidationError(code, msg, field) from exc

    collected: list[ConfigWarning] = []

    # Cross-entity validations (hard errors)
    sim = cfg.simulation
    if sim.debug_history_default_ticks > sim.debug_history_max_ticks:
        raise ConfigValidationError(
            "E_DEBUG_WINDOW_INVALID",
            f"debug_history_default_ticks ({sim.debug_history_default_ticks}) "
            f"exceeds debug_history_max_ticks ({sim.debug_history_max_ticks})",
            "simulation.debug_history_default_ticks",
        )

    if len(cfg.world.vendor_agents) == 0:
        raise ConfigValidationError("E_WORLD_MISSING_VENDOR", "At least one vendor_agent is required")

    if len(cfg.world.pops) == 0:
        raise ConfigValidationError("E_WORLD_MISSING_POP", "At least one pop is required")

    # Build product reference set for link resolution
    known_products: set[tuple[str, str]] = set()
    for vendor in cfg.world.vendor_agents:
        for product in vendor.products:
            known_products.add((vendor.vendor_id, product.product_id))

    for pop in cfg.world.pops:
        all_links_unknown = all(not link.known for link in pop.product_links)
        if all_links_unknown:
            collected.append(
                ConfigWarning(
                    "W_ALL_LINKS_UNKNOWN",
                    f"Pop '{pop.pop_id}' has no known=true product links; "
                    "no onboard/transact requests will be generated",
                )
            )

        for link in pop.product_links:
            pair = (link.vendor_id, link.product_id)
            if pair not in known_products:
                raise ConfigValidationError(
                    "E_LINK_TARGET_MISSING",
                    f"Pop '{pop.pop_id}' links to unknown product "
                    f"({link.vendor_id}, {link.product_id})",
                    "world.pops[].product_links",
                )
            if link.onboarded_count > pop.pop_count:
                raise ConfigValidationError(
                    "E_ONBOARDED_COUNT_INVALID",
                    f"Pop '{pop.pop_id}' link to ({link.vendor_id}, {link.product_id}): "
                    f"onboarded_count ({link.onboarded_count}) > pop_count ({pop.pop_count})",
                    "world.pops[].product_links[].onboarded_count",
                )

    # Warnings
    if sim.intake_window_ms < 50:
        collected.append(
            ConfigWarning(
                "W_INTAKE_WINDOW_LOW",
                f"intake_window_ms={sim.intake_window_ms} is very low; "
                "manual command timing may be difficult",
            )
        )
    if sim.tick_wall_clock_base_ms == 0:
        collected.append(
            ConfigWarning(
                "W_NO_PACING",
                "tick_wall_clock_base_ms=0 disables pacing; "
                "ticks will run as fast as possible",
            )
        )

    # v2 foundations cross-entity validation (spec 40 §regions/§fx).
    _validate_v2_foundations(cfg, collected)

    return cfg, collected


def _validate_v2_foundations(cfg: PrototypeConfig, collected: list[ConfigWarning]) -> None:
    """Cross-entity v2 checks for region_id/calendar_id/fx source_refs.

    Backward compat: if v2 sections are absent, skip silently. v2 sections present
    but partially populated must still pass referential integrity checks.
    """
    # 1. calendars: calendar_ids must be unique.
    if cfg.calendars:
        ids: set[str] = set()
        for c in cfg.calendars:
            if c.calendar_id in ids:
                raise ConfigValidationError(
                    "E_CALENDAR_DUPLICATE",
                    f"Duplicate calendar_id '{c.calendar_id}'",
                    "calendars[].calendar_id",
                )
            ids.add(c.calendar_id)

    # 2. regions: region_ids must be unique; calendar_id must reference a defined calendar.
    if cfg.regions:
        rids: set[str] = set()
        cal_ids = {c.calendar_id for c in cfg.calendars}
        for r in cfg.regions:
            if r.region_id in rids:
                raise ConfigValidationError(
                    "E_REGION_DUPLICATE",
                    f"Duplicate region_id '{r.region_id}'",
                    "regions[].region_id",
                )
            rids.add(r.region_id)
            if r.calendar_id not in cal_ids:
                raise ConfigValidationError(
                    "E_CALENDAR_NOT_FOUND",
                    f"Region '{r.region_id}' references unknown calendar '{r.calendar_id}'",
                    "regions[].calendar_id",
                )

    # 3. world entities: region_id (when set) must reference a defined region.
    region_ids = {r.region_id for r in cfg.regions}
    for v in cfg.world.vendor_agents:
        if v.region_id is not None and v.region_id not in region_ids:
            raise ConfigValidationError(
                "E_REGION_NOT_FOUND",
                f"Vendor '{v.vendor_id}' references unknown region '{v.region_id}'",
                "world.vendor_agents[].region_id",
            )
    for p in cfg.world.pops:
        if p.region_id is not None and p.region_id not in region_ids:
            raise ConfigValidationError(
                "E_REGION_NOT_FOUND",
                f"Pop '{p.pop_id}' references unknown region '{p.region_id}'",
                "world.pops[].region_id",
            )

    # 4. fx: source_refs must reference defined frankfurter source_ids.
    if cfg.fx is not None:
        # Frankfurter source_ids must be unique.
        fr_ids: set[str] = set()
        for fs in cfg.fx.frankfurter_sources:
            if fs.source_id in fr_ids:
                raise ConfigValidationError(
                    "E_FX_SOURCE_DUPLICATE",
                    f"Duplicate frankfurter source_id '{fs.source_id}'",
                    "fx.frankfurter_sources[].source_id",
                )
            fr_ids.add(fs.source_id)

        if cfg.fx.source_refs:
            for ref in cfg.fx.source_refs:
                if ref not in fr_ids:
                    raise ConfigValidationError(
                        "E_FX_SOURCE_REF_NOT_FOUND",
                        f"fx.source_refs entry '{ref}' does not match any defined "
                        "frankfurter_sources[].source_id",
                        "fx.source_refs",
                    )

        # Policy <-> source presence consistency.
        policy = cfg.fx.source_policy
        local_enabled = (cfg.fx.sources is not None
                         and cfg.fx.sources.local_file is not None
                         and cfg.fx.sources.local_file.enabled)
        any_frankfurter_enabled = any(s.enabled for s in cfg.fx.frankfurter_sources)
        if policy == "local_only" and not local_enabled:
            raise ConfigValidationError(
                "E_FX_POLICY_SOURCE_MISMATCH",
                "fx.source_policy is 'local_only' but no enabled local_file source is configured",
                "fx.source_policy",
            )
        if policy == "frankfurter_only" and not any_frankfurter_enabled:
            raise ConfigValidationError(
                "E_FX_POLICY_SOURCE_MISMATCH",
                "fx.source_policy is 'frankfurter_only' but no enabled frankfurter_sources entry exists",
                "fx.source_policy",
            )
        if policy == "local_override_then_frankfurter" and not (local_enabled or any_frankfurter_enabled):
            raise ConfigValidationError(
                "E_FX_POLICY_SOURCE_MISMATCH",
                "fx.source_policy is 'local_override_then_frankfurter' but no enabled source exists",
                "fx.source_policy",
            )

    # 5. Authoring currency (when pop daily_transact_amount uses money-object form)
    # must match money.default_currency. Spec 40 §money + critical contract decision #1.
    default_currency = cfg.money.default_currency if cfg.money else None
    for p in cfg.world.pops:
        if p.daily_transact_amount_currency is not None:
            if default_currency is None:
                raise ConfigValidationError(
                    "E_AMOUNT_CURRENCY_WITHOUT_MONEY",
                    f"Pop '{p.pop_id}' authored daily_transact_amount as money-object "
                    "but `money.default_currency` is not set",
                    "world.pops[].daily_transact_amount.currency",
                )
            if p.daily_transact_amount_currency != default_currency:
                raise ConfigValidationError(
                    "E_AMOUNT_CURRENCY_MISMATCH",
                    f"Pop '{p.pop_id}' daily_transact_amount currency "
                    f"'{p.daily_transact_amount_currency}' does not match "
                    f"money.default_currency '{default_currency}'",
                    "world.pops[].daily_transact_amount.currency",
                )

    # 6. Pipeline contract validation (spec 40 §pipeline, ADR-0002).
    _validate_pipeline_contracts(cfg)


_ROLE_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _validate_pipeline_contracts(cfg: PrototypeConfig) -> None:
    """Cross-entity validation for the pipeline section + per-product bindings."""
    pipeline = cfg.pipeline
    profile_ids: set[str] = set()
    profiles_by_id: dict[str, "PipelineProfileConfig"] = {}

    if pipeline is not None:
        # First pass: id uniqueness + index.
        for prof in pipeline.pipeline_profiles:
            if prof.pipeline_profile_id in profile_ids:
                raise ConfigValidationError(
                    "E_PIPELINE_PROFILE_DUPLICATE",
                    f"Duplicate pipeline_profile_id '{prof.pipeline_profile_id}'",
                    "pipeline.pipeline_profiles[].pipeline_profile_id",
                )
            profile_ids.add(prof.pipeline_profile_id)
            profiles_by_id[prof.pipeline_profile_id] = prof

        # Cross-profile pool of all outgoing intent ids: a sink profile's fee can
        # trigger on an upstream profile's outgoing_intent_id (the routed intent).
        all_outgoing_ids: set[str] = {
            d.outgoing_intent_id
            for prof in pipeline.pipeline_profiles
            for i in prof.transaction_intents
            for d in i.destinations
        }
        all_intent_ids: set[str] = {
            i.intent_id
            for prof in pipeline.pipeline_profiles
            for i in prof.transaction_intents
        }

        for prof in pipeline.pipeline_profiles:

            # Validate intra-profile refs.
            ledger_refs = {l.ledger_ref for l in prof.ledger_construction}
            container_refs = {c.container_ref for c in prof.value_container_construction}
            intent_ids = {i.intent_id for i in prof.transaction_intents}
            outgoing_ids = {
                d.outgoing_intent_id
                for i in prof.transaction_intents
                for d in i.destinations
            }

            for r in prof.posting_rules:
                if r.source_ledger_ref not in ledger_refs:
                    raise ConfigValidationError(
                        "E_LEDGER_REF_NOT_FOUND",
                        f"Profile '{prof.pipeline_profile_id}': posting_rules.source_ledger_ref "
                        f"'{r.source_ledger_ref}' not defined",
                        "pipeline.pipeline_profiles[].posting_rules[].source_ledger_ref",
                    )
                if r.destination_ledger_ref not in ledger_refs:
                    raise ConfigValidationError(
                        "E_LEDGER_REF_NOT_FOUND",
                        f"Profile '{prof.pipeline_profile_id}': posting_rules.destination_ledger_ref "
                        f"'{r.destination_ledger_ref}' not defined",
                        "pipeline.pipeline_profiles[].posting_rules[].destination_ledger_ref",
                    )

            for r in prof.asset_transfer_rules:
                if r.source_container_ref not in container_refs:
                    raise ConfigValidationError(
                        "E_CONTAINER_REF_NOT_FOUND",
                        f"Profile '{prof.pipeline_profile_id}': asset_transfer_rules.source_container_ref "
                        f"'{r.source_container_ref}' not defined",
                        "pipeline.pipeline_profiles[].asset_transfer_rules[].source_container_ref",
                    )
                if r.destination_container_ref not in container_refs:
                    raise ConfigValidationError(
                        "E_CONTAINER_REF_NOT_FOUND",
                        f"Profile '{prof.pipeline_profile_id}': asset_transfer_rules.destination_container_ref "
                        f"'{r.destination_container_ref}' not defined",
                        "pipeline.pipeline_profiles[].asset_transfer_rules[].destination_container_ref",
                    )

            for m in prof.ledger_value_container_map:
                if m.ledger_ref not in ledger_refs:
                    raise ConfigValidationError(
                        "E_LEDGER_REF_NOT_FOUND",
                        f"Profile '{prof.pipeline_profile_id}': ledger_value_container_map.ledger_ref "
                        f"'{m.ledger_ref}' not defined",
                        "pipeline.pipeline_profiles[].ledger_value_container_map[].ledger_ref",
                    )
                if m.container_ref not in container_refs:
                    raise ConfigValidationError(
                        "E_CONTAINER_REF_NOT_FOUND",
                        f"Profile '{prof.pipeline_profile_id}': ledger_value_container_map.container_ref "
                        f"'{m.container_ref}' not defined",
                        "pipeline.pipeline_profiles[].ledger_value_container_map[].container_ref",
                    )

            # Fee triggers must reference a defined intent (this profile's intent_ids,
            # any profile's outgoing_intent_id — sink profiles trigger on routed
            # upstream intents) OR a fee_id earlier in the same sequence.
            for seq in prof.fee_sequences:
                seen_in_seq: set[str] = set()
                for fee in seq.fees:
                    valid_triggers = (
                        all_intent_ids
                        | all_outgoing_ids
                        | seen_in_seq
                    )
                    for tid in fee.trigger_ids:
                        if tid not in valid_triggers:
                            raise ConfigValidationError(
                                "E_FEE_TRIGGER_UNKNOWN",
                                f"Profile '{prof.pipeline_profile_id}' fee '{fee.fee_id}' "
                                f"references unknown trigger '{tid}'",
                                "pipeline.pipeline_profiles[].fee_sequences[].fees[].trigger_ids",
                            )
                    seen_in_seq.add(fee.fee_id)

    # Per-product binding validation: pipeline_profile_id must reference a defined profile,
    # and every {role_placeholder} in path patterns / destinations must be resolvable from
    # the product's pipeline_role_bindings.
    for vendor in cfg.world.vendor_agents:
        for product in vendor.products:
            if product.pipeline_profile_id is None:
                # Profile binding is optional; products without it just don't run a pipeline.
                continue
            if pipeline is None or product.pipeline_profile_id not in profile_ids:
                raise ConfigValidationError(
                    "E_PIPELINE_PROFILE_NOT_FOUND",
                    f"Vendor '{vendor.vendor_id}' product '{product.product_id}' "
                    f"references unknown pipeline_profile_id "
                    f"'{product.pipeline_profile_id}'",
                    "world.vendor_agents[].products[].pipeline_profile_id",
                )
            bindings = product.pipeline_role_bindings
            known_roles: set[str] = set()
            if bindings is not None:
                known_roles |= set(bindings.entity_roles.keys())
            profile = profiles_by_id[product.pipeline_profile_id]
            # Collect placeholders from path patterns + destinations.
            placeholders_seen: set[str] = set()
            for l in profile.ledger_construction:
                placeholders_seen |= set(_ROLE_PLACEHOLDER_RE.findall(l.path_pattern))
            for c in profile.value_container_construction:
                placeholders_seen |= set(_ROLE_PLACEHOLDER_RE.findall(c.path_pattern))
            for i in profile.transaction_intents:
                for d in i.destinations:
                    placeholders_seen.add(d.destination_role)
            for seq in profile.fee_sequences:
                for fee in seq.fees:
                    placeholders_seen.add(fee.beneficiary_role)
                    if fee.beneficiary_product_role:
                        placeholders_seen.add(fee.beneficiary_product_role)
            unresolved = placeholders_seen - known_roles
            if unresolved:
                raise ConfigValidationError(
                    "E_PIPELINE_ROLE_UNRESOLVED",
                    f"Vendor '{vendor.vendor_id}' product '{product.product_id}' "
                    f"profile '{product.pipeline_profile_id}': roles referenced but "
                    f"not bound: {sorted(unresolved)}",
                    "world.vendor_agents[].products[].pipeline_role_bindings.entity_roles",
                )

            # If pipeline binding present but pipeline section is v2_foundations,
            # enforce config consistency: v2 profiles attached to products are
            # parsed/validated but not executed at runtime (ADR-0002 gating). No error,
            # just informational warning would go here — left as silent skip per spec.


def _extract_code(msg: str) -> str:
    """Pull E_XXX code from validator message, or return generic."""
    for token in msg.split():
        if token.startswith("E_"):
            return token.rstrip(":,.")
    return "E_CONFIG_INVALID"
