"""저장 데이터 API의 본문 수신 완료 시간을 같은 호스트에서 측정한다."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DEFAULT_PATHS = (
    "/v1/parking/current",
    "/v1/parking/history?airport_code=GMP&days=7",
    "/v1/parking/history?airport_code=GMP&days=30",
    "/v1/dashboard/bootstrap",
    "/v1/dashboard/analytics?airport_code=GMP",
    "/v1/parking/analytics/holiday-patterns?airport_code=GMP",
    "/v1/transport/highways/traffic?days=7&limit=1000",
    "/v1/transport/highways/incidents?days=7&limit=1000",
    "/v1/transport/fuel/stations?days=7&limit=1000",
    "/v1/transport/features/places?kind=fuel_station&limit=300",
    "/v1/transport/features/places?kind=fuel_station&limit=5000",
    "/v1/transport/features/places?kind=fuel_station&product_code=B027&limit=300",
    "/v1/transport/features/places?kind=ferry_port&limit=5000",
    "/v1/transport/features/places?kind=rail_station&limit=5000",
    "/v1/transport/features/places?kind=bus_terminal&limit=5000",
    "/v1/transport/bus/terminals?service_type=express&limit=100",
    "/v1/transport/statistics?days=7",
    "/v1/transport/statistics?days=90",
    "/v1/transport/providers",
    "/v1/transport/collector-status",
)


def default_paths() -> tuple[str, ...]:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    start = today - timedelta(days=89)
    return (*DEFAULT_PATHS,
            f"/v1/parking/analytics/timeseries?airport_code=GMP&start_date={start}&end_date={today}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:14001")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--threshold-seconds", type=float, default=1.0)
    parser.add_argument("--path", action="append", help="기본 목록 대신 검사할 경로. 반복 가능")
    parser.add_argument("--strict", action="store_true", help="한 번이라도 목표를 넘으면 실패")
    args = parser.parse_args()
    if args.samples < 1 or args.threshold_seconds <= 0:
        parser.error("samples와 threshold-seconds는 양수여야 합니다")
    paths = args.path or default_paths()
    failed = False
    print("상태\t최대초\t중앙값초\t본문KB\t경로", flush=True)
    for path in paths:
        if not path.startswith("/") or path.startswith("//"):
            parser.error("--path는 상대 API 경로여야 합니다")
        durations: list[float] = []
        body_size = 0
        status = 0
        for _ in range(args.samples):
            request = Request(args.base_url.rstrip("/") + path, headers={"Accept": "application/json"})
            started = time.perf_counter()
            try:
                with urlopen(request, timeout=30) as response:
                    body_size = len(response.read())
                    status = response.status
            except (HTTPError, URLError, TimeoutError) as exc:
                print(f"오류\t-\t-\t-\t{path}: {exc}", flush=True)
                failed = True
                break
            durations.append(time.perf_counter() - started)
        if not durations:
            continue
        maximum = max(durations)
        print(f"{status}\t{maximum:.3f}\t{statistics.median(durations):.3f}\t{body_size / 1024:.0f}\t{path}", flush=True)
        failed |= status != 200 or maximum > args.threshold_seconds
    return int(failed and args.strict)


if __name__ == "__main__":
    sys.exit(main())
