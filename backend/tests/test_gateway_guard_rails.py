"""공개·export gateway의 소요 시간 access log, places limit 상한, export 버퍼·동시 상한, Server-Timing 숨김,
공개 유가 gzip 계약.

실제 nginx 동작(nginx -t, limit 상한·422, 공개 표지 덮어쓰기, Server-Timing 숨김, export·유가 places 동시 상한,
temp file 경고, access log 형식)은 CI `gateway-probe` job이 nginx:1.27-alpine과 loopback stub으로 확인한다
(`scripts/gateway-probe.py`). 이 시험은 그 동작을 만드는 설정 문장을 고정한다.
"""
import json
import re
from pathlib import Path

import pytest

from app.core.problems import RETRY_AFTER_SECONDS, ProblemCode

BACKEND = Path(__file__).resolve().parents[1]
# 저장소 checkout은 repo root, backend 회귀 이미지는 /app/compose-contract에 deploy/가 있다.
ROOT = BACKEND.parent if (BACKEND.parent / "deploy").is_dir() else BACKEND / "compose-contract"
ADMIN = ROOT / "deploy/transport-admin/api-gateway.conf.template"
FUEL = ROOT / "deploy/transport-fuel/api-gateway.conf.template"
TEMPLATES = {"admin": (ADMIN, "transport_places_limit"), "fuel": (FUEL, "fuel_places_limit")}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _block(text: str, header: str) -> str:
    return text.split(header + " {", 1)[1].split("\n    }", 1)[0]


def _limit_map(text: str, variable: str) -> tuple[str, dict[str, str], list[tuple[str, str]]]:
    body = text.split(f"map $arg_limit ${variable} {{", 1)[1].split("\n}", 1)[0]
    default, exact, regexes = None, {}, []
    for line in (row.strip() for row in body.splitlines()):
        if not line:
            continue
        key, value = line.rstrip(";").split(None, 1)
        if key == "default":
            default = value
        elif key.startswith("~"):
            regexes.append((key[1:], value))
        else:
            exact[key.strip('"')] = value
    assert default is not None
    return default, exact, regexes


def _nginx_map(text: str, variable: str, arg_limit: str) -> str:
    """nginx map 판정 순서: 정확 문자열 → 정규식(나온 순서) → default. 값의 $arg_limit은 원문 그대로다."""
    default, exact, regexes = _limit_map(text, variable)
    value = exact.get(arg_limit)
    if value is None:
        value = next((result for pattern, result in regexes if re.search(pattern, arg_limit)), default)
    return arg_limit if value == "$arg_limit" else value.strip('"')


@pytest.mark.parametrize("name", sorted(TEMPLATES))
@pytest.mark.parametrize(("arg_limit", "effective"), [
    ("", "900"), ("1", "1"), ("10", "10"), ("99", "99"), ("100", "100"), ("300", "300"), ("899", "899"),
    ("900", "900"), ("901", "900"), ("999", "900"), ("1000", "900"), ("5000", "900"),
    ("99999999999999999999", "900"),
    # 0·부호·앞자리 0·소수·지수·인코딩 숫자·문자는 backend까지 가지 않고 422다.
    ("0", ""), ("00", ""), ("0300", ""), ("-1", ""), ("+5", ""), ("5.0", ""), ("1e3", ""),
    ("%35000", ""), ("abc", ""), ("10%26limit%3D5000", ""), (" 5", ""),
])
def test_places_limit_map_clamps_to_admin_map_maximum(name, arg_limit, effective):
    path, variable = TEMPLATES[name]
    assert _nginx_map(_text(path), variable, arg_limit) == effective


def _returned_json(block: str, status: int) -> dict:
    match = re.search(rf"return {status} '([^']*)';", block)
    assert match, status
    return json.loads(match.group(1))


