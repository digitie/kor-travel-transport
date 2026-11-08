# 같은 API에서 제공하는 유가 검색 MCP

`TRANSPORT_FUEL_MCP_ENABLED=true`이면 기존 FastAPI의 `/mcp`에서 Streamable HTTP MCP를
제공한다. API와 **같은 프로세스·호스트·포트**이며 운영 정본 API 포트는 12302다.
별도 서버·포트·DB·내부 HTTP 호출 계층은 추가하지 않는다. 기본값은 `false`다.
기존 REST 경로와 SDK/provider 핀·수집·원본·영구 지역 통계는 유지한다.

## 연결과 인증

| 항목 | 계약 |
|---|---|
| 주소 | 같은 호스트의 `http://127.0.0.1:12302/mcp` |
| 인증 | 기존 `x-kor-travel-transport-service-token` 헤더, 32자 이상 |
| 접속 대역 | 기존 `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`, 기본 loopback |
| 활성화 | `TRANSPORT_FUEL_MCP_ENABLED`, API 역할에서만 사용 |
| 주소 판정 | 기존 `VWORLD_API_KEY` / `KAKAO_REST_API_KEY`와 저장 주소 캐시 재사용 |
| 기존 API gateway | exact `/mcp`의 GET/POST만 전달. `TRANSPORT_MCP_CONSUMER_CIDR`이 비면 전부 거절 |

인증이 없거나 잘못됐거나 실제 ASGI peer가 허용 대역 밖이면 404다. `Host`나
`X-Forwarded-For`를 읽어 peer 권한을 넓히지 않는다. API의 TrustedHost와 MCP의 Host/Origin
검사도 함께 적용한다. 직접 loopback 접속이 기본이며 새 공용 reverse proxy 경로를 열지 않는다.
프록시를 사용한다면 ASGI peer 생성에 관여하는 Uvicorn의 신뢰 프록시 설정도 Root가 확인해야 한다.
서비스 토큰은 도구 인자·URL·명령행에 넣지 않는다. 실제 값은 기존 비공개 환경을 통해서만 전달한다.

기존 Transport API gateway는 같은 API의 12302로 전달한다. `/mcp`에서 buffering/cache를 끄고
HTTP/1.1·GET 스트림·POST를 전달하며 Host는 loopback으로 고정하고 X-Forwarded-For는 비운다.
`/mcp` 하위 임의 경로와 DELETE 등은 열지 않는다. MCP 전용 allow 파일을 사용하므로
`TRANSPORT_EXPORT_CONSUMER_CIDR`과 기존 raw export 허용 범위는 바뀌지 않는다.
두 CIDR은 같은 엄격한 IPv4/CIDR 검산을 거치며 하나라도 잘못되면 두 기존 파일을 모두 보존한다.

gateway의 MCP CIDR은 **gateway가 실제로 관측하는 peer**이고 backend의 기존
`SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`는 **backend가 실제로 관측하는 peer**다.
gateway 경유 backend peer는 loopback이며, HAProxy 경유 gateway peer는 Root가 실제 경로에서
확인해야 한다. 임의 XFF로 원래 사용자 IP를 단정하거나 raw export CIDR을 대신 넓히지 않는다.
Transport 저장소의 gateway 구성과 배포 런북의 host-route 이력을 확인했으나 실제 HAProxy 설정은
이 구현에서 조회·변경하지 않았다. 공개 `transport-api` 도메인/SNI의 연결 성공은 아직 미검증이다.

공식 Python MCP SDK `mcp==2.3.0`을 사용한다. 최신 `2026-07-28` 프로토콜과
`2025-11-25`의 `initialize` 연결을 모두 지원한다. SDK가 최신 요청의 메타데이터와
`MCP-Method` 헤더를 구성하게 한다. 예를 들어 같은 호스트의 클라이언트는 다음처럼 연결한다.
예제 좌표는 설명용이며 사용자 GPS/IP를 추정하지 않는다.

```python
import asyncio
import os

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    headers = {
        "x-kor-travel-transport-service-token": os.environ["TRANSPORT_SERVICE_EXPORT_TOKEN"],
    }
    async with httpx2.AsyncClient(headers=headers, trust_env=False, timeout=20) as http:
        transport = streamable_http_client("http://127.0.0.1:12302/mcp", http_client=http)
        async with Client(transport, cache=None) as client:
            result = await client.call_tool("search_nearby_fuel", {"query": {
                "latitude": 37.5665, "longitude": 126.9780, "radius_m": 5000,
            }})
            print(result.structured_content)

asyncio.run(main())
```

