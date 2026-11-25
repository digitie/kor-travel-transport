#!/usr/bin/env python3
"""공개·export gateway(12301)와 공개 유가 gateway(12307)의 실제 nginx 동작 probe.

운영 이미지와 같은 방식으로 두 template을 띄운다.
- 12301: compose의 `nginx:1.27-alpine`(아래 NGINX_IMAGE digest로 고정)에 template과 `19-export-allowlist.sh`를
  같은 위치로 mount한다.
- 12307: `deploy/transport-fuel/Dockerfile.gateway`를 template 하나만 든 빌드 문맥으로 빌드한다(FROM은 같은
  digest로 고정). 운영 compose와 같은 `--memory 64m --memory-swap 64m`으로 띄우고 끝에 cgroup memory.peak를 잰다.
두 경우 모두 공식 entrypoint(20-envsubst-on-templates.sh)가 template을 렌더링하고, 렌더링 결과가
template에서 port 변수만 바꾼 문자열과 같은지 확인한다(nginx 변수가 env로 치환되지 않았는지).
그 뒤 `nginx -t`를 실행하고, loopback 127.0.0.1:12302에 띄운 stub upstream으로 동작을 확인한다.

stub과 gateway는 운영처럼 host network를 쓴다(Linux Docker 엔진 필요: CI runner·WSL). 네트워크는
이미지 pull만 쓴다. 실행: `python3 scripts/gateway-probe.py` (12301·12302·12307이 비어 있어야 한다).
12307의 "직접 호출"(HAProxy를 거친 외부 주소) 대역은 source 주소를 127.0.0.2로 묶어 만든다(127.0.0.1만 BFF key다).
환경 문제(port 사용 중·pull·build·기동 실패)는 `SETUP FAIL`, 동작 불일치는 `FAIL`로 표시하고 둘 다 exit 1이다.
확인 항목은 docs/runbooks/request-timing-logs.md "공개 gateway 가드레일"·"CI 검증"과 같다.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import gzip
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = ROOT / "deploy/transport-admin/api-gateway.conf.template"
ADMIN_ALLOWLIST = ROOT / "deploy/transport-admin/19-export-allowlist.sh"
ADMIN_COMPOSE = ROOT / "docker-compose.transport-admin.yml"
FUEL_TEMPLATE = ROOT / "deploy/transport-fuel/api-gateway.conf.template"
FUEL_DOCKERFILE = ROOT / "deploy/transport-fuel/Dockerfile.gateway"
UPSTREAM_PORT = 12302
FUEL_ORIGIN = "https://fuel.digitie.mywire.org"
TEMP_FILE_WARNING = "buffered to a temporary file"
# compose·fuel Dockerfile의 tag와 같은 이미지를 digest로 고정한다(backend/Dockerfile.dagster-gateway와 같은 digest).
NGINX_TAG = "nginx:1.27-alpine"
NGINX_IMAGE = NGINX_TAG + "@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
# 운영 export 동시 상한·공개 유가 places 동시 상한(template과 같은 값이어야 한다).
EXPORT_CONN_LIMIT = 6
FUEL_BFF_CONN_LIMIT = 16
FUEL_DIRECT_CONN_LIMIT = 8
FUEL_MEMORY = "64m"
SLOW_SECONDS = 3.0
BFF_ADDR = "127.0.0.1"
DIRECT_ADDR = "127.0.0.2"
# gzip으로 거의 줄지 않는 채움 문자(멈춘 클라이언트 시험이 실제로 쓰기를 막히게 한다).
FILLER = base64.b64encode(os.urandom(6_100_000))

FAILURES: list[str] = []


class SetupFailure(Exception):
    """probe 대상이 아니라 실행 환경(port·pull·build·기동)이 실패했다."""


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f" :: {detail}"), flush=True)
    if not condition:
        FAILURES.append(name)


# ---------------------------------------------------------------- stub upstream (backend 12302 대역)

class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict] = []

    def add(self, item: dict) -> None:
        with self.lock:
            self.requests.append(item)

    def count(self) -> int:
        with self.lock:
            return len(self.requests)

    def last(self) -> dict:
        with self.lock:
            return self.requests[-1]


RECORDER = Recorder()


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def handle_error(self, request, client_address) -> None:
        # gateway가 멈춘 클라이언트를 끊으면 stub 쓰기가 broken pipe로 끝난다. 정상이다.
        pass


class Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))  # 같은 이름은 마지막 값(Starlette와 같다)
        seen = {
            "path": parts.path,
            "query": parts.query,
            "limit": params.get("limit"),
            "kind": params.get("kind"),
            "listener": self.headers.get_all("X-Transport-Listener") or [],
            "xff": self.headers.get_all("X-Forwarded-For") or [],
        }
        RECORDER.add(seen)
        if parts.path.endswith("/slow") or "slow" in params:
            time.sleep(SLOW_SECONDS)
        status = 200
        headers = {"Content-Type": "application/json", "Server-Timing": "app;dur=1.0, sql;dur=0.5"}
        # backend처럼 places 200에 실제로 받은(마지막) limit을 X-Limit-Applied로 돌려준다(main.py places route).
        if parts.path == "/v1/transport/features/places" and params.get("limit"):
            headers["X-Limit-Applied"] = params["limit"]
            # backend CORS가 Expose를 보내게 바뀌어도 12307이 숨겨 한 줄만 나가는지 본다.
            headers["Access-Control-Expose-Headers"] = "X-Upstream-Only"
        if parts.path.endswith("/backend-busy") or params.get("status") == "503":
            status, headers["Retry-After"] = 503, "60"
        elif params.get("status") == "429":
            status, headers["Retry-After"] = 429, "7"
        body = json.dumps({"stub": True, **seen}).encode()
        big = int(params["big"]) if params.get("big", "").isdigit() else 0
        if big:
            body = body[:-1] + b',"pad":"' + FILLER[:max(0, big - len(body) - 16)] + b'"}'
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_stub() -> StubServer:
    server = StubServer(("127.0.0.1", UPSTREAM_PORT), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------------------------------------------------------------- docker helpers

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def compose_image() -> str:
    text = ADMIN_COMPOSE.read_text(encoding="utf-8")
    block = text.split("  transport-api-gateway:", 1)[1].split("\n  transport-admin-web:", 1)[0]
    return re.search(r"^\s+image:\s*\"?([^\s\"]+)", block, re.M).group(1)


def dockerfile_image() -> str:
    return re.search(r"^FROM\s+(\S+)", FUEL_DOCKERFILE.read_text(encoding="utf-8"), re.M).group(1)


def pull(image: str) -> None:
    if not run(["docker", "image", "inspect", image]).returncode:
        return
    for attempt in (1, 2):
        result = run(["docker", "pull", "-q", image])
        if not result.returncode:
            return
        if attempt == 1:
            time.sleep(5)
    raise SetupFailure(f"docker pull {image}: {result.stderr.strip()}")


class Gateway:
    def __init__(self, name: str, image: str, port: int, port_var: str, template: Path,
                 run_args: list[str]) -> None:
        self.name, self.image, self.port, self.port_var = name, image, port, port_var
        self.template, self.run_args = template, run_args
        self.container = f"gateway-probe-{name}-{uuid.uuid4().hex[:12]}"

    def base_args(self) -> list[str]:
        return ["--network", "host", "-e", f"{self.port_var}={self.port}", *self.run_args]

    def nginx_t(self) -> subprocess.CompletedProcess:
        return run(["docker", "run", "--rm", *self.base_args(), self.image, "nginx", "-t"])

    def start(self) -> None:
        result = run(["docker", "run", "-d", "--name", self.container, *self.base_args(), self.image])
        if result.returncode:
            raise SetupFailure(f"{self.name} 시작 실패: {result.stderr}")
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if request(self.port, "/health")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.2)
        raise SetupFailure(f"{self.name} health 대기 실패: {self.logs()}")

    def rendered(self) -> str:
        return run(["docker", "exec", self.container, "cat", "/etc/nginx/conf.d/default.conf"]).stdout

    def logs(self) -> tuple[str, str]:
        result = run(["docker", "logs", self.container])
        return result.stdout, result.stderr

    def memory(self) -> tuple[int | None, bool, int]:
        peak = run(["docker", "exec", self.container, "cat", "/sys/fs/cgroup/memory.peak"]).stdout.strip()
        oom = run(["docker", "inspect", "-f", "{{.State.OOMKilled}}", self.container]).stdout.strip() == "true"
        workers = run(["docker", "exec", self.container, "sh", "-c", "ps -o args | grep -c '[n]ginx: worker'"])
        return (int(peak) if peak.isdigit() else None), oom, int(workers.stdout.strip() or 0)

    def memory_now(self) -> str:
        stat = run(["docker", "exec", self.container, "sh", "-c",
                    "cat /sys/fs/cgroup/memory.current; grep -E '^(anon|sock|kernel|file) ' /sys/fs/cgroup/memory.stat"])
        rows = stat.stdout.split()
        if not rows or not rows[0].isdigit():
            return "unavailable"
        parts = [f"current={int(rows[0]) / 1048576:.1f}MiB"]
        parts += [f"{key}={int(value) / 1048576:.1f}MiB" for key, value in zip(rows[1::2], rows[2::2])]
        return " ".join(parts)

    def stop(self) -> None:
        run(["docker", "rm", "-f", self.container])


def request(port: int, path: str, headers: list[tuple[str, str]] | None = None,
            method: str = "GET", source: str = BFF_ADDR) -> tuple[int, dict[str, list[str]], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30, source_address=(source, 0))
    try:
        conn.putrequest(method, path, skip_accept_encoding=True)
        for key, value in headers or []:
            conn.putheader(key, value)
        conn.endheaders()
        response = conn.getresponse()
        body = response.read()
        merged: dict[str, list[str]] = {}
        for key, value in response.getheaders():
            merged.setdefault(key.lower(), []).append(value)
        return response.status, merged, body
    finally:
        conn.close()


def upstream_after(port: int, path: str, headers=None):
    before = RECORDER.count()
    status, response_headers, body = request(port, path, headers)
    called = RECORDER.count() > before
    return status, response_headers, body, (RECORDER.last() if called else None)


def concurrent(port: int, path: str, count: int, headers=None, source: str = BFF_ADDR):
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = []
        for index in range(count):
            futures.append(pool.submit(request, port, path, headers, "GET", source))
            if index < count - 1:
                time.sleep(0.02)
        return [future.result() for future in futures]


def problem_of(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------- 공통 시험

def check_render(gw: Gateway) -> None:
    expected = gw.template.read_text(encoding="utf-8").replace("${" + gw.port_var + "}", str(gw.port))
    rendered = gw.rendered()
    diff = "".join(difflib.unified_diff(expected.splitlines(True), rendered.splitlines(True),
                                        "template(port만 치환)", "entrypoint 렌더링"))
    check(f"{gw.name}: entrypoint 렌더링 = template에서 ${{{gw.port_var}}}만 치환", rendered == expected,
          "\n" + diff[:4000])
    check(f"{gw.name}: 렌더링에 남은 ${{...}} 없음", "${" not in rendered)


def check_limit_cap(gw: Gateway, path: str, extra: dict[str, str] | None = None) -> None:
    cases = [("", "900"), ("?limit=5000", "900"), ("?limit=901", "900"), ("?limit=300", "300"),
             ("?limit=900", "900"), ("?limit=10&limit=5000", "10"), ("?bbox=1,2,3,4", "900")]
    for query, expected in cases:
        # 클라이언트가 요청 header로 X-Limit-Applied를 보내도 응답 값은 backend(stub)가 받은 limit 하나다.
        status, headers, _, seen = upstream_after(gw.port, path + query, [("X-Limit-Applied", "5000")])
        ok = status == 200 and seen is not None and seen["limit"] == expected
        if ok and extra:
            ok = all(seen.get(key) == value for key, value in extra.items())
        check(f"{gw.name}: {path}{query or ' (limit 생략)'} → upstream 마지막 limit={expected}", ok, seen)
        check(f"{gw.name}: {path}{query or ' (limit 생략)'} → 응답 X-Limit-Applied=[{expected}] 하나(gateway 통과)",
              status == 200 and headers.get("x-limit-applied") == [expected], headers.get("x-limit-applied"))
    for query in ("?limit=abc", "?limit=0", "?limit=-1", "?limit=0300", "?limit=%35000", "?limit=5.0"):
        status, headers, body, seen = upstream_after(gw.port, path + query)
        problem = problem_of(body)
        ok = (status == 422 and seen is None and "x-limit-applied" not in headers
              and headers.get("content-type", [""])[0].startswith("application/problem+json")
              and set(problem) == {"type", "title", "status", "detail", "instance"}
              and problem.get("status") == 422 and problem.get("instance") == path)
        check(f"{gw.name}: {path}{query} → 422 problem+json 다섯 항목, upstream 미호출", ok,
              (status, headers.get("content-type"), body[:200], seen))


def check_listener(gw: Gateway, paths: list[str]) -> None:
    variants = [
        [],
        [("X-Transport-Listener", "admin")],
        [("x-transport-listener", "admin"), ("X-Transport-Listener", "internal")],
    ]
    for path in paths:
        for sent in variants:
            status, _, _, seen = upstream_after(gw.port, path, sent)
            ok = status == 200 and seen is not None and seen["listener"] == ["public"]
            label = ",".join(value for _, value in sent) or "없음"
            check(f"{gw.name}: {path} 클라이언트 표지({label}) → upstream X-Transport-Listener=[public]", ok, seen)


def check_server_timing(gw: Gateway, hidden: list[str], kept: list[str]) -> None:
    for path in hidden:
        status, headers, _ = request(gw.port, path)
        check(f"{gw.name}: {path} Server-Timing 숨김", status == 200 and "server-timing" not in headers,
              (status, headers.get("server-timing")))
    for path in kept:
        status, headers, _ = request(gw.port, path)
        check(f"{gw.name}: {path} Server-Timing 유지", status == 200 and "server-timing" in headers,
              (status, headers))


def check_access_log(gw: Gateway, with_gz: bool) -> None:
    stdout, _ = gw.logs()
    lines = [line for line in stdout.splitlines() if line and not line.startswith("/docker-entrypoint")
             and "Configuration complete" not in line and not re.match(r"^\d\d-", line)]
    pattern = re.compile(
        r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d \S+ "(GET|HEAD|OPTIONS) [^"? ]*" \d{3} \d+ '
        r"rt=\d+\.\d{3} uct=\S+ uht=\S+ urt=\S+ ust=\S+" + (r" gz=\S+" if with_gz else "") + "$")
    bad = [line for line in lines if not pattern.match(line)]
    check(f"{gw.name}: access log 모든 줄이 timing 형식", bool(lines) and not bad, bad[:3] or "로그 없음")
    check(f"{gw.name}: access log에 query·cursor 값 없음", not any("SECRET" in line or "?" in line for line in lines),
          [line for line in lines if "SECRET" in line][:2])
    check(f"{gw.name}: /health는 access log에 남지 않음", not any('"GET /health"' in line for line in lines))
    rejected = [line for line in lines if '" 422 ' in line]
    check(f"{gw.name}: 422 거절 줄은 uct=- (upstream 미호출)",
          bool(rejected) and all(" uct=- " in line for line in rejected), rejected[:2])


def check_no_temp_file(gw: Gateway) -> None:
    # proxy_max_temp_file_size 0이 있으면 이 경고는 날 수 없다. 이 검사는 그 지시문이 빠지는 회귀를 잡는다
    # (main의 fuel template으로 돌리면 1.25MB 본문에서 실제로 FAIL했다). 버퍼 크기 적정성은 설정 시험이 본다.
    _, stderr = gw.logs()
    warnings = [line for line in stderr.splitlines() if TEMP_FILE_WARNING in line]
    check(f"{gw.name}: '{TEMP_FILE_WARNING}' 경고 없음(temp 지시문 회귀 검출)", not warnings, warnings[:2])


# ---------------------------------------------------------------- gateway별 시험

def probe_admin(gw: Gateway) -> None:
    check_render(gw)
    places = "/v1/transport/features/places"
    check_limit_cap(gw, places)
    check_listener(gw, [places, "/v1/transport/parking-lots", "/v1/transport/fuel/stations"])
    check_server_timing(gw, hidden=["/health", places, "/v1/transport/parking-lots",
                                    "/v1/transport/rail/general/catalog", "/mcp"],
                        kept=["/v1/service/exports/airports"])

    status, _, _, seen = upstream_after(gw.port, "/v1/service/exports/airports?cursor=SECRET",
                                        [("X-Forwarded-For", "10.0.0.1")])
    check("admin: export는 클라이언트 XFF를 지우고 전달", status == 200 and seen and seen["xff"] in ([], [""]), seen)

    size = 1_300_000
    status, _, body = request(gw.port, f"/v1/service/exports/fuel-stations?big={size}")
    check("admin: export 1.3MB 본문 전체 수신", status == 200 and len(body) >= size - 64, (status, len(body)))

    results = concurrent(gw.port, "/v1/service/exports/slow", EXPORT_CONN_LIMIT + 2)
    ok_count = sum(1 for status, _, _ in results if status == 200)
    busy = [(headers, body) for status, headers, body in results if status == 503]
    check(f"admin: export 동시 {EXPORT_CONN_LIMIT + 2}건 → 200 {EXPORT_CONN_LIMIT}건·503 2건",
          ok_count == EXPORT_CONN_LIMIT and len(busy) == 2, [status for status, _, _ in results])
    for headers, body in busy[:1]:
        problem = problem_of(body)
        check("admin: export 503은 Retry-After 10 + problem+json code=EXPORT_BUSY",
              headers.get("retry-after") == ["10"]
              and headers.get("content-type", [""])[0].startswith("application/problem+json")
              and set(problem) == {"type", "title", "status", "detail", "instance", "code"}
              and problem.get("code") == "EXPORT_BUSY" and problem.get("status") == 503
              and problem.get("instance") == "/v1/service/exports/slow", (headers, body[:300]))

    status, headers, body = request(gw.port, "/v1/service/exports/backend-busy")
    check("admin: backend 503은 gateway가 바꾸지 않고 전달(Retry-After 60, stub 본문)",
          status == 503 and headers.get("retry-after") == ["60"] and b'"stub": true' in body,
          (status, headers, body[:120]))

    check_access_log(gw, with_gz=False)
    stdout, _ = gw.logs()
    busy_lines = [line for line in stdout.splitlines() if '"GET /v1/service/exports/slow" 503 ' in line]
    check("admin: export 동시 상한 거절 줄은 uct=-",
          len(busy_lines) == 2 and all(" uct=- " in line for line in busy_lines), busy_lines)
    backend_busy = [line for line in stdout.splitlines() if '"GET /v1/service/exports/backend-busy" 503 ' in line]
    check("admin: backend 503 전달 줄은 ust=503", len(backend_busy) == 1 and " ust=503" in backend_busy[0], backend_busy)
    check_no_temp_file(gw)


def probe_fuel(gw: Gateway) -> None:
    check_render(gw)
    print(f"INFO fuel: 기동 직후 memory {gw.memory_now()}", flush=True)
    places = "/v1/transport/fuel/places"
    check_limit_cap(gw, places, extra={"path": "/v1/transport/features/places", "kind": "fuel_station"})
    check_listener(gw, [places, "/v1/transport/fuel/stations", "/v1/transport/fuel/statistics"])
    check_server_timing(gw, hidden=["/health", places, "/v1/transport/fuel/stations"], kept=[])

    origin = [("Origin", FUEL_ORIGIN)]
    status, headers, _ = request(gw.port, places + "?limit=5000", origin)
    check("fuel: places 200 + CORS 허용 origin 유지",
          status == 200 and headers.get("access-control-allow-origin") == [FUEL_ORIGIN], (status, headers))
    exposed = [name.strip().lower() for name in (headers.get("access-control-expose-headers") or [""])[0].split(",")]
    check("fuel: places 200 X-Limit-Applied=900 + CORS Expose-Headers에 x-limit-applied(다른 출처 화면이 읽음)",
          status == 200 and headers.get("x-limit-applied") == ["900"] and "x-limit-applied" in exposed
          and len(headers.get("access-control-expose-headers") or []) == 1, headers)
    status, headers, _ = request(gw.port, places + "?limit=5000", origin, method="HEAD")
    check("fuel: places HEAD도 X-Limit-Applied=900(proxy_method GET)",
          status == 200 and headers.get("x-limit-applied") == ["900"], (status, headers))

    # 공개 UI 300곳(실측 약 0.40MB)과 상한 900곳(약 1.18MB) 크기 본문. 임시 파일 없이 전부 받아야 한다.
    for size in (420_000, 1_250_000):
        for encoding in ("identity", "gzip"):
            status, headers, body = request(gw.port, f"{places}?limit=300&big={size}",
                                            [("Accept-Encoding", encoding)])
            if encoding == "gzip":
                ok = status == 200 and headers.get("content-encoding") == ["gzip"]
                body = gzip.decompress(body) if ok else body
            else:
                ok = status == 200 and "content-encoding" not in headers
            check(f"fuel: places {size} bytes 본문({encoding}) 전체 수신", ok and len(body) >= size - 64,
                  (status, headers.get("content-encoding"), len(body)))

    status, headers, body = request(gw.port, f"{places}?status=429", origin)
    check("fuel: backend 429는 gateway가 바꾸지 않고 전달(Retry-After 7, stub 본문)",
          status == 429 and headers.get("retry-after") == ["7"] and b'"stub": true' in body, (status, headers))

    def busy_ok(label: str, headers: dict, body: bytes) -> None:
        problem = problem_of(body)
        check(f"fuel: {label} 429는 Retry-After 2 + problem+json 다섯 항목 + CORS",
              headers.get("retry-after") == ["2"]
              and headers.get("content-type", [""])[0].startswith("application/problem+json")
              and set(problem) == {"type", "title", "status", "detail", "instance"}
              and problem.get("status") == 429 and problem.get("instance") == places
              and headers.get("access-control-allow-origin") == [FUEL_ORIGIN]
              and "Retry-After" in (headers.get("access-control-expose-headers") or [""])[0]
              and "x-limit-applied" not in headers,
              (headers, body[:300]))

    for label, source, limit in (("BFF(127.0.0.1)", BFF_ADDR, FUEL_BFF_CONN_LIMIT),
                                 ("직접 호출(127.0.0.2)", DIRECT_ADDR, FUEL_DIRECT_CONN_LIMIT)):
        results = concurrent(gw.port, f"{places}?slow=1", limit + 1, origin, source)
        statuses = sorted(status for status, _, _ in results)
        check(f"fuel: {label} 동시 {limit + 1}건 → 200 {limit}건·429 1건", statuses == [200] * limit + [429], statuses)
        for status, headers, body in results:
            if status == 429:
                busy_ok(f"{label} 상한", headers, body)

    # 읽지 않는(멈춘) 직접 호출이 자기 몫을 다 써도 BFF·다른 경로는 막히지 않고, send_timeout(10초) 뒤 자리가 풀린다.
    # 본문(3MB, gzip으로도 거의 줄지 않음)은 gateway 버퍼(512KiB)와 송신 socket 버퍼(sndbuf 256k, 실제 약 512KiB)보다 커서
    # 쓰기가 실제로 멈춘다. 나머지는 upstream socket 수신 버퍼에 남는다(실제 places 본문은 1.2MB 이하라 이보다 작다).
    stalled = []
    for _ in range(FUEL_DIRECT_CONN_LIMIT):
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        sock.bind((DIRECT_ADDR, 0))
        sock.connect(("127.0.0.1", gw.port))
        sock.sendall(f"GET {places}?limit=900&big=3000000 HTTP/1.1\r\nHost: probe\r\n"
                     "Accept-Encoding: gzip\r\n\r\n".encode())
        stalled.append(sock)
    stalled_at = time.time()
    time.sleep(1.5)
    status, _, _ = request(gw.port, places, origin, source=DIRECT_ADDR)
    check(f"fuel: 멈춘 직접 호출 {FUEL_DIRECT_CONN_LIMIT}건이 몫을 채움 → 다음 직접 호출 429", status == 429, status)
    status, headers, _ = request(gw.port, places, origin, source=BFF_ADDR)
    check("fuel: 직접 호출 몫이 찬 동안 BFF places 200(CORS 포함)",
          status == 200 and headers.get("access-control-allow-origin") == [FUEL_ORIGIN], (status, headers))
    with ThreadPoolExecutor(max_workers=FUEL_BFF_CONN_LIMIT) as pool:
        holders = [pool.submit(request, gw.port, f"{places}?slow=1&big=420000", [("Accept-Encoding", "identity")])
                   for _ in range(FUEL_BFF_CONN_LIMIT)]
        time.sleep(1.0)
        status, _, _ = request(gw.port, places)
        check(f"fuel: BFF 몫도 참 → {FUEL_BFF_CONN_LIMIT + 1}번째 BFF 429(두 몫 모두 가득)", status == 429, status)
        status, _, _ = request(gw.port, "/v1/transport/fuel/stations")
        check("fuel: places 두 몫이 모두 찬 동안에도 stations 200", status == 200, status)
        print(f"INFO fuel: 두 몫이 찬 동안 memory {gw.memory_now()}", flush=True)
        held = [future.result()[0] for future in holders]
        check(f"fuel: BFF 몫을 채운 {FUEL_BFF_CONN_LIMIT}건은 모두 200", held == [200] * FUEL_BFF_CONN_LIMIT, held)
    freed = None
    while time.time() - stalled_at < 25:
        if request(gw.port, places, source=DIRECT_ADDR)[0] == 200:
            freed = time.time() - stalled_at
            break
        time.sleep(0.5)
    check("fuel: 멈춘 직접 호출은 send_timeout(10초) 뒤 끊겨 몫이 풀림(8~16초)",
          freed is not None and 8 <= freed <= 16, freed)
    for sock in stalled:
        sock.close()

    _, stderr = gw.logs()
    limited = [line for line in stderr.splitlines() if "limiting connections by zone" in line]
    check("fuel: 상한 거절은 error log에 [warn] limiting connections by zone 줄(두 zone)",
          any("[warn]" in line and '"fuel_places_direct"' in line for line in limited)
          and any("[warn]" in line and '"fuel_places_bff"' in line for line in limited), limited[:2])
    stdout, _ = gw.logs()
    rejected = [line for line in stdout.splitlines() if '"GET /v1/transport/fuel/places" 429 ' in line]
    gateway_busy = [line for line in rejected if " uct=- " in line]
    backend_busy = [line for line in rejected if " ust=429" in line]
    check("fuel: gateway 상한 429 줄은 uct=- ust=-", len(gateway_busy) >= 4
          and all(" ust=- " in line for line in gateway_busy), gateway_busy[:2])
    check("fuel: backend 429 전달 줄은 ust=429이고 uct 값이 있음",
          len(backend_busy) == 1 and " uct=- " not in backend_busy[0], backend_busy)
    check("fuel: 429 줄은 gateway 상한 또는 backend 전달 둘 중 하나",
          len(rejected) == len(gateway_busy) + len(backend_busy), rejected)

    check_access_log(gw, with_gz=True)
    check_no_temp_file(gw)
    peak, oom, workers = gw.memory()
    print(f"INFO fuel: memory.peak={peak} bytes ({(peak or 0) / 1048576:.1f}MiB), workers={workers}, "
          f"limit={FUEL_MEMORY}", flush=True)
    check(f"fuel: {FUEL_MEMORY} 한도에서 OOM 없음", not oom and peak is not None and peak < 64 * 1048576, (peak, oom))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--admin-port", type=int, default=12301)
    parser.add_argument("--fuel-port", type=int, default=12307)
    parser.add_argument("--keep", action="store_true", help="끝난 뒤 컨테이너를 지우지 않는다(디버그)")
    args = parser.parse_args()

    started = time.time()
    fuel_tag = f"gateway-probe-fuel:{uuid.uuid4().hex[:12]}"
    stub = None
    gateways: list[Gateway] = []
    try:
        for port in (UPSTREAM_PORT, args.admin_port, args.fuel_port):
            if not port_free(port):
                raise SetupFailure(f"port {port} 사용 중: 비어 있는 환경(CI runner 등)에서 실행한다")
        admin_image, fuel_base = compose_image(), dockerfile_image()
        check(f"compose 12301 gateway·fuel Dockerfile이 probe 고정 이미지와 같은 tag({NGINX_TAG})",
              admin_image.split("@")[0] == NGINX_TAG and fuel_base.split("@")[0] == NGINX_TAG, (admin_image, fuel_base))
        pull(NGINX_IMAGE)

        # fuel 이미지는 운영과 같은 Dockerfile로 template 하나만 든 문맥에서 빌드한다. FROM tag를 고정 digest로 돌린다.
        with tempfile.TemporaryDirectory() as context:
            target = Path(context) / "deploy/transport-fuel"
            target.mkdir(parents=True)
            shutil.copy(FUEL_TEMPLATE, target / FUEL_TEMPLATE.name)
            built = run(["docker", "buildx", "build", "--load", "-q", "-t", fuel_tag,
                         "--build-context", f"{fuel_base}=docker-image://{NGINX_IMAGE}",
                         "-f", str(FUEL_DOCKERFILE), context])
            if built.returncode:
                raise SetupFailure(f"fuel gateway build: {built.stderr[-1500:]}")

        admin = Gateway("admin", NGINX_IMAGE, args.admin_port, "TRANSPORT_PUBLIC_API_PORT", ADMIN_TEMPLATE, [
            "-e", "TRANSPORT_EXPORT_CONSUMER_CIDR=127.0.0.1/32", "-e", "TRANSPORT_MCP_CONSUMER_CIDR=127.0.0.1/32",
            "-v", f"{ADMIN_TEMPLATE}:/etc/nginx/templates/default.conf.template:ro",
            "-v", f"{ADMIN_ALLOWLIST}:/docker-entrypoint.d/19-export-allowlist.sh:ro",
        ])
        # 운영(ODROID M1S, 4코어 → worker_processes auto = 4)과 같은 worker 수로 띄운다.
        cpuset = ["--cpuset-cpus", "0-3"] if (os.cpu_count() or 1) >= 4 else []
        fuel = Gateway("fuel", fuel_tag, args.fuel_port, "TRANSPORT_FUEL_API_PORT", FUEL_TEMPLATE,
                       ["--memory", FUEL_MEMORY, "--memory-swap", FUEL_MEMORY, *cpuset])

        stub = start_stub()
        for gw in (admin, fuel):
            result = gw.nginx_t()
            check(f"{gw.name}: nginx -t ({gw.image})", result.returncode == 0 and "test is successful" in result.stderr,
                  result.stderr[-800:])
        if not FAILURES:
            for gw in (admin, fuel):
                gateways.append(gw)
                gw.start()
            probe_admin(admin)
            probe_fuel(fuel)
    except SetupFailure as error:
        print(f"SETUP FAIL {error}", flush=True)
        return 1
    finally:
        if stub is not None:
            stub.shutdown()
        if not args.keep:
            for gw in gateways:
                gw.stop()
            run(["docker", "image", "rm", fuel_tag])
    print(f"\n{'FAIL' if FAILURES else 'OK'}: {len(FAILURES)} failure(s), {time.time() - started:.1f}s", flush=True)
    for name in FAILURES:
        print("  - " + name)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