@pytest.mark.parametrize(("name", "location", "upstream"), [
    ("admin", "/v1/transport/features/places",
     "proxy_pass http://127.0.0.1:12302/v1/transport/features/places?$args&limit=$transport_places_limit;"),
    ("fuel", "/v1/transport/fuel/places",
     "proxy_pass http://127.0.0.1:12302/v1/transport/features/places?$args&kind=fuel_station"
     "&limit=$fuel_places_limit;"),
])
def test_places_limit_is_the_last_upstream_query_value_and_invalid_is_problem_json(name, location, upstream):
    path, variable = TEMPLATES[name]
    block = _block(_text(path), "    location = " + location)
    # Starlette는 반복 query의 마지막 값을 쓴다. 판정 값이 마지막이라 limit=10&limit=5000·%6cimit 우회가 없다.
    assert upstream in block
    assert f'if (${variable} = "") {{' in block
    assert "default_type application/problem+json;" in block
    # ADR-005: 다섯 항목 모두, backend의 query 검증 오류와 같은 422, instance는 클라이언트가 부른 경로.
    problem = _returned_json(block, 422)
    assert set(problem) == {"type", "title", "status", "detail", "instance"}
    assert problem["type"] == "about:blank" and problem["title"] == "Unprocessable Entity"
    assert problem["status"] == 422 and problem["instance"] == location
    assert "900" in problem["detail"] and re.search(r"[가-힣]", problem["detail"])
    assert "return 400" not in block


def test_public_transport_places_exact_location_keeps_read_only_public_contract():
    text = _text(ADMIN)
    block = _block(text, "    location = /v1/transport/features/places")
    assert "limit_except GET { deny all; }" in block
    assert "proxy_set_header Host 127.0.0.1;" in block
    assert "proxy_read_timeout 30s;" in block
    # 정확 일치 location이 정규식보다 먼저 나와 읽기 쉬운 순서를 유지한다(nginx 선택은 순서와 무관).
    assert text.index("location = /v1/transport/features/places") < text.index("location ~ ^/v1/transport/(")


@pytest.mark.parametrize(("name", "format_name"), [("admin", "transport_timing"), ("fuel", "fuel_timing")])
def test_timing_access_log_has_durations_but_no_query_or_request_line(name, format_name):
    path, _ = TEMPLATES[name]
    text = _text(path)
    match = re.search(rf"log_format {format_name} ((?:'[^']*'\s*)+);", text)
    assert match, format_name
    fmt = "".join(re.findall(r"'([^']*)'", match.group(1)))
    path_variable = {"admin": "$transport_log_path", "fuel": "$fuel_log_path"}[name]
    for field in ("$time_iso8601", "$status", "$body_bytes_sent", "$request_time", "$upstream_connect_time",
                  "$upstream_header_time", "$upstream_response_time", "$upstream_status",
                  f'"$request_method {path_variable}"'):
        assert field in fmt, field
    # cursor·토큰·좌표가 남는 변수는 쓰지 않는다. 디코드한 $uri도 쓰지 않는다(%20이 공백이 되어 필드가 밀린다).
    for forbidden in ("$request ", '$request"', "$request_uri", "$args", "$query_string", "$arg_",
                      "$http_authorization", "$http_cookie", "$uri"):
        assert forbidden not in fmt, forbidden
    # 경로 변수는 디코드 전 요청 경로에서 query(? 뒤)를 뗀 값이다.
    path_map = text.split(f"map $request_uri {path_variable} {{", 1)[1].split("\n}", 1)[0]
    assert "~^([^?]*) $1;" in path_map
    assert re.match(r"^([^?]*)", "/v1/service/exports/fuel-stations?cursor=SECRET").group(1) == (
        "/v1/service/exports/fuel-stations")
    server = text.split("server {", 1)[1]
    assert f"    access_log /dev/stdout {format_name};" in server.split("location", 1)[0]
    assert "access_log off;" in _block(text, "    location = /health")


