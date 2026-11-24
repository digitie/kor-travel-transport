# Map 담당 인계: 현재 상태·참조 service API

## 구현·운영 상태

2026-11-09 운영 API·수집기의 공통 `TRANSPORT_MAP_CURRENT_ENABLED`를 true로 맞췄다.
철도·해운 기준정보 수집 flag·예약도 활성 상태다. 실제 Map 호스트에서 철도1108건과 항구753건의
완결 페이지·source_status=ok·조건부304를 확인했다. [실제 활성화와 한계](reports/2026-11-09-map-reference-activation.md).
아래 나머지 T2/T3 source의 최초 승인집합은 이번 수용 범위에 포함하지 않는다.

Map PR1355의 기존 consumer는 T1의 `collection/has_more/next_cursor` 페이지를 읽는다.
새 T2/T3는 `meta/snapshot_id/snapshot_expires_at/total_count/items/has_more/next_cursor`의 별도
고정 집합 계약이다. 기존 T1 parser로 직접 읽지 말고 Map 쪽에 새 reader를 추가해야 한다.
기존 fuel/rest-area/T1 응답은 T2/T3 작업에서 변경하지 않았다. 2026-11-24 T1 전송 개정(gzip 협상·`Vary`,
int4 밖 cursor 422, snapshot 상한 초과 503 + `Retry-After`)은 본문 JSON을 바꾸지 않는다 —
[ADR-013 개정 2026-11-24 (T1 전송)](adr/013-internal-service-exports-for-map.md#개정-2026-11-24-t1-전송).

| 구분 | 경로 suffix | Transport PR | 운영 상태 |
| --- | --- | --- | --- |
| T2 | highway-traffic/current | 114 | API 배포·공통flagON, source 수용 별도 |
| T3 | bus-terminals | 115 | API 배포·공통flagON, source 수용 별도 |
| T3 | ferry-ports | 116 | 실제753건·완결200/304 확인 |
| T3 | rail-stations | 117 | 실제1108건·완결200/304 확인 |
| T2 | parking/current | 118 | API 배포·공통flagON, source 수용 별도 |

[제품 검증·머지/운영 잔여 gate 정산](reports/2026-10-23-map-t2-t3-acceptance.md). KAC quota 복구 PR119도 운영 rollout 전에 포함한다.

모든 경로는 `/v1/service/exports/` 아래이며 기존 `X-Kor-Travel-Transport-Service-Token` header/peer 허용 규칙을 사용한다.
새 인증 방식이나 브라우저 토큰을 만들지 않는다. 배포 및 source flag 활성화는 운영 수집 run과
조율하는 별도 gate이며 본 문서의 fixture 응답을 운영 검증으로 해석하면 안 된다.

## 실제 fixture HTTP 응답

[HTTP 기록](examples/map-service-exports/http-summary.json)은 격리 PostgreSQL과 실제 TCP uvicorn에서
`limit=1`, gzip 요청으로 캡처한5종200 응답이다. source head `2f52aed`의 테스트용 집합이며
운영 개수·좌표·시각이 아니다. 문자열 cursor는 fixture 키로 서명했고 예시의 만료시각은 이미
지났을 수 있으므로 운영 요청에 재사용하면 안 된다.

- [구간별 교통 현재](examples/map-service-exports/highway-traffic-current.json)
- [주차장 현재](examples/map-service-exports/parking-current.json)
- [버스터미널](examples/map-service-exports/bus-terminals.json)
- [항구](examples/map-service-exports/ferry-ports.json)
- [철도역](examples/map-service-exports/rail-stations.json)

`meta.generated_at`은 응답 생성, `meta.source_collected_at`은 source 승인시각이며 parking은
승인집합의 가장 이른 원천 관측시각을 쓴다. source_status는 ok/stale이며 item_count는 페이지의
행수, total_count는 고정 집합 전체행수다. 메타 없는/급감미확인 첫집합은503으로 닫는다.
철도 코드의 선행0과 nullable code/coords, parking의 airport_anchor, 항구 guideline 좌표null을
그대로 보존한다. T1 fuel/rest-area 및 T3 참조의 admin은 현재 좌표의 coordinate_key와
reverse_address_entries가 일치할 때만 싣고, 없거나 불일치하면 null이다. 주소 provider는
vworld/kakao이며 nullable code/주소 필드를 보존한다. 검증된10자리 legal_dong_code를
직접 쓰고 geo를 재호출하지 않는다. 기존 Map T1 consumer의 admin 소비는 별도 후속이다.

T4는 [별도 가격 이력 계약](map-service-price-history.md)을 따른다. query는 product/from/to,
limit은 전체 페이지 행수, cursor revision/만료는409다. 위 T2/T3의410과 혼동하지 않는다.
휴게소 가격 이력은501이며 이력 표를 새로 만들지 않는다. Map의 기존 T4 query/parser와
producer 응답 사이 호환 수정은 Map 소유 후속이다.

## Map reader 처리 순서

1. 같은 token/peer로 첫 페이지를 요청하고 gzip을 해제한다. limit은1~5000이며 작업 동안 고정한다.
2. `items`를 작업용 새 집합에 누적한다. 응답의 서명된 next_cursor를 수정하거나 다른 endpoint·limit에
   재사용하지 않는다. snapshot_id와 total_count가 모든 페이지에서 동일한지 확인한다.
3. has_more=false까지 모두 수신하고 누적수량·고유identity를 확인한 뒤 Map의 성공집합을 교체한다.
   부분수신·503·미확인 원천빈응답을 근거로 기존 Map집합을 닫지 않는다. stale은 이전확인집합+상태로 표시한다.
   단, highway-traffic/current의 승인head가 권위정상0을 확정한200(total_count=0/items=[]/
   has_more=false/next_cursor=null)은 유효한 빈 완결집합이다. 이 응답을 무조건 거부하지 않는다.
   참조/parking의 미확인 빈 집합은 서버가503으로 닫는다.
4. 410은 고정snapshot15분TTL 만료다. 작업용 누적값을 버리고 cursor 없이 첫 페이지부터 새로 받는다.
   422는 잘못된/다른scope cursor·limit이며 같은 방식으로 재시작한다. 재시도 횟수와 지연은 Map에서 유한하게 둔다.
5. ETag는 응답페이지의 validator다. 완료한 이전집합의 첫페이지 ETag만 같은 endpoint·limit 요청의
   If-None-Match로 사용한다. 304이면 이미 완결된 Map집합을 유지한다. 미완료 작업이나 다른limit의
   ETag를 완결 성공으로 재사용하지 않는다. TTL이 지났거나 source상태가 달라지면200/410을 처리한다.
6. source가 다음 수집으로 바뀌어도 기존cursor는 최초 DTO를 만료까지 읽는다. 새 조회의 snapshot_id가
   바뀌었다고 중간의 기존페이지를 섞지 않는다. Map 데이터 반영은 완결집합 단위로 한다.

## 503 사유 code와 Retry-After (2026-11-24)

transport 앱이 `/v1/service/exports/*`에서 내는 모든 503(T1·T2·T3·T4·공공 주차장)은 지금까지의 RFC 7807 problem
본문(`type`/`title`/`status`/`detail`/`instance`, 한국어 `detail` 문장 그대로)에 **가산 확장 멤버 `code`**
(UPPER_SNAKE 문자열)를 싣고 HTTP **`Retry-After: <정수 초>`**를 함께 준다. 앞단 프록시·로드밸런서가 만든 503은
이 계약 밖이다(code 없음 → 아래 하위 호환 규칙). 결정 기록은
[ADR-013 개정 2026-11-24](adr/013-internal-service-exports-for-map.md)과
[ADR-005 사실 갱신](adr/005-versioned-rest-api-contract.md)이다(공통 표준 openapi M3, Common T-482).

**계약과 힌트**: `code`의 뜻은 계약이다(새 code 추가는 가산, 있는 code의 뜻 변경은 계약 변경). `Retry-After`
값과 아래 표의 기본값은 **힌트**다 — 운영 중에 바뀔 수 있고, 소비자는 이 값 때문에 정기 polling·tick을 멈추지
않는다. 크게 잡힌 값을 이유로 다음 tick을 건너뛰지 말고, 작은 값을 이유로 같은 run 안에서 바쁘게 다시 묻지 않는다.

| code | 뜻 | Retry-After 힌트(초) | 나오는 경로 | 권장 소비자 처리 |
| --- | --- | --- | --- | --- |
| `EXPORT_SOURCE_NOT_CURRENT` | T1 참조 집합의 마지막 성공이 stale 기준(주유소 27.5시간·휴게소 3일·휴게소 유가 12시간·공공 주차장 90일)을 넘었다 | 수집 상태로 계산해 [60, 3600]: 진행 중인 수집은 `시작 + 예상 수행 시간 − now`(넘겼으면 300), 다음 예정이 미래면 `next_due_at − now + 예상 수행 시간`, 예정이 없거나 지났으면(휴게소 계열은 성공 때 예정을 비움) 1800 | fuel-stations·rest-areas·rest-area-fuel-prices·parking-lots | **HTTP·step 재시도 없이 직전 세대를 유지하고 run은 실패로 끝낸다** |
| `EXPORT_NO_HISTORY` | 근거 수집이 한 번도 성공하지 않았다(T2/T3는 설정에 활성인 scope의 승인 head가 아직 없다) | 5분 주기 집합(교통 current·주차장 current·돌발) 300, 그 밖 3600 | 모든 export, T4 가격 이력 | 위와 같다 |
| `EXPORT_INCIDENTS_NOT_CURRENT` | 돌발 활성 집합이 "지금"이 아니다(마지막 시도 실패·30분 초과). #265 뒤 0건 수집도 실패(`last_error`)로 남으므로 **운영의 0건은 이 code**다 | 300 | highway-incidents/active | 위와 같다 |
| `EXPORT_EMPTY_SET` | 상태는 현재인데 낼 집합이 0건이다 — 돌발의 옛 "0건 성공" 같은 **안전망 분기**, T3 완결 head의 membership 0건 | 300(돌발·5분 주기), 3600(그 밖 T3) | highway-incidents/active, T3 | 위와 같다 |
| `EXPORT_BUSY` | snapshot admission 경합(55P03·40P01을 한 번 새 RR로 재시도한 뒤에도, 반복된 40001·SnapshotRace, 경합 뒤 재시도가 예산을 다 씀) | 10 | T2/T3 | 같은 요청(같은 cursor)을 Retry-After 뒤 짧게 유한 재시도 |
| `EXPORT_PREPARE_TIMEOUT` | 요청 경로 본문 구성 15초 예산 초과, snapshot 안의 statement timeout(57014), 본문 구성 중 handler 상한 25초 초과 | 60 | T2/T3 | 위와 같다 |
| `TRANSIENT_DB` | pool checkout timeout·DB 접속 실패/timeout·PG 기동 중(57P03)·관리자 종료(57P01/57P02)·접속 수 초과(53300)·연결 예외(class 08, 08P01 제외)·끊긴 연결, 본문 구성 밖의 handler 상한 25초 초과(T2/T3/T4) | 15 | 모든 export | 위와 같다 |
| `EXPORT_DISABLED` | `TRANSPORT_MAP_CURRENT_ENABLED=false`라 T2/T3 export가 꺼져 있거나, 그 기준정보의 source가 하나도 설정되지 않았다 | 3600 | T2/T3 | 재시도해도 같다 — 운영 설정 문제로 경보 |
| `EXPORT_SOURCE_INCONSISTENT` | 승인 head·membership·본문·handle이 맞지 않거나 필수 이름·코드가 비었다 | 300 | T2/T3 | 다음 tick(다음 수집·준비가 고친다), 반복되면 경보 |
| `EXPORT_TOO_LARGE` | 고정 집합·승인 head가 export 행 수(head당 10,000)·바이트 상한을 넘었다 | 3600 | T2/T3 | 재시도해도 같다 — 경보 |

- **not-current 계열(위 네 줄)을 초록으로 숨기지 않는다**: 감사 보고서 §5.1의 요구다 — 다시 묻지 않고 직전 세대를
  유지하되 **run은 실패로 끝낸다**. 11월 주유소 export 503 16.6시간 동안 빨간 run이 유일한 신호였다. run을 초록
  "건너뜀"으로 끝내는 것은 서비스 세대 나이가 Valkey `max_age`를 넘으면 경보를 내는 장치가 **함께** 있을 때만
  받아들일 수 있다. 이 처리를 구현한 Map 쪽 관문은 **Map #1549**(503 code 분류·HTTP 층 재시도)다. Map #1542는 같은
  자리에서 transport 503을 초록 `skipped=upstream_not_ready`로 건너뛰는 다른 의미라, #1549 없이 #1542만 들어가면
  이 표의 처리와 어긋난다.
- **Map이 지금 이 code를 다루는 방식(#1549 기준)**: not-current 네 code는 다시 묻지 않고 run 실패, `EXPORT_BUSY`·
  `EXPORT_PREPARE_TIMEOUT`·`TRANSIENT_DB`는 같은 요청을 HTTP 층에서 4회까지(대기 `max(5·10·20초, Retry-After)`,
  한 번 60초 상한) 다시 묻고 다 쓰면 step 재시도·run 실패다. `EXPORT_DISABLED`·`EXPORT_SOURCE_INCONSISTENT`·
  `EXPORT_TOO_LARGE`는 #1549의 분류 표에 없어 **모르는 code**로 다뤄진다 — 예전과 같이 step 재시도(`retryable=True`)다.
  셋 다 재시도해도 풀리지 않는 쪽이므로 Map에 분류를 더하는 것이 후속이다.
- **하위 호환**: `code`가 없거나 모르는 값이거나 공통 사전의 기본값(예: `SERVICE_UNAVAILABLE`)이면 예전과 같이
  "503 = 현재 집합을 낼 수 없음"으로 다룬다. 200 본문·`collection`·`meta`·cursor 의미는 바뀌지 않는다. T4의
  기계 판독 503 `meta.source_status=failed`도 그대로이고 `code=EXPORT_NO_HISTORY`가 더해질 뿐이다. T4의 일시 DB
  불가·handler 상한 503에는 `meta`가 없다(OpenAPI `ServiceExportProblemDetails.meta`는 선택).
- **상태 코드 변경 두 가지(가산 아님)와 배포 보류**: export 경로의 일시 DB 불가와 T2/T3 snapshot 안의 statement
  timeout(57014)은 예전에는 원인 불명 500이었고 이제 503(`TRANSIENT_DB`, `EXPORT_PREPARE_TIMEOUT`)이다. 공개·관리
  경로와 그 밖의 DB 오류는 예전처럼 500이다. **이 변경은 Map #1549가 운영에 배포된 뒤에만 운영에 배포한다**
  ([배포 런북](runbooks/deployment.md)의 보류 항목). #1549 없이 #1542만 있으면 두 code가 초록 건너뜀으로 숨는다.
- **55P03·40P01 재시도와 응답 시간**: T2/T3 첫 고정의 admission 대기 lock_timeout(55P03)·교착(40P01)은 생산자
  안에서 남은 예산이 `대기 + 2초 + 여유 3초` 이상일 때만 0.3~1초 뒤 한 번 더 시도한다. 두 시도는 첫 시도부터 잰
  15초 예산 하나를 나눠 쓴다. 보장하는 것은 **T2/T3/T4 응답이 handler 상한 25초 안에 200이거나 code 있는 503**이라는
  것이다(재시도의 pool 대기는 15초 예산이 아니라 이 상한이 덮는다). T1의 상한은 T1 export 작업이 따로 둔다.
- **유가 stale 기준 변경**: 주유소 export는 마지막 성공 뒤 24시간이 아니라 **27.5시간**까지 200(`collection.last_attempt_failed=true`)이다.
  시작 기준 8시간 tick에서 연속 두 번 실패까지 200이고 세 번째 연속 실패부터 503이다.
- **로그**: code가 있는 응답은 `problem response status=… code=… path=…`(WARNING)로, T4 이력 없음 503도 같은 줄을
  남긴다. 일시 DB 불가와 handler 상한 초과는 `app.core.export_guard`가 예외 종류·원인 종류/errno·SQLSTATE만
  남긴다(처음 한 번과 그 뒤 60초마다 ERROR, 그 사이 WARNING, 원문 SQL·DSN은 남기지 않는다).

## 배포 및 초기 승인

API 이미지와 collector code 모두 새 코드를 사용해야 한다. migration0030~0033을 현재 head까지
적용한다. `TRANSPORT_MAP_CURRENT_ENABLED` 하나가 새 T2/T3 API와 collector 모두를 제어하며
source별 개별 flag가 아니다. 기본값은 false이고 API·CS 환경을 일치시켜야 한다. 운영
overlay(`docker-compose.shared.yml`)에서는 API(`backend`)와 CS가 같은 `x-transport-scope-environment`
앵커를 병합한다. 이 앵커는 플래그와 scope hash 입력(`AIRPORT_CODES_CSV`·`ENABLE_INCHEON_COLLECTION`·
`TRANSPORT_ROUTE_NOS_CSV`·`TRANSPORT_CONZONE_IDS_CSV`)을 함께 둬서, env 파일에서 키가 빠져도 두 프로세스의
기본값이 같다(`backend/tests/test_map_current_env_parity.py`). 활성화 뒤
승인된 정상수집 순서로 scope별 head를 채운다. 이력 전체 backfill은 하지 않는다.
플래그를 켠 직후 head가 없으면 철도(rail-station/nationwide)와 버스(express·intercity)는 최근 플래그 OFF 성공이
있어도 다음 정기 tick을 due로 보고 첫 head를 만든다(48·72시간 guard가 export를 2~3일 503으로 두지 않게,
2026-10-27). 항구는 3일 주기 cron이므로 활성화 직후 Dagster에서 `maritime_reference_collection_job`을 1회 수동 실행해
ferry-ports head를 만든다. 주차·교통은 5분 주기 수집이 곧 head를 만든다.
BUS express/intercity, KAC/ICN처럼 설정에 활성인 source의 head가 모두 준비되기 전에는503이다.
API가 먼저 flagON되어도 미승인·구버전 행을 추정해 export하지 않는다.

공유 daemon은 RUNNING을 유지하고 Transport instigator만 현재 배포런북에 따라 관리한다.
정상 source 수집·서버간 token/peer·새 API 최초snapshot/전체페이지/304/410/stale을 배포 후 별도로
확인한 뒤 Map reader를 활성화한다. 운영 배포·source 실호출은 root가 조율한다.