## 도구 계약

두 도구 모두 `query` 객체를 받으며 구조화된 `FuelSearchResponse`를 반환한다.
`readOnlyHint=true`, `destructiveHint=false`이며 DB 조회는 PostgreSQL의 읽기 전용
REPEATABLE READ 트랜잭션을 사용한다. 인증은 이 힌트와 별도로 실제 강제된다.

### `search_nearby_fuel`

- 필수: `latitude`, `longitude` — 호출자가 제공하는 유한 WGS84 좌표.
- `radius_m`: 기본 5,000m, 1~50,000m. km 값은 호출자가 m로 환산한다.
- `product_codes`: 생략 시 아래 다섯 유종 전부. 1~5개를 지정할 수 있다.
- `limit_per_product`: 최저가 동률 주유소의 반환 상한. 기본 5곳, 최대 20곳.

DB에서 bbox로 후보를 제한하고 대권 직선거리로 반경을 판정한다. 평균 지구 반지름
6,371,008.8m를 사용하며 도로 주행거리는 아니다. **반경 판정에는 반올림 전 거리**를 사용하고
표시 거리만 소수 둘째 자리로 반올림한다. 전체 가격 목록을 Python으로 가져와 순회하지 않는다.

유종별 양수·유한 가격의 평균, 최저가, 표본 주유소 수와 최저가 동률 주유소를 반환한다.
동률은 거리→기존 `station_key` 순서이며 전체 동률 수와 `truncated`를 별도로 준다.
좌표 없는 시설은 반경 평균·검색에서 제외된다. 반경 평균은 지도 marker 상한과 무관하다.

### `get_regional_fuel_prices`

- `scope`: 기본 `nationwide`, 또는 `sigungu`.
- 전국 조회는 인자 없이 가능하다. 전 유종 평균·최저가·대표 주유소를 반환한다.
- 시군구는 `latitude`·`longitude`, 또는 `sido_value`·`sigungu_value` 두 저장 지역 값을 받는다.
- 명시적 코드가 있으면 주소 제공자를 호출하지 않는다. 해당 공개 지역이 없으면
  `region.status=unavailable`, `reason=region_not_published`다.
- 좌표는 기존 정확한 좌표 키의 저장 주소를 먼저 읽는다. 없으면 기존 VWorld/Kakao resolver를
  호출한다. 새 provider adapter나 provider 의존성은 추가하지 않는다. 성공 주소만 최대 128개·1시간
  메모리 캐시로 재사용하며 DB 주소 쓰기는 없다. 이 캐시는 유가·수집 상태를 캐시하지 않는다.
- 법정동 연결 또는 SDK 시도 코드 변환과 유일한 저장 시군구명 대조로 지역을 확인한다.
  제공자 실패·명칭/코드 불일치·다중 후보이면 명시적 이유와 unavailable을 반환한다.
  가까운 주유소의 행정구역을 현재 위치라고 단정하지 않는다. 명시적 저장 지역 값로 다시 조회할 수 있다.
- 전국·시군구는 기존 영구 통계의 **안정 대표 최저가 1곳과 전체 동률 수**를 그대로 반환한다.
  동률이 더 있으면 `truncated=true`다. 다른 세대의 주유소 지역/상호를 섞어 재집계하지 않는다.
  좌표를 같이 주면 대표 주유소의 직선거리도 DB에서 계산한다.

| 코드 | 유종 | 가격 단위 |
|---|---|---|
| B027 | 휘발유 | 원/L |
| B034 | 고급휘발유 | 원/L |
| D047 | 경유 | 원/L |
| C004 | 등유 | 원/L |
| K015 | LPG | 원/L |

## 성공 세대·미제공 의미

반경은 `FuelStatisticsState`가 가리키는 완결된 `FuelStatisticsPoint` 세대를,
전국·시군구는 같은 포인터의 `FuelStatisticsDaily`를 읽는다. 기존 발행의
**이번 성공 Opinet 수집 시각과 같은 양수 가격만** 사용하는 모집단을 유지한다.
이전 성공 가격 110원이 최신 가격 표에 남아 있어도 새 통계에 섞지 않는다.
과거 원본과 영구 통계는 수정·삭제하지 않는다.

`collection.generated_at`, `last_success_at`, `stale`, `update_pending`,
`last_attempt_failed`를 매번 조회해 반환한다. 통계 발행이 뒤처졌으면 이전 완결 공개 세대와
`update_pending=true`를 함께 보여준다. 낡은 자료를 현재 시각의 가격으로 표현하지 않는다.
공개 세대가 없으면 `status=unavailable`이고 건수·가격은 `null`이다.
정상 세대의 반경에 양수 가격이 없는 유종은 건수 `0`, 평균/최저가 `null`이다.
미제공을 무료 `0원`으로 바꾸지 않는다. MCP 요청은 수집이나 통계 발행을 시작하지 않는다.

