"""Export the backend's OpenAPI schema to a committed file (ADR-005).

Usage (from repo root, backend deps installed):

    uv run --project backend python scripts/export_openapi.py
    uv run --project backend python scripts/export_openapi.py --check   # CI: 커밋본이 최신인지만 확인

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


def render() -> str:
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
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(f"{OUTPUT_PATH} is stale: run scripts/export_openapi.py and commit the result", file=sys.stderr)
            return 1
        print(f"{OUTPUT_PATH} is up to date")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({len(json.loads(rendered).get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
