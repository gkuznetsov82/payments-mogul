"""World Builder FastAPI service (spec 74 §v0_viewer, spec 75 §P0).

Standalone app surface (separate from the simulation engine API). Exposes:

- POST /validate    -> ValidationReport envelope
- POST /normalize   -> NormalizationReport envelope (canonical YAML)
- POST /analyze     -> AnalysisReport envelope (graph + unresolved refs)
- GET  /health      -> liveness probe
- GET  /            -> minimal browser scaffold (load/validate/visualize/export)
- GET  /ui/*        -> static UI assets

Validation/normalization is authoritative on the service side per spec 74; the
UI is intentionally thin and never duplicates validation logic.

Run locally:
    uvicorn engine.world_builder.service:app --port 8090
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.world_builder.analyze import analyze_yaml_string
from engine.world_builder.normalize import normalize_yaml_string
from engine.world_builder.validation import validate_yaml_string


SUPPORTED_CONFIG_VERSIONS = ["v0"]
SUPPORTED_PIPELINE_SCHEMA_VERSIONS = ["v2_foundations", "v3_runtime"]


class YamlPayload(BaseModel):
    """Request envelope for /validate, /normalize, /analyze.

    YAML is sent as a string so the contract remains transport-agnostic
    (browser file upload, CLI cat, etc.).
    """

    yaml_text: str


app = FastAPI(
    title="Payments Mogul World Builder",
    description=(
        "Standalone World Builder service (v0_viewer). "
        "Provides authoritative YAML validation, deterministic normalization, "
        "and topology analysis for world configs. See spec 74."
    ),
)


_UI_DIR = Path(__file__).parent / "ui"
if _UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR)), name="ui")


@app.get("/")
async def index() -> Any:
    """Serve the minimal builder UI scaffold (or a JSON pointer if absent)."""
    index_path = _UI_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return JSONResponse({
        "service": "payments-mogul-world-builder",
        "ui": "scaffold not bundled; POST YAML to /validate, /normalize, /analyze",
    })


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe + supported-schema-version surfacing (spec 74 §Compatibility)."""
    return {
        "status": "ok",
        "service": "world_builder",
        "binding_level": "v0_viewer",
        "supported_config_versions": SUPPORTED_CONFIG_VERSIONS,
        "supported_pipeline_schema_versions": SUPPORTED_PIPELINE_SCHEMA_VERSIONS,
    }


def _read_yaml_payload_from_body(payload: Optional[YamlPayload], raw_body: bytes) -> str:
    """Accept either a JSON envelope `{ yaml_text: "..." }` or a raw YAML body.

    Browser uploads via fetch usually send JSON; curl/httpx callers may send the
    YAML directly. We support both for ergonomics.
    """
    if payload is not None and payload.yaml_text:
        return payload.yaml_text
    if raw_body:
        try:
            return raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, f"Body must be UTF-8: {exc}")
    raise HTTPException(400, "Missing YAML payload (send JSON {yaml_text} or raw YAML body)")


async def _extract_yaml(request: Request) -> str:
    """Pull a YAML string from JSON envelope or raw body without double-reading."""
    body = await request.body()
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            data = await _safe_json(body)
        except ValueError as exc:
            raise HTTPException(400, f"Invalid JSON body: {exc}")
        if not isinstance(data, dict) or "yaml_text" not in data:
            raise HTTPException(400, "JSON body must include 'yaml_text' string field")
        text = data.get("yaml_text")
        if not isinstance(text, str):
            raise HTTPException(400, "'yaml_text' must be a string")
        return text
    # Treat anything else (text/yaml, application/x-yaml, octet-stream, none) as raw YAML.
    if not body:
        raise HTTPException(400, "Empty request body")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, f"Body must be UTF-8: {exc}")


async def _safe_json(body: bytes) -> Any:
    import json
    return json.loads(body.decode("utf-8"))


@app.post("/validate")
async def validate_endpoint(request: Request) -> dict[str, Any]:
    """Authoritative YAML validation (spec 74 §Validation ownership)."""
    yaml_text = await _extract_yaml(request)
    report = validate_yaml_string(yaml_text)
    return report.to_dict()


@app.post("/normalize")
async def normalize_endpoint(request: Request) -> dict[str, Any]:
    """Deterministic canonical YAML emission (spec 74 §Normalization ownership)."""
    yaml_text = await _extract_yaml(request)
    report = normalize_yaml_string(yaml_text)
    return report.to_dict()


@app.post("/analyze")
async def analyze_endpoint(request: Request) -> dict[str, Any]:
    """Topology graph + unresolved-reference diagnostics (spec 74 §Visualization)."""
    yaml_text = await _extract_yaml(request)
    report = analyze_yaml_string(yaml_text)
    return report.to_dict()
