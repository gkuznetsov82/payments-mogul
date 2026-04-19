"""Role resolution per spec 40 §pipeline_role_bindings + path-pattern expansion.

The same pipeline profile is reused across products; the per-product
`pipeline_role_bindings` map symbolic role names to concrete refs. A path
pattern like `[Managed-Funds][{product_role}][Settlement][{counterparty_role}]`
is expanded by substituting placeholders with the resolved ID strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from engine.config.models import PipelineRoleBindings, PipelineRoleSelector


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class RoleResolutionError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedRole:
    role: str
    agent_id: Optional[str] = None
    product_id: Optional[str] = None
    local: bool = False

    def as_id_string(self) -> str:
        if self.product_id:
            return self.product_id
        if self.agent_id:
            return self.agent_id
        if self.local:
            return "local"
        return self.role


class RoleResolver:
    def __init__(self, bindings: Optional[PipelineRoleBindings]) -> None:
        self.bindings = bindings or PipelineRoleBindings()

    def resolve(self, role: str) -> ResolvedRole:
        sel = self.bindings.entity_roles.get(role)
        if sel is None:
            raise RoleResolutionError(
                f"role {role!r} not bound in pipeline_role_bindings.entity_roles"
            )
        return _selector_to_resolved(role, sel)

    def expand_path(self, pattern: str) -> str:
        """Substitute {role} placeholders with resolved ID strings."""
        def repl(match: re.Match) -> str:
            placeholder = match.group(1)
            sel = self.bindings.entity_roles.get(placeholder)
            if sel is None:
                # Try default product role for `product_role`-style placeholders.
                if placeholder == "product_role" and self.bindings.default_product_role:
                    sel = self.bindings.entity_roles.get(self.bindings.default_product_role)
            if sel is None:
                raise RoleResolutionError(
                    f"path placeholder '{{{placeholder}}}' not bound"
                )
            return _selector_to_id(sel)
        return _PLACEHOLDER_RE.sub(repl, pattern)


def _selector_to_resolved(role: str, sel: PipelineRoleSelector) -> ResolvedRole:
    return ResolvedRole(
        role=role,
        agent_id=sel.agent_id,
        product_id=sel.product_id,
        local=bool(sel.local),
    )


def _selector_to_id(sel: PipelineRoleSelector) -> str:
    if sel.product_id:
        return sel.product_id
    if sel.agent_id:
        return sel.agent_id
    if sel.local:
        return "local"
    raise RoleResolutionError("selector has no concrete target")
