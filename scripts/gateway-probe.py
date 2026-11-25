#!/usr/bin/env python3
"""공개·export gateway(12301)와 공개 유가 gateway(12307)의 실제 nginx 동작 probe.

운영 이미지와 같은 방식으로 두 template을 띄운다.
- 12301: compose의 `nginx:1.27-alpine` 그대로, template과 `19-export-allowlist.sh`를 같은 위치에 mount한다.
- 12307: `deploy/transport-fuel/Dockerfile.gateway`를 template 하나만 든 빌드 문맥으로 빌드한다.
두 경우 모두 공식 entrypoint(20-envsubst-on-templates.sh)가 template을 렌더링하고, 렌더링 결과가
template에서 port 변수만 바꾼 문자열과 같은지 확인한다(nginx 변수가 env로 치환되지 않았는지).
그 뒤 `nginx -t`를 실행하고, loopback 127.0.0.1:12302에 띄운 stub upstream으로 동작을 확인한다.

stub과 gateway는 운영처럼 host network를 쓴다(Linux Docker 엔진 필요: CI runner·WSL). 네트워크는
이미지 pull만 쓴다. 실행: `python3 scripts/gateway-probe.py` (12301·12302·12307이 비어 있어야 한다).
확인 항목은 docs/runbooks/request-timing-logs.md "공개 gateway 가드레일"과 같다.
"""
from __future__ import annotations

import argparse
import gzip
import http.client
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
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
# 운영 export 동시 상한·공개 유가 places 동시 상한(template과 같은 값이어야 한다).
EXPORT_CONN_LIMIT = 6
FUEL_PLACES_CONN_LIMIT = 32
SLOW_SECONDS = 3.0

FAILURES: list[str] = []


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


class Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # noqa: D401 - 조용히
        pass

    def do_GET(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        query = parse_qsl(parts.query, keep_blank_values=True)
        params = dict(query)  # 같은 이름은 마지막 값(Starlette와 같다)
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
        if parts.path.endswith("/backend-busy") or params.get("status") == "503":
            status, headers["Retry-After"] = 503, "60"
        elif params.get("status") == "429":
            status, headers["Retry-After"] = 429, "7"
        body = json.dumps({"stub": True, **seen}).encode()
        big = int(params.get("big", "0") or 0) if params.get("big", "").isdigit() else 0
        if big:
            filler = b"x" * max(0, big - len(body) - 16)
            body = body[:-1] + b',"pad":"' + filler + b'"}'
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


class Gateway:
    def __init__(self, name: str, image: str, port: int, port_var: str, template: Path,
                 run_args: list[str]) -> None:
        self.name, self.image, self.port, self.port_var = name, image, port, port_var
        self.template, self.run_args = template, run_args
        self.container = f"gateway-probe-{name}-{int(time.time())}"

    def base_args(self) -> list[str]:
        return ["--network", "host", "-e", f"{self.port_var}={self.port}", *self.run_args]

    def nginx_t(self) -> subprocess.CompletedProcess:
        return run(["docker", "run", "--rm", *self.base_args(), self.image, "nginx", "-t"])

    def start(self) -> None:
        result = run(["docker", "run", "-d", "--name", self.container, *self.base_args(), self.image])
        if result.returncode:
            raise SystemExit(f"{self.name} 시작 실패: {result.stderr}")
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if request(self.port, "/health")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.2)
        raise SystemExit(f"{self.name} health 대기 실패: {self.logs()}")

    def rendered(self) -> str:
        return run(["docker", "exec", self.container, "cat", "/etc/nginx/conf.d/default.conf"]).stdout

    def logs(self) -> tuple[str, str]:
        result = run(["docker", "logs", self.container])
        return result.stdout, result.stderr

    def stop(self) -> None:
        run(["docker", "rm", "-f", self.container])