def test_export_location_never_buffers_large_pages_to_temp_files_and_bounds_total_memory():
    text = _text(ADMIN)
    block = _block(text, "    location ^~ /v1/service/exports/")
    assert "proxy_max_temp_file_size 0;" in block
    match = re.search(r"proxy_buffers (\d+) (\d+)k;", block)
    assert match
    per_request = int(match.group(1)) * int(match.group(2)) * 1024
    assert "proxy_buffering off;" not in block
    # 동시 상한 × 요청당 버퍼가 64MiB gateway(공개 API·MCP 공유)의 1/4(16MiB)을 넘지 않는다.
    limit = re.search(r"limit_conn transport_export (\d+);", block)
    assert limit
    assert int(limit.group(1)) * per_request <= 16 * 1024 * 1024
    assert "limit_conn_zone $transport_export_slot zone=transport_export:1m;" in text
    assert "limit_conn_status 503;" in block
    assert "error_page 503 = @transport_export_busy;" in block
    # 거절은 Retry-After가 있는 problem+json이다. instance는 JSON에 안전한 문자만 허용한 map 값이다.
    # export 503 사유 code 계약(ProblemCode)의 EXPORT_BUSY와 그 Retry-After 힌트를 쓴다.
    busy = _block(text, "    location @transport_export_busy")
    assert f"add_header Retry-After {RETRY_AFTER_SECONDS[ProblemCode.EXPORT_BUSY]} always;" in busy
    assert "default_type application/problem+json;" in busy
    problem = json.loads(re.search(r"return 503 '([^']*)';", busy).group(1).replace(
        "$transport_export_instance", "/v1/service/exports/airports"))
    assert set(problem) == {"type", "title", "status", "detail", "instance", "code"} and problem["status"] == 503
    assert problem["code"] == ProblemCode.EXPORT_BUSY
    instance_map = text.split("map $uri $transport_export_instance {", 1)[1].split("\n}", 1)[0]
    pattern = re.search(r"~(\S+) \$uri;", instance_map).group(1)
    assert re.match(pattern, "/v1/service/exports/fuel-stations/opinet:A0001/price-history")
    for unsafe in ('/v1/service/exports/a"b', "/v1/service/exports/a\\b", "/v1/service/exports/a b"):
        assert not re.match(pattern, unsafe), unsafe


@pytest.mark.parametrize("location", [
    "location = /health", "location = /v1/transport/features/places", "location ~ ^/v1/transport/(",
    "location ~ ^/v1/transport/rail/general/", "location = /mcp",
])
def test_public_transport_locations_hide_server_timing(location):
    text = _text(ADMIN)
    header = text[text.index("    " + location):].split(" {\n", 1)[0]
    assert "proxy_hide_header Server-Timing;" in _block(text, header), location


def test_export_keeps_server_timing_and_fuel_server_hides_it():
    assert "Server-Timing" not in _block(_text(ADMIN), "    location ^~ /v1/service/exports/")
    fuel = _text(FUEL)
    server = fuel.split("server {", 1)[1].split("    location", 1)[0]
    assert "proxy_hide_header Server-Timing;" in server
    # location 안에 proxy_hide_header를 두면 server 단위 목록 상속이 끊긴다.
    for block in fuel.split("    location")[1:]:
        assert "proxy_hide_header" not in block


def test_public_fuel_gateway_compresses_json_cheaply_without_recompressing():
    text = _text(FUEL)
    server = text.split("server {", 1)[1].split("    location", 1)[0]
    for directive in ("gzip on;", "gzip_comp_level 1;", "gzip_min_length 1024;", "gzip_proxied any;",
                      "gzip_vary on;"):
        assert directive in server, directive
    assert re.search(r"gzip_types [^;]*application/json", server)
    # nginx gzip은 200·403·404만 압축하므로 오류 본문 형식은 대상에 넣지 않는다.
    assert "application/problem+json" not in re.search(r"gzip_types [^;]*;", server).group(0)
    # 모바일 NAT 뒤의 정상 사용자를 막지 않도록 IP별 요청 제한은 두지 않는다(PR 설명 참고).
    assert "limit_req" not in text


