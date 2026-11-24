"""배포 직후 서빙 중인 backend 프로세스에 loopback으로 Map export를 한 번씩 불러 데우고 설정을 확인한다.

backend 컨테이너 안에서만 실행한다.

    docker exec <backend> python -I -B -m app.deploy.export_smoke --port 12302

- 포트: 운영 compose의 backend는 host network로 `PUBLIC_API_PORT`(기본 12302)에서 듣는다. 그래서 컨테이너 안의
  127.0.0.1:<그 포트>가 서빙 프로세스다(허용 peer 기본값도 loopback). bridge network로 띄운 compose(기본 이미지
  포트 8000)라면 `--port 8000`을 넘긴다.
- 토큰은 컨테이너 env(`TRANSPORT_SERVICE_EXPORT_TOKEN`)에서만 읽는다. argv·출력·로그에 넣지 않는다.
- 출력은 경로·상태·(503이면) problem `code`·지연뿐이다(본문·헤더 값 없음).
- 표준 라이브러리만 쓴다. 512MiB backend cgroup 안에서 앱 전체를 import하지 않는다.
- 서빙 프로세스의 지문 memo·커넥션·컴파일 캐시를 데우는 유일한 경로다(다른 프로세스의 준비는 DB 본문만 데운다).

종료 코드(우선순위 순):
3 = 설정 불일치 — 토큰이 설정됐는데 404, 또는 토큰이 32자보다 짧아 export가 닫혀 있다(토큰·허용 peer·라우터 확인).
1 = Map T3(철도역·여객선) 첫 페이지가 2xx가 아니거나, 어느 경로든 시간 초과·연결 실패다 — 다음 Map 호출이 요청 안에서
    다시 구성하거나 503을 받을 수 있다(연결 실패는 포트·기동 상태 확인).
5 = T1 일부가 2xx가 아니다 — 대개 원천이 최신이 아니거나 비활성(problem `code`로 구분), 배포 문제가 아니다.
4 = 토큰이 없어 건너뜀 — export가 의도적으로 닫혀 있다(이 확인은 하지 않았다).
0 = 모두 2xx.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
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
EXIT_OK, EXIT_T3_FAILED, EXIT_CONFIG, EXIT_SKIPPED, EXIT_T1_UNAVAILABLE = 0, 1, 3, 4, 5
_PROBLEM_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_MAX_ERROR_BODY = 4096


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _problem_code(body: bytes) -> str | None:
    """problem+json 본문의 고정 `code`만 읽는다(형식이 다르면 없음). detail 등 다른 값은 출력하지 않는다."""
    try:
        code = json.loads(body[:_MAX_ERROR_BODY]).get("code")
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, str) and _PROBLEM_CODE.fullmatch(code) else None


def _call(host: str, port: int, path: str, token: str, timeout: float) -> tuple[str, str | None, int]:
    started = monotonic()
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    code = None
    try:
        connection.request("GET", PREFIX + path, headers={TOKEN_HEADER: token, "Accept-Encoding": "gzip"})
        response = connection.getresponse()
        if 200 <= response.status < 300:
            response.read()  # 본문 직렬화·전송까지 끝까지 데운다. 내용은 버린다.
        else:
            code = _problem_code(response.read(_MAX_ERROR_BODY))
        status = str(response.status)
    except TimeoutError:
        status = "timeout"
    except (OSError, http.client.HTTPException) as exc:
        status = type(exc).__name__
    finally:
        connection.close()
    return status, code, round((monotonic() - started) * 1000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="배포 직후 loopback export 확인·warm(best-effort)")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=12302)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not 1 <= args.timeout_seconds <= 120:
        parser.error("--port는 1~65535, --timeout-seconds는 1~120이어야 합니다")
    token = os.environ.get(TOKEN_ENV) or ""
    if not token:
        print("export smoke skipped: service export token is not configured (exports are intentionally closed)",
              flush=True)
        return EXIT_SKIPPED
    if len(token) < MIN_TOKEN_LENGTH:
        print(f"export smoke: service export token is set but shorter than {MIN_TOKEN_LENGTH} characters; "
              "exports stay closed (404)", flush=True)
        return EXIT_CONFIG
    routes = [(path, "T1") for path in T1_ROUTES]
    if _enabled(os.environ.get("TRANSPORT_MAP_CURRENT_ENABLED")):
        routes += [(path, "T3") for path in T3_ROUTES]
    else:
        print("T3 routes skipped: TRANSPORT_MAP_CURRENT_ENABLED is off", flush=True)
    counts = {"ok": 0, "not_found": 0, "unreachable": 0, "t3_failed": 0, "t1_unavailable": 0}
    for path, tier in routes:
        status, code, latency_ms = _call(args.host, args.port, path, token, args.timeout_seconds)
        suffix = f" {code}" if code else ""
        print(f"GET {PREFIX}{path.split('?', 1)[0]} {status}{suffix} {latency_ms}ms", flush=True)
        if status.isdigit() and 200 <= int(status) < 300:
            counts["ok"] += 1
        elif status == "404":
            counts["not_found"] += 1
        elif not status.isdigit():
            counts["unreachable"] += 1
        elif tier == "T3":
            counts["t3_failed"] += 1
        else:
            counts["t1_unavailable"] += 1
    del token
    print("export smoke summary: " + " ".join(f"{key}={value}" for key, value in counts.items()), flush=True)
    if counts["not_found"]:
        return EXIT_CONFIG
    if counts["t3_failed"] or counts["unreachable"]:
        return EXIT_T3_FAILED
    if counts["t1_unavailable"]:
        return EXIT_T1_UNAVAILABLE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