도구 동시 실행은 프로세스당 4개, 주소 제공자 동시는 2개, DB 문장은 5초,
도구 예산은 20초이며 MCP 요청 본문은 16KiB다. 오류 응답에는 고정 사유만 반환하고
토큰·DSN·제공자 예외 원문을 포함하지 않는다.

## 검증과 운영 인계

WSL/Python 3.12와 자체 Docker PG18에서 반경·전 유종·동률·양수/NULL·이전 성공분 제외·
주소 캐시·해결 불가·인증/대역/프록시 헤더·Host/Origin·프로토콜·같은 API lifespan을 집중 검증한다.
기존 provider 설치 경로는 읽기 전용으로 재사용하고 새 SDK 설치나 원본/영구 통계 변경은 하지 않는다.
새 의존성은 공식 MCP SDK와 전이 의존성뿐이며 기존 provider와 기존 잠금 기록은 유지한다.

초기 SQLite에서 SQL NULL 열 이름과 현대 프로토콜 요청 형식 시험이 실패한 기록은 보존한다.
실제 검증 수와 commit/PR·미배포 상태는 작업 원장
`C:/Users/digit/.codex/tmp/transport-fuel-mcp-20261108/plan.json`에 정산한다.
PG18 집중 묶음은 WSL 22개·Docker 22개 통과했다. 도중 수집 성공/통계 공개가 바뀌어도 한
읽기 응답의 세대가 섞이지 않는 native 검산과 read-only 설정을 포함한다. 같은 소켓의 API와
공식 SDK Client로 initialize(2025-11-25)·discover(2026-07-28)·도구 목록·호출을 확인했다.
별도 격리 Nginx 경유에서도 GET SSE 200·POST 두 프로토콜과 토큰 없는 404·빈 CIDR/위조 XFF
403·기존 raw export 허용 범위 불변을 확인했다. 초기 gateway 시험의 GET 예상405 오류는
보존했고 실제 SDK의 SSE 200을 검산한 뒤 정정했다. 이는 운영 HAProxy/공개 URL 수용이 아니다.

운영 반영은 Root가 현재 배포 런북·ADR-014에 따라 API 이미지·활성화 값과 기존 gateway 설정을
적용하고 실제 HAProxy peer를 관측해 MCP 전용 CIDR만 명시한 뒤 같은 호스트와 공개 경로의
인증·도구·실제 가격 세대·부모/자식 종료를 확인한다. gateway의 기존 Nginx 이미지 재빌드는
필요하지 않으며 template/allowlist 설정 반영은 별도다. 이 구현은 아직 운영에 반영하지 않았다.
새로운 백업·복원·수집·키 교체·migration·prune는 필요하지 않다.

## 기존 Python 3.12 이미지의 의존성 추가 경로

기준 소스는 `68990e4a4d3a3e9125903a36ceebec73b223c1fb`다. 기존 provider/common 10개
잠금 record와 FastAPI·Starlette·httpx·Pydantic 등 모든 기존 의존성 record는 그대로다.
후보 `backend/uv.lock` SHA256은
`278e5b164cf9be48f37d474e390f03cc9bd0bd2f3d6c5b451f5ea37bcc7bec08`이다.
`backend/fuel-mcp-additions.txt`는 신규 17개 record의 정확 버전과 platform marker만 담는다.
Linux CPython3.12에는 그중 16개가 적용되며 `httpx2-jsfetch`는 emscripten 전용이다.
격리 Python3.12 기준 환경에서 기존 95개 third-party distribution의 버전을 보존하고
적용되는 신규 16개만 추가했다. 기존 provider의 17개 Python 파일 SHA 불변·provider 설치 0을
확인했으며 이 환경에서도 같은 API 소켓의 두 MCP 프로토콜·도구 호출을 검산했다.
이는 운영 ARM64 이미지 자체의 추가 설치/배포 완료를 뜻하지 않는다.