def test_public_fuel_places_never_buffers_to_temp_files_and_bounds_total_memory():
    text = _text(FUEL)
    block = _block(text, "    location = /v1/transport/fuel/places")
    assert "proxy_max_temp_file_size 0;" in block
    assert "proxy_buffering off;" not in block
    match = re.search(r"proxy_buffers (\d+) (\d+)k;", block)
    assert match
    buffers = int(match.group(1)) * int(match.group(2)) * 1024
    # 공개 UI 한 번(종류당 300곳, 실측 411,384 bytes 비압축)은 메모리 버퍼에 다 들어간다.
    assert buffers >= 411_384
    # 요청당 메모리: proxy_buffers + proxy_buffer_size(기본 4KiB). gzip 응답(직접 호출)은 zlib deflate 상태
    # (window 15·memLevel 8: 2^17 + 2^17 + 약 8KiB) + gzip_buffers 기본 32×4KiB를 더한다. BFF는 identity를 요청한다.
    for directive in ("proxy_buffer_size", "gzip_buffers", "gzip_window", "gzip_hash", "gzip_memlevel"):
        assert not re.search(rf"^\s*{directive}\s", text, re.M), directive
    identity = buffers + 4 * 1024
    gzipped = identity + (1 << 17) + (1 << 17) + 8 * 1024 + 32 * 4 * 1024
    bff = re.search(r"limit_conn fuel_places_bff (\d+);", block)
    direct = re.search(r"limit_conn fuel_places_direct (\d+);", block)
    assert bff and direct
    # 두 몫을 모두 채워도 64MiB fuel gateway의 1/4(16MiB, export와 같은 기준)을 넘지 않는다. zone은 worker끼리
    # 공유하므로 worker 수와 무관하다(worker 상주 메모리·커널 socket 버퍼는 probe가 64MiB 한도로 따로 잰다).
    assert int(bff.group(1)) * identity + int(direct.group(1)) * gzipped <= 16 * 1024 * 1024
    # BFF 몫은 backend 공개 몫(동시 계산 3·대기 8)보다 크고, 직접 호출 몫이 BFF를 막지 못하도록 key가 다르다.
    assert int(bff.group(1)) > 3 + 8
    bff_map = text.split("map $remote_addr $fuel_places_bff_slot {", 1)[1].split("\n}", 1)[0]
    direct_map = text.split("map $remote_addr $fuel_places_direct_slot {", 1)[1].split("\n}", 1)[0]
    assert 'default "";' in bff_map and "127.0.0.1 bff;" in bff_map
    assert "default direct;" in direct_map and '127.0.0.1 "";' in direct_map
    assert "limit_conn_zone $fuel_places_bff_slot zone=fuel_places_bff:1m;" in text
    assert "limit_conn_zone $fuel_places_direct_slot zone=fuel_places_direct:1m;" in text
    # 주소별로 나누지 않는다(직접 호출은 HAProxy 한 주소·모바일 NAT를 공유한다). listen은 IPv4 하나다.
    assert "$binary_remote_addr" not in text
    assert text.count("    listen ") == 1 and "listen 0.0.0.0:" in text
    # 읽지 않는 연결의 커널 송신 버퍼도 묶는다(cgroup v2에서는 컨테이너 한도에 들어간다).
    assert "    listen 0.0.0.0:${TRANSPORT_FUEL_API_PORT} sndbuf=256k;" in text
    # 멈춘 클라이언트는 10초 안에 끊는다(전체 시간 상한은 아니다).
    assert "send_timeout 10s;" in block
    assert "limit_conn_status 429;" in block
    assert "limit_conn_log_level warn;" in block
    assert "error_page 429 = @fuel_places_busy;" in block
    # 거절은 backend 입장 거절과 같은 429 + Retry-After 2(공개 지도 자동 재조회 범위) problem+json이다.
    busy = _block(text, "    location @fuel_places_busy")
    assert "add_header Retry-After 2 always;" in busy
    assert "default_type application/problem+json;" in busy
    problem = _returned_json(busy, 429)
    assert set(problem) == {"type", "title", "status", "detail", "instance"}
    assert problem["status"] == 429 and problem["instance"] == "/v1/transport/fuel/places"
    # location의 add_header는 server 목록 상속을 끊으므로 CORS 줄을 모두 다시 적어야 한다.
    server = text.split("server {", 1)[1].split("    location", 1)[0]
    cors = re.findall(r"^    (add_header [^\n]+;)$", server, re.M)
    assert len(cors) == 5
    for line in cors:
        assert "        " + line in busy, line
