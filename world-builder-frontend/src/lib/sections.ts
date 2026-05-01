import type { Diagnostic, NodeKind, Section } from "./types";

export const SECTIONS: { id: Section; label: string; nodeKinds: NodeKind[] }[] = [
  { id: "scenario", label: "Scenario", nodeKinds: [] },
  { id: "simulation", label: "Simulation", nodeKinds: [] },
  { id: "money", label: "Money", nodeKinds: [] },
  { id: "currency_catalog", label: "Currency Catalog", nodeKinds: [] },
  { id: "fx", label: "FX", nodeKinds: [] },
  { id: "calendars", label: "Calendars", nodeKinds: ["calendar"] },
  { id: "regions", label: "Regions", nodeKinds: ["region"] },
  { id: "pipeline", label: "Pipeline", nodeKinds: ["pipeline_profile"] },
  { id: "world", label: "World", nodeKinds: ["vendor", "product", "pop"] },
  { id: "control_defaults", label: "Control Defaults", nodeKinds: [] },
];

export function nodeKindsForSection(section: Section | null): Set<NodeKind> | null {
  if (section === null) return null;
  const entry = SECTIONS.find((s) => s.id === section);
  if (!entry) return null;
  return new Set(entry.nodeKinds);
}

export function diagnosticBelongsToSection(
  diag: Diagnostic,
  section: Section | null,
): boolean {
  if (section === null) return true;
  if (diag.section) return diag.section === section;
  // Fall back to the path prefix; mirrors the service-side derivation in
  // engine/world_builder/validation.py _section_from_path.
  if (!diag.path) return false;
  const head = diag.path.split(".", 1)[0].split("[", 1)[0];
  return head === section;
}