def request(port: int, path: str, headers: list[tuple[str, str]] | None = None,
            method: str = "GET") -> tuple[int, dict[str, list[str]], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
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


# ---------------------------------------------------------------- 공통 시험

def check_render(gw: Gateway) -> None:
    expected = gw.template.read_text(encoding="utf-8").replace("${" + gw.port_var + "}", str(gw.port))
    rendered = gw.rendered()
    check(f"{gw.name}: entrypoint 렌더링 = template에서 ${{{gw.port_var}}}만 치환", rendered == expected,
          "렌더링 결과가 다르다(다른 env 치환 또는 template 누락)")
    check(f"{gw.name}: 렌더링에 남은 ${{...}} 없음", "${" not in rendered)


def check_limit_cap(gw: Gateway, path: str, extra: dict[str, str] | None = None) -> None:
    cases = [("", "900"), ("?limit=5000", "900"), ("?limit=901", "900"), ("?limit=300", "300"),
             ("?limit=900", "900"), ("?limit=10&limit=5000", "10"), ("?bbox=1,2,3,4", "900")]
    for query, expected in cases:
        status, _, _, seen = upstream_after(gw.port, path + query)
        ok = status == 200 and seen is not None and seen["limit"] == expected
        if ok and extra:
            ok = all(seen.get(key) == value for key, value in extra.items())
        check(f"{gw.name}: {path}{query or ' (limit 생략)'} → upstream 마지막 limit={expected}", ok, seen)
    for query in ("?limit=abc", "?limit=0", "?limit=-1", "?limit=0300", "?limit=%35000", "?limit=5.0"):
        status, headers, body, seen = upstream_after(gw.port, path + query)
        try:
            problem = json.loads(body)
        except ValueError:
            problem = {}
        ok = (status == 422 and seen is None
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


def concurrent(port: int, path: str, count: int, headers=None) -> list[tuple[int, dict, bytes]]:
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = []
        for index in range(count):
            futures.append(pool.submit(request, port, path, headers))
            if index < count - 1:
                time.sleep(0.02)
        return [future.result() for future in futures]


def check_access_log(gw: Gateway, with_gz: bool) -> None:
    stdout, _ = gw.logs()
    lines = [line for line in stdout.splitlines() if line and not line.startswith("/docker-entrypoint")
             and "Configuration complete" not in line and not line.startswith("20-")
             and not line.startswith("10-") and not line.startswith("30-")]
    pattern = re.compile(
        r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d \S+ "(GET|HEAD|OPTIONS) [^"? ]*" \d{3} \d+ '
        r"rt=\d+\.\d{3} uct=\S+ uht=\S+ urt=\S+ ust=\S+" + (r" gz=\S+" if with_gz else "") + "$")
    bad = [line for line in lines if not pattern.match(line)]
    check(f"{gw.name}: access log 모든 줄이 timing 형식", bool(lines) and not bad, bad[:3] or "로그 없음")
    check(f"{gw.name}: access log에 query·cursor 값 없음", not any("SECRET" in line or "?" in line for line in lines),
          [line for line in lines if "SECRET" in line][:2])
    check(f"{gw.name}: /health는 access log에 남지 않음", not any('"GET /health"' in line for line in lines))
    rejected = [line for line in lines if '" 422 ' in line]
    check(f"{gw.name}: 422 거절 줄은 uct=- (upstream 미호출)", bool(rejected) and all(" uct=- " in line for line in rejected),
          rejected[:2])


def check_no_temp_file(gw: Gateway) -> None:
    _, stderr = gw.logs()
    warnings = [line for line in stderr.splitlines() if TEMP_FILE_WARNING in line]
    check(f"{gw.name}: '{TEMP_FILE_WARNING}' 경고 없음", not warnings, warnings[:2])


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
        try:
            problem = json.loads(body)
        except ValueError:
            problem = {}
        check("admin: export 503은 Retry-After 10 + problem+json code=EXPORT_BUSY",
              headers.get("retry-after") == ["10"]
              and headers.get("content-type", [""])[0].startswith("application/problem+json")
              and set(problem) == {"type", "title", "status", "detail", "instance", "code"}
              and problem.get("code") == "EXPORT_BUSY" and problem.get("status") == 503
              and problem.get("instance") == "/v1/service/exports/slow", (headers, body[:300]))

    status, headers, body = request(gw.port, "/v1/service/exports/backend-busy")
    check("admin: backend 503은 gateway가 바꾸지 않고 전달(Retry-After 60, stub 본문)",
          status == 503 and headers.get("retry-after") == ["60"] and b'"stub": true' in body, (status, headers, body[:120]))

    check_access_log(gw, with_gz=False)
    stdout, _ = gw.logs()
    busy_lines = [line for line in stdout.splitlines() if '"GET /v1/service/exports/slow" 503 ' in line]
    check("admin: export 동시 상한 거절 줄은 uct=-", len(busy_lines) == 2 and all(" uct=- " in line for line in busy_lines),
          busy_lines)
    check_no_temp_file(gw)


def probe_fuel(gw: Gateway) -> None:
    check_render(gw)
    places = "/v1/transport/fuel/places"
    check_limit_cap(gw, places, extra={"path": "/v1/transport/features/places", "kind": "fuel_station"})
    check_listener(gw, [places, "/v1/transport/fuel/stations", "/v1/transport/fuel/statistics"])
    check_server_timing(gw, hidden=["/health", places, "/v1/transport/fuel/stations"], kept=[])

    origin = [("Origin", FUEL_ORIGIN)]
    status, headers, _ = request(gw.port, places, origin)
    check("fuel: places CORS 허용 origin 유지", headers.get("access-control-allow-origin") == [FUEL_ORIGIN], headers)

    # 공개 UI 300곳(약 0.4MB)과 상한 900곳(약 1.2MB) 크기 본문. 임시 파일 없이 전부 받아야 한다.
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

    results = concurrent(gw.port, f"{places}?slow=1", FUEL_PLACES_CONN_LIMIT + 3, origin)
    ok_count = sum(1 for status, _, _ in results if status == 200)
    busy = [(headers, body) for status, headers, body in results if status == 429]
    check(f"fuel: places 동시 {FUEL_PLACES_CONN_LIMIT + 3}건 → 200 {FUEL_PLACES_CONN_LIMIT}건·429 3건",
          ok_count == FUEL_PLACES_CONN_LIMIT and len(busy) == 3, sorted(status for status, _, _ in results))
    for headers, body in busy[:1]:
        try:
            problem = json.loads(body)
        except ValueError:
            problem = {}
        check("fuel: places 동시 상한 429는 Retry-After 2 + problem+json 다섯 항목 + CORS",
              headers.get("retry-after") == ["2"]
              and headers.get("content-type", [""])[0].startswith("application/problem+json")
              and set(problem) == {"type", "title", "status", "detail", "instance"}
              and problem.get("status") == 429 and problem.get("instance") == places
              and headers.get("access-control-allow-origin") == [FUEL_ORIGIN]
              and "Retry-After" in (headers.get("access-control-expose-headers") or [""])[0],
              (headers, body[:300]))
    # 상한은 places location에만 있다. 다른 공개 경로는 같은 시각에도 막히지 않는다.
    with ThreadPoolExecutor(max_workers=FUEL_PLACES_CONN_LIMIT + 1) as pool:
        holders = [pool.submit(request, gw.port, f"{places}?slow=1") for _ in range(FUEL_PLACES_CONN_LIMIT)]
        time.sleep(1.0)
        status, _, _ = request(gw.port, "/v1/transport/fuel/stations")
        check("fuel: places 상한이 찬 동안에도 stations는 200", status == 200, status)
        [future.result() for future in holders]

    check_access_log(gw, with_gz=True)
    check_no_temp_file(gw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--admin-port", type=int, default=12301)
    parser.add_argument("--fuel-port", type=int, default=12307)
    parser.add_argument("--keep", action="store_true", help="끝난 뒤 컨테이너를 지우지 않는다(디버그)")
    args = parser.parse_args()

    for port in (UPSTREAM_PORT, args.admin_port, args.fuel_port):
        if not port_free(port):
            print(f"port {port} 사용 중: 비어 있는 환경(CI runner 등)에서 실행한다", file=sys.stderr)
            return 2

    admin_image, fuel_base = compose_image(), dockerfile_image()
    check("compose 12301 gateway와 fuel Dockerfile이 같은 nginx 이미지", admin_image.split("@")[0] == fuel_base.split("@")[0],
          (admin_image, fuel_base))
    for image in sorted({admin_image, fuel_base}):
        if run(["docker", "image", "inspect", image]).returncode:
            pulled = run(["docker", "pull", "-q", image])
            if pulled.returncode:
                print(pulled.stderr, file=sys.stderr)
                return 2

    # fuel 이미지는 운영과 같은 Dockerfile로 template 하나만 든 문맥에서 빌드한다.
    fuel_tag = f"gateway-probe-fuel:{int(time.time())}"
    with tempfile.TemporaryDirectory() as context:
        target = Path(context) / "deploy/transport-fuel"
        target.mkdir(parents=True)
        shutil.copy(FUEL_TEMPLATE, target / FUEL_TEMPLATE.name)
        built = run(["docker", "build", "-q", "--pull=false", "-t", fuel_tag, "-f", str(FUEL_DOCKERFILE), context])
        if built.returncode:
            print(built.stderr, file=sys.stderr)
            return 2

    admin = Gateway("admin", admin_image, args.admin_port, "TRANSPORT_PUBLIC_API_PORT", ADMIN_TEMPLATE, [
        "-e", "TRANSPORT_EXPORT_CONSUMER_CIDR=127.0.0.1/32", "-e", "TRANSPORT_MCP_CONSUMER_CIDR=127.0.0.1/32",
        "-v", f"{ADMIN_TEMPLATE}:/etc/nginx/templates/default.conf.template:ro",
        "-v", f"{ADMIN_ALLOWLIST}:/docker-entrypoint.d/19-export-allowlist.sh:ro",
    ])
    fuel = Gateway("fuel", fuel_tag, args.fuel_port, "TRANSPORT_FUEL_API_PORT", FUEL_TEMPLATE, [])

    started = time.time()
    stub = start_stub()
    gateways: list[Gateway] = []
    try:
        for gw in (admin, fuel):
            result = gw.nginx_t()
            check(f"{gw.name}: nginx -t ({gw.image})", result.returncode == 0 and "test is successful" in result.stderr,
                  result.stderr[-800:])
        if FAILURES:
            return 1
        for gw in (admin, fuel):
            gw.start()
            gateways.append(gw)
        probe_admin(admin)
        probe_fuel(fuel)
    finally:
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
