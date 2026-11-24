"""공개·export gateway의 소요 시간 access log, places limit 상한, export 버퍼, 공개 유가 gzip 계약.

실제 nginx 동작(반복·인코딩 query, 정규화 경로, temp file 경고, gzip 이중 압축 여부)은 PR에서
nginx:1.27-alpine과 loopback stub으로 따로 확인했다. 이 시험은 그 동작을 만드는 설정 문장을 고정한다.
"""
import re
from pathlib import Path

import pytest

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
    # 0·부호·앞자리 0·소수·지수·인코딩 숫자·문자는 backend까지 가지 않고 400이다.
    ("0", ""), ("00", ""), ("0300", ""), ("-1", ""), ("+5", ""), ("5.0", ""), ("1e3", ""),
    ("%35000", ""), ("abc", ""), ("10%26limit%3D5000", ""), (" 5", ""),
])
def test_places_limit_map_clamps_to_admin_map_maximum(name, arg_limit, effective):
    path, variable = TEMPLATES[name]
    assert _nginx_map(_text(path), variable, arg_limit) == effective


@pytest.mark.parametrize(("name", "location", "upstream"), [
    ("admin", "location = /v1/transport/features/places",
     "proxy_pass http://127.0.0.1:12302/v1/transport/features/places?$args&limit=$transport_places_limit;"),
    ("fuel", "location = /v1/transport/fuel/places",
     "proxy_pass http://127.0.0.1:12302/v1/transport/features/places?$args&kind=fuel_station"
     "&limit=$fuel_places_limit;"),
])
def test_places_limit_is_the_last_upstream_query_value_and_invalid_is_problem_json(name, location, upstream):
    path, variable = TEMPLATES[name]
    block = _block(_text(path), "    " + location)
    # Starlette는 반복 query의 마지막 값을 쓴다. 판정 값이 마지막이라 limit=10&limit=5000·%6cimit 우회가 없다.
    assert upstream in block
    assert f'if (${variable} = "") {{' in block
    assert "return 400 '{" in block and '"status":400' in block
    assert "default_type application/problem+json;" in block


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
    for field in ("$time_iso8601", "$status", "$body_bytes_sent", "$request_time", "$upstream_connect_time",
                  "$upstream_header_time", "$upstream_response_time", "$upstream_status", '"$request_method $uri"'):
        assert field in fmt, field
    # cursor·토큰·좌표가 남는 변수는 쓰지 않는다.
    for forbidden in ("$request ", '$request"', "$request_uri", "$args", "$query_string", "$arg_",
                      "$http_authorization", "$http_cookie"):
        assert forbidden not in fmt, forbidden
    server = text.split("server {", 1)[1]
    assert f"    access_log /dev/stdout {format_name};" in server.split("location", 1)[0]
    assert "access_log off;" in _block(text, "    location = /health")


def test_export_location_never_buffers_large_pages_to_temp_files():
    block = _block(_text(ADMIN), "    location ^~ /v1/service/exports/")
    assert "proxy_max_temp_file_size 0;" in block
    match = re.search(r"proxy_buffers (\d+) (\d+)k;", block)
    assert match
    # 요청당 메모리 버퍼는 64MiB gateway에서 동시 export 여러 개를 감당할 수 있게 4MiB 이하로 둔다.
    assert int(match.group(1)) * int(match.group(2)) * 1024 <= 4 * 1024 * 1024
    assert "proxy_buffering off;" not in block


def test_public_fuel_gateway_compresses_json_cheaply_without_recompressing():
    text = _text(FUEL)
    server = text.split("server {", 1)[1].split("    location", 1)[0]
    for directive in ("gzip on;", "gzip_comp_level 1;", "gzip_min_length 1024;", "gzip_proxied any;",
                      "gzip_vary on;"):
        assert directive in server, directive
    assert re.search(r"gzip_types [^;]*application/json", server)
    # 모바일 NAT 뒤의 정상 사용자를 막지 않도록 IP별 요청 제한은 두지 않는다(PR 설명 참고).
    assert "limit_req" not in text
