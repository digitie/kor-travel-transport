"""배포 직후 서빙 중인 backend 프로세스에 loopback으로 Map export를 한 번씩 불러 데우고 설정을 확인한다.

backend 컨테이너 안에서만 실행한다(host network, 허용 peer는 loopback).

    docker exec <backend> python -I -B -m app.deploy.export_smoke --port 12302

- 토큰은 컨테이너 env(`TRANSPORT_SERVICE_EXPORT_TOKEN`)에서만 읽는다. argv·출력·로그에 넣지 않는다.
- 출력은 경로·상태·지연뿐이다(본문·헤더 값 없음).
- 표준 라이브러리만 쓴다. 512MiB backend cgroup 안에서 앱 전체를 import하지 않는다.
- 서빙 프로세스의 지문 memo·커넥션·컴파일 캐시를 데우는 유일한 경로다(다른 프로세스의 준비는 DB 본문만 데운다).

종료 코드: 0 = 모두 2xx(또는 토큰 미설정으로 건너뜀), 3 = 토큰이 설정됐는데 404(토큰·허용 peer·라우터 설정 불일치),
1 = 그 밖의 실패(503·시간 초과·연결 실패). 배포 스크립트는 어느 쪽이든 경고만 남긴다.
"""
from __future__ import annotations

import argparse
import http.client
import os
import sys
from time import monotonic

TOKEN_ENV = "TRANSPORT_SERVICE_EXPORT_TOKEN"
#: `app.service_exports.SERVICE_TOKEN_HEADER`·`MIN_SERVICE_TOKEN_LENGTH`와 같아야 한다(시험이 대조한다).
TOKEN_HEADER = "x-kor-travel-transport-service-token"
MIN_TOKEN_LENGTH = 32
PREFIX = "/v1/service/exports"
#: Map이 실제로 부르는 T1(limit=1)과 T3 첫 페이지. T3는 준비된 본문이 있으면 handle만 만든다.
T1_ROUTES = (
    "/fuel-stations?limit=1",
    "/rest-areas?limit=1",
    "/rest-area-fuel-prices?limit=1",
    "/highway-incidents/active",
    "/airports",
)
T3_ROUTES = (
    "/rail-stations?limit=1",
    "/ferry-ports?limit=1",
)
EXIT_OK, EXIT_WARN, EXIT_CONFIG = 0, 1, 3


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _call(host: str, port: int, path: str, token: str, timeout: float) -> tuple[str, int]:
    started = monotonic()
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", PREFIX + path, headers={TOKEN_HEADER: token, "Accept-Encoding": "gzip"})
        response = connection.getresponse()
        response.read()  # 본문 직렬화·전송까지 끝까지 데운다. 내용은 버린다.
        status = str(response.status)
    except TimeoutError:
        status = "timeout"
    except (OSError, http.client.HTTPException) as exc:
        status = type(exc).__name__
    finally:
        connection.close()
    return status, round((monotonic() - started) * 1000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="배포 직후 loopback export 확인·warm(best-effort)")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=12302)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not 1 <= args.timeout_seconds <= 120:
        parser.error("--port는 1~65535, --timeout-seconds는 1~120이어야 합니다")
    token = os.environ.get(TOKEN_ENV) or ""
    if len(token) < MIN_TOKEN_LENGTH:
        # 토큰이 없으면 export는 의도적으로 닫혀 있다(404). 설정 오류로 보지 않는다.
        print("export smoke skipped: service export token is not configured", flush=True)
        return EXIT_OK
    routes = list(T1_ROUTES)
    if _enabled(os.environ.get("TRANSPORT_MAP_CURRENT_ENABLED")):
        routes += T3_ROUTES
    else:
        print("T3 routes skipped: TRANSPORT_MAP_CURRENT_ENABLED is off", flush=True)
    exit_code = EXIT_OK
    for path in routes:
        status, latency_ms = _call(args.host, args.port, path, token, args.timeout_seconds)
        print(f"GET {PREFIX}{path.split('?', 1)[0]} {status} {latency_ms}ms", flush=True)
        if status == "404":
            exit_code = EXIT_CONFIG
        elif not (status.isdigit() and 200 <= int(status) < 300) and exit_code == EXIT_OK:
            exit_code = EXIT_WARN
    del token
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