| 신규 record | 버전 |
|---|---|
| attrs | 26.1.0 |
| cffi | 2.1.1 |
| cryptography | 50.0.2 |
| httpcore2 | 2.16.0 |
| httpx2 | 2.16.0 |
| httpx2-jsfetch | 1.0 (emscripten 전용) |
| jsonschema | 4.26.0 |
| jsonschema-specifications | 2025.9.1 |
| mcp / mcp-types | 각각 2.3.0 |
| opentelemetry-api | 1.45.2 |
| pycparser | 3.12 |
| pyjwt | 2.15.1 |
| referencing | 0.37.0 |
| rpds-py | 2026.9.1 |
| sse-starlette | 3.7.0 |
| truststore | 0.10.5 |

ARM64 CPython3.12용 신규 16개 wheel을 아래 명령으로 내려받고 각각의 SHA를 위 lock의
wheel record와 대조했다. 내려받기 도구는 별도 환경이며 기존 provider 환경은 수정하지 않았다.

```sh
uv tool run --from pip pip download --only-binary=:all: --no-deps \
  --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 \
  --implementation cp --python-version 3.12 --abi cp312 --abi abi3 \
  -r backend/fuel-mcp-additions.txt -d <신규-wheel-디렉터리>
```

개인 작업 원장의 `arm64-cp312-wheels/manifest.json`에 정확 파일명·버전·SHA를 기록했다.
`transport-fuel-mcp-arm64-cp312-wheels.tgz` SHA256은
`3e58f08c8cf1836bd2e6040902ca456e591659cea6d4f01da2f58e39410d9b3f`다.
Root가 지정한 기존 ARM64 API 기준 이미지는
`sha256:11418aa1e1a654fa1d09d85df1ec9984c94bdb4b040622d6dd320d7bb82d6c01`이며,
실행 인계는 같은 원장의 `root/runtime-handoff.json`에 기록한다. 설치는 같은 목록으로
`pip install --no-deps --no-index --find-links=<검산한-wheel-디렉터리> -r backend/fuel-mcp-additions.txt`를
사용한다. 기존 SDK나 전체 requirements를 재설치하거나 다른 기존 버전을 갱신하지 않는다.
새 backend 소스/프로젝트 metadata만 반영하고 기존 dependency inventory와 provider 파일 SHA를
전후 대조한다. wheel 선택·해시 검산은 완료했고, 실제 ARM64 이미지 생성·추가 설치·pip check와
배포는 Root 단계다. 소스 제품 commit은 `a3fbb4e9dca25e059efaef1d59d81d4885206366`,
검토용 [Draft PR175](https://github.com/digitie/kor-travel-transport/pull/175)는 PR174의
`codex/transport-read-max-20261107` 위에 쌓았다. 머지·운영 배포는 하지 않았다.

참고한 공식 자료:

- [Python SDK 설치·현재 안정 버전 계열](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/get-started/installation.md)
- [최신/initialize 프로토콜 호환](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/protocol-versions.md)
- [MCP 도구 스키마·목록·호출 명세](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

## 2026-11-08 실제 API 반영

제품 `a3fbb4e`/API 이미지 `857b507b`를 같은12302 `/mcp`에 반영했다. API에서만 MCP를 활성화하며 CS·웹·gateway·Weather·원47개 일정을 보존했다. DB/schema0041과 provider는 그대로다. 실제 ARM64 Python3.12.13의 기존108개 distribution·Git provider Python138파일을 보존하고 새16개 wheel만 추가했다. 격리95개/17파일과 합산하지 않는다. 원 CRLF overlay는 보존하고 같은 Git commit의 정본LF archive를 blob SHA로 검산했다.

공식 Client 두 프로토콜로 실제 소켓을 호출했다. 예제 좌표 서울시청 부근5km의5유종 표본은52/43/52/16/0개이며 평균·최저·동률·순서를 독립 거리/산술과 대조해 일치했다. LPG0개는 반경 미제공이다. 전국·저장 지역값·좌표 기반 서울 중구도 같은 공개 성공 세대에서 조회했으며 update_pending=false였다. 단일 호출은 반경3.125초/전국1.650초/명시 지역0.210초/좌표 지역4.230초다. p95/cold/모든 지역 보장은 아니다. 시도/시군구 값은 실제 저장된 이름일 수도 있으므로 숫자 코드로 추측하지 않는다.

인증 없는 호출404/API health200, Manager healthy·원 일정·빌드/배포 첫 Invocation done·MainPID0·cgroup부재를 확인했다. 외부 gateway/HAProxy는 변경하지 않았으므로 공개 도메인 성공으로 표현하지 않는다. 기존 서비스 토큰·허용 대역 또는 같은 호스트 loopback으로 접속한다. 키값·토큰·URL query·HAR는 기록하지 않았다. 정본은 `transport-fuel-mcp-release-20261108/final-acceptance.json`이다.
