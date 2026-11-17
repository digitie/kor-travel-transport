"""격리 *_bench DB의 합성 참조 본문으로 warm 304 비용과 페이지 읽기 0회를 검증한다."""
import argparse
import asyncio
import json
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter, process_time
from uuid import uuid4

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost"} or not parsed.database.endswith("_bench"):
        parser.error("loopback *_bench 전용 DB만 허용합니다")
    os.environ["DATABASE_URL"] = url
    os.environ["KOR_TRAVEL_TRANSPORT_TEST_DATABASE"] = "1"
    from app.core.config import Settings
    from app.core.time_utils import now_utc
    from app.main import create_app
    from app.models import (
        KricStationMappingRegistry,
        RailStationReference,
        ReferenceExportState,
    )
    from app.services.rail_maritime_collection import KRIC_FILE_SOURCE
    from fastapi.testclient import TestClient
    from sqlalchemy import event, select, update
    token = "synthetic-benchmark-token-" * 2
    app = create_app(Settings(database_url=url, seed_sample_data=False, enable_scheduler=False,
        data_go_kr_service_key=None, use_sample_client_when_no_key=True,
        transport_map_current_enabled=True, release_sha="local-reference-304-benchmark",
        transport_service_export_token=token))
    with TestClient(app, client=("127.0.0.1", 20000)) as client:
        async def seed():
            async with app.state.session_factory() as session:
                now = now_utc()
                await session.execute(update(RailStationReference).values(source=KRIC_FILE_SOURCE, last_seen_at=now))
                ids = list((await session.scalars(select(RailStationReference.id).order_by(RailStationReference.id))).all())
                session.add(ReferenceExportState(kind="rail-station", scope_key="nationwide", generation=str(uuid4()),
                    attempt_order=1, confirmed_at=now, last_attempt_at=now, member_ids=ids, proof={"complete": True}))
                await session.merge(KricStationMappingRegistry(id=1, catalog_json=[], catalog_sha256="a"*64,
                    automatic_mappings_json=[], manual_mappings_json=[], updated_at=now))
                await session.commit()
        asyncio.run(seed())
        path = "/v1/service/exports/rail-stations?limit=1000"
        headers = {"x-kor-travel-transport-service-token": token}
        first = client.get(path, headers=headers)
        assert first.status_code == 200, first.status_code
        warm = client.get(path, headers=headers)
        assert warm.status_code == 200
        headers["If-None-Match"] = first.headers["ETag"]
        samples = []
        for _ in range(5):
            statements = []
            def seen(conn, cursor, sql, parameters, context, many, statements=statements):
                statements.append(sql)
            engine = app.state.engine.sync_engine
            event.listen(engine, "before_cursor_execute", seen)
            started, cpu = perf_counter(), process_time()
            try:
                response = client.get(path, headers=headers)
            finally:
                event.remove(engine, "before_cursor_execute", seen)
            page_reads = sum("reference_export_artifact_items" in sql or "service_export_snapshot_items" in sql
                             for sql in statements)
            assert response.status_code == 304 and not page_reads
            samples.append({"wall_seconds": perf_counter()-started, "cpu_seconds": process_time()-cpu,
                            "sql_count": len(statements), "page_reads": page_reads})
        result = {"scope": "local_synthetic_only", "items": len(first.json()["items"]), "samples": samples,
                  "median_seconds": statistics.median(row["wall_seconds"] for row in samples)}
        args.output.write_text(json.dumps(result, indent=2)+"\n")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
