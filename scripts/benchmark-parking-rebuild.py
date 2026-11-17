"""격리 *_bench DB에서 실제 주차 캐시 재구성 중 작은 읽기의 p95를 잰다.

운영 DB에서는 실행하지 않는다. 합성 표본은 운영 호스트의 채택 판정을 대체하지 않는다.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from time import perf_counter, sleep

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def p95(values):
    return sorted(values)[max(0, int(len(values)*0.95+0.9999)-1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100000)
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
    from app.services.parking_history_cache import ParkingHistoryReadCache
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    app = create_app(Settings(database_url=url, seed_sample_data=True, enable_scheduler=False,
                             data_go_kr_service_key=None, use_sample_client_when_no_key=True))
    paths = ("/health", "/v1/airports")
    with TestClient(app) as client:
        async def seed():
            async with app.state.session_factory() as session:
                await session.execute(text("""INSERT INTO parking_snapshots
                    (airport_id, parking_lot_id, observed_at, collected_at, source,
                     occupied_spaces, total_spaces, available_spaces)
                    SELECT lot.airport_id, lot.id, CAST(:now AS timestamptz) - n * interval '3 seconds', CAST(:now AS timestamptz),
                           'read_performance_fixture', 50, 100, 50
                    FROM (SELECT id, airport_id FROM parking_lots ORDER BY id LIMIT 1) lot
                    CROSS JOIN generate_series(1, :rows) n"""), {"now": now_utc(), "rows": args.rows})
                await session.commit()
        asyncio.run(seed())
        values = {phase: {path: [] for path in paths} for phase in ("idle", "rebuild")}
        def sample(phase):
            for path in paths:
                started = perf_counter()
                response = client.get(path)
                elapsed = perf_counter()-started
                assert response.status_code == 200, response.status_code
                values[phase][path].append(elapsed)
        for _ in range(50):
            sample("idle"); sleep(0.01)
        cache = ParkingHistoryReadCache(app.state.session_factory)
        started = perf_counter()
        future = client.portal.start_task_soon(cache.refresh_once)
        while not future.done():
            sample("rebuild"); sleep(0.01)
        future.result()
        duration = perf_counter()-started
        summary = {path: {"idle_p95_seconds": p95(values["idle"][path]),
                          "rebuild_p95_seconds": p95(values["rebuild"][path]),
                          "ratio": p95(values["rebuild"][path])/p95(values["idle"][path])}
                   for path in paths}
        args.output.write_text(json.dumps({"scope": "local_synthetic_only", "rows_added": args.rows,
            "rebuild_wall_seconds": duration, "samples": values, "summary": summary}, indent=2)+"\n")
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
