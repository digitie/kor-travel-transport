"""Export the backend's OpenAPI schema to a committed file (ADR-005).

Usage (from repo root, backend deps installed):

    uv run --project backend python scripts/export_openapi.py

The output (`docs/openapi.json`) is the machine-readable source of truth for
kor-travel-transport's public `/v1` API contract. Regenerate it whenever a route,
request/response model, or the error envelope changes, and commit the
result in the same PR -- this mirrors kor-travel-map's
`packages/kor-travel-map-api/scripts/export_openapi.py` convention.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def main() -> None:
    # Use a throwaway settings instance so exporting the schema never needs a
    # real database or DATA_GO_KR_SERVICE_KEY -- the OpenAPI schema is static
    # route/model metadata, not something the running app state affects.
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        data_go_kr_service_key=None,
        use_sample_client_when_no_key=True,
        enable_api_docs=True,
    )
    app = create_app(settings)
    schema = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
