"""격리 PostgreSQL의 합성 표본으로 다중 지도 CPU·SQL·본문 동등성을 비교한다.

TEST_DATABASE_URL은 loopback의 *_bench 전용 DB여야 한다. 운영 접속·원천 API 호출은 없다.
같은 작업 트리의 새 코드와 --baseline-ref의 main.py를 교대로 실행한다.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter, process_time

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="origin/main")
    parser.add_argument("--count", type=int, default=800)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost"} or not parsed.database.endswith("_bench"):
        parser.error("loopback *_bench 전용 DB만 허용합니다")
    os.environ["DATABASE_URL"] = url
    os.environ["KOR_TRAVEL_TRANSPORT_TEST_DATABASE"] = "1"
    from app.core.config import Settings
    from app.core.read_timing import ReadTimingMiddleware
    from app.core.time_utils import now_utc
    from app.main import create_app
    from app.models import FuelPriceSnapshot, FuelStation
    from app.services.transport_collection import upsert_latest_fuel_prices
    from fastapi.testclient import TestClient
    from sqlalchemy import event, insert
    from test_read_performance import seed_places
    settings = Settings(database_url=url, seed_sample_data=True, enable_scheduler=False,
                        data_go_kr_service_key=None, use_sample_client_when_no_key=True)
    app = create_app(settings)
    with TestClient(app) as candidate:
        async def seed():
            async with app.state.session_factory() as session:
                await seed_places(session, args.count)
                now = now_utc()
                ids = (await session.scalars(insert(FuelStation).returning(FuelStation.id), [
                    {"source": "opinet", "identity_key": f"bench-{i}", "name": f"주유소-{i}",
                         "longitude": 127.1, "latitude": 37.5, "query_level": "sigungu", "source_kinds": [], "sido_value": "11", "sido_name": "서울",
                         "sigungu_value": "110", "sigungu_name": "검산구",
                         "first_seen_at": now, "last_seen_at": now} for i in range(args.count)])).all()
                await session.execute(insert(FuelPriceSnapshot), [
                    {"fuel_station_id": identity, "source": "opinet", "product_code": code, "price": 1700,
                         "observed_at": now, "collected_at": now}
                    for identity in ids for code in ("B027", "B034", "D047", "C004", "K015")])
                await upsert_latest_fuel_prices(session)
                await session.commit()
        asyncio.run(seed())
        original = subprocess.check_output(["git", "show", f"{args.baseline_ref}:backend/app/main.py"], cwd=ROOT)
        baseline_file = ROOT / ".perf-baseline-main.py"
        baseline_file.write_bytes(original)
        spec = importlib.util.spec_from_file_location("app.baseline_main", baseline_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        baseline_app = module.create_app(settings.model_copy(update={"seed_sample_data": False}))
        baseline_app.add_middleware(ReadTimingMiddleware)
        samples, bodies = [], {}
        with TestClient(baseline_app) as baseline:
            for label, client in [("baseline", baseline), ("candidate", candidate)] * 4:
                statements = []
                def seen(conn, cursor, sql, params, context, many, statements=statements):
                    statements.append(sql)
                engine = client.app.state.engine.sync_engine
                event.listen(engine, "before_cursor_execute", seen)
                started, cpu = perf_counter(), process_time()
                try:
                    response = client.get("/v1/transport/features/places?limit=5000")
                finally:
                    event.remove(engine, "before_cursor_execute", seen)
                elapsed, cpu_elapsed = perf_counter()-started, process_time()-cpu
                assert response.status_code == 200, response.status_code
                body = response.json(); body.pop("generated_at")
                bodies[label] = body
                samples.append({"variant": label, "wall_seconds": elapsed, "cpu_seconds": cpu_elapsed,
                                    "sql_count": len(statements), "items": len(body["items"]),
                                    "server_timing": response.headers.get("server-timing")})
            assert bodies["baseline"] == bodies["candidate"], "본문·총계·출처·truncated가 달라졌습니다"
        summary = {label: {key: statistics.median([sample[key] for sample in samples
                    if sample["variant"] == label]) for key in ("wall_seconds", "cpu_seconds", "sql_count")}
                   for label in ("baseline", "candidate")}
        args.output.write_text(json.dumps({"fixture_rows_per_kind": args.count, "equivalent": True,
                                  "samples": samples, "medians": summary}, ensure_ascii=False, indent=2)+"\n")
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
