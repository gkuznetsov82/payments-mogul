import type {
  AnalysisReport,
  NormalizationReport,
  ValidationReport,
} from "./types";

async function postYaml<T>(path: string, yamlText: string): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml_text: yamlText }),
  });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export const api = {
  validate: (yaml: string) => postYaml<ValidationReport>("/validate", yaml),
  normalize: (yaml: string) => postYaml<NormalizationReport>("/normalize", yaml),
  analyze: (yaml: string) => postYaml<AnalysisReport>("/analyze", yaml),
};
