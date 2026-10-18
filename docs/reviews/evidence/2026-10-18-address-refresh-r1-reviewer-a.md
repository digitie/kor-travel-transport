# Transport86 최초 formal FULL 독립 적대적 리뷰 — James r1

**판정: SOURCE_PASS_TRANSPORT_FIXTURE_ONLY. OPEN P0=0 / P1=0 / P2=0. 비차단 P3=1(문서 UI 수치 표현).**
Weather/Common의 별도 PASS로 대신한 판정이 아니다. Transport 전체 소비자 변경과 연결 경로를 새로 읽고 아래 직접 fixture를 실행했다. 운영·배포·실제 provider·새 CPU/RSS 최적화 수용은 포함하지 않는다.

- 실행 ID: /root/review_finish_a. Frontend/live UI·상태 진실성·auth/CSRF·BFF·자기 Dagster scope 렌즈.
- base: 61a566dee0b1cc40f858652c0683883c26e56411.
- exact head: f8e5dd06f8bfe478fdb57785e70b2304958333ad.
- Common pin: c067a7f6a11b106931a73cd7465503d90e54d976.
- manifest: /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r1.json.
- manifest 실제 SHA256: 51a12f61808e910b49d98beeb1242566acbafebc8e174a2152e72a48daafd723.
- 시작 UTC: 2026-10-18T02:58:59.798836+00:00.
- 이번 상대 reviewer의 보고서·결과는 열람하지 않았다.

## 범위·규칙·격리

CLAUDE/AGENTS/SKILL 및 적대 리뷰·반복 실패 runbook, 관련 구조/모델/인수인계 문서를 읽었다. 전체 base→head는 **29파일 954+/10-**다. 모든 diff와 관련 auth/session/Origin/proxy/Button, Backend 관리자 인증, Common callback/테이블 선언을 읽었다. env example/Compose, source union, migration0025, 모델/설정, schema/OpenAPI/TS, Dagster job/sensor, Common pin/lock, BFF/화면/CSS/E2E/tests 및 문서를 포함한다.

제품은 immutable git show로 읽고 소유 임시 디렉터리/메모리 fixture만 사용했다. 제품/index/branch·기존 WIP는 변경하거나 되돌리지 않았다. 시작부터 작성자 소유 untracked 로그9개가 있었다. 내용을 읽거나 변경하지 않았고, 종료 시 동일한9개 경로 외 tracked 변경은 없음을 확인했다. 원 WT를 clean이라고 쓰지 않는다.

임시 Vitest 프로젝트/cache와 SQLite 파일은 소유 TemporaryDirectory 안에 만들고 종료 시 제거했다. 실제 운영/SSH/Docker/실제 provider·키/실제 PG/실제 Dagster SDK 실행/Daemon 조작/브라우저는 0이다. 테스트의 세션 비밀번호·서명키·관리자 token은 새 소유 상수 fixture이며 실제 자격증명이 아니다. 실제 provider SDK 객체도 만들지 않았다.

변경 경로 순서의 path+NUL+해당 head blob SHA256+LF 목록 SHA256:
2040d2fce3a3dac47c0928c48d8d30181c5707c6a26690876196d3cbfcd5d960.

## 발견·판정

새 P0/P1/P2의 재현 가능한 결함은 발견하지 못했다.

### T86-A-P3-01 — 두 viewport 합계13을 각 크기13처럼 읽을 수 있다

위치: docs/reverse-address-refresh.md:26.

문구는 “Chromium 1365×900·390×844에서 13개씩 통과했다”다. 읽는 사람은 각 viewport13/앱26로 해석할 수 있지만 제공된 UI evidence는 **두 크기를 합한 앱당13, 두 앱 합계26**이다. 바로 뒤의 다른 문단·journal/resume는 각 앱13/합계26을 말하므로 실제 기준이나 시험 수용을 52개로 확대할 근거는 없다.

권고: “Chromium 두 크기를 합해 각 앱13개”로 한 문장만 명확히 정산한다. 제품·테스트·시간 제한은 바꾸지 않는다. 이는 비차단 문서 P3이며 UI 실제 성공을 새로 만들어 낸다는 주장이 아니다. exact f8의 문구를 보고서에 보존하고 제품을 수정하지 않았다.

## Frontend/BFF 신뢰 경계

frontend 경로는 packages/kor-travel-transport-admin/frontend 하위다.

### 인증·CSRF·요청 범위

- app/api/address-refresh/route.ts:38–50: GET/POST 모두 hasAdminSession을 요구한다. lib/auth.ts는 실제 서명 세션 검증을 호출한다.
- lib/session.ts는 HMAC-SHA256, 현재 관리자 사용자, 만료, 로그인 설정을 검증한다. session secret 최소 길이/서명 오류를 거절한다. 기존 auth/session/origin/proxy 파일은 base와 byte 동일함을 확인했다.
- proxy.ts의 화면 쿠키 존재 검사는 실 API 권한 검사가 아니다. 새 route 안의 hasAdminSession이 위조 쿠키를 거절한다.
- POST는 exact configured Origin, JSON, bounded1024 body 및 UUID requestId 한 필드만 허용한다. 사용자가 job/location/repository/runConfig를 주입할 수 없다.
- GET은 서버 관리자 token 길이32 이상을 확인한 뒤 /v1/transport/admin/address-refresh에 x-transport-admin-token으로 전달한다. provider 키를 response로 보내지 않는다.
- 기존 signed session의 수명·로그아웃/발급 정책을 새 기능이 바꾼 것은 아니다. 이번 리뷰는 별도 durable revocation을 새로 도입했다고 주장하지 않는다.

독립 actual-HMAC fixture 5시험을 실행했다. auth 함수를 mock하지 않고 고정 session/auth/route를 사용했다. missing/forged cookie가 fetch 전에401, 유효 HMAC GET은 서버 token을 붙여200/no-store, token 미설정503/no fetch, 잘못된 Origin5종·body6종 거절, 초과262144 upstream body502/원문 비노출을 확인했다. **5 PASS / test33ms / 전체360ms / exit0**. actual network 0이다.

Backend main.py:776–798은 require_admin_token 의존성을 명시한 sync 읽기 endpoint다. 기존 admin_token_valid 실패는404로 숨기는 계약을 따른다. 새 endpoint가 provider를 호출하거나 mutation하는 연결은 없다. 이 전체 FastAPI 앱을 실행하지 않았고 본인 API auth 실행 결과라고 확대하지 않는다.

### 자기 Dagster scope·동시 진입·unknown

- lib/dagster-scope.ts의 location은 kor-travel-transport, repository는 __repository__다.
- previous/active query는 address_refresh_job + 자기 location tag로 필터링한다. active는 QUEUED/NOT_STARTED/STARTING/STARTED/CANCELING을 포함한다.
- launch는 자기 location/repository의 고정 job과 force=true op config, request/location/manual tags만 만든다.
- 새 mutation을 일반 readonly DAGSTER_OPERATIONS allowlist에 등록하지 않았다. 기존 readonly operation 이름/변수 검사는 유지된다.
- route.ts:12/:59–60/:91의 동기 check/set/finally로 단일 Node 프로세스 진입을 직렬화한다. guard를 얻지 못한 요청의409가 다른 요청의 guard를 해제하지 않는다.
- 기존 run은 replayed:true로 실제 status를 반환하고 새 launch는false다. 오류는 고정502/불명확 결과 안내이며 raw GraphQL/provider 예외를 반사하지 않는다.
- GraphQL은 각10초, 요약 fetch는12초, body는 각각131072/262144로 제한한다. client POST는35초다. upstream의 불명확한 늦은 완료·여러 replica·재시작까지 exactly-once를 보장하는 구현은 아니다.

고정 route.test.ts 9개를 독립 임시 Git-object 복사로 실행했다: **9 PASS / test23ms / 전체282ms / exit0**. 같은/다른 ID 경합→launch1, previous terminal replay, 이미 active인 run409, 고정 scope/config/tag, 오류 뒤 재진입, auth/CSRF/shape 음성을 포함한다. 이9시험의 auth는 대역이며 위 별도5시험의 actual-HMAC 확인과 구분한다.

단일 Node 프로세스 한계는 docs/reverse-address-refresh.md에 명시돼 있다. 여러 worker/replica 확장 전 공유 원자 경계가 필요하며 배포자가 현 단일 프로세스 가정을 확인해야 한다. 현재 운영 프로세스 수/불명확한 상위 예약 결과를 본인이 관측하지 않았고 전역 exactly-once PASS를 부여하지 않는다.

## UI 상태·요청 경합·접근성

components/address-refresh.tsx는 두 오류 상태를 분리한다. 늦은 상태 GET은 loadError만 지우고 수동 launch의 FAILURE/CANCELED/HTTP 오류는 launchError에 남는다. 실패/취소·성공·기존 queued replay·신규 queued를 각각 다르게 알리고, 실행 기록 링크는 새 예약을 암시하지 않는 명칭이다. 실패 시 requestId 유지, 정상 응답 후 새 의도 ID 발급 경계를 유지한다. busy가 끝나면 버튼이 회복된다.

실제 Transport TSX를 transpile하여 소유 hook/JSX/Button 대역으로 9경로를 실행했다:
- 지연 GET200 뒤에도 FAILURE/CANCELED/HTTP503/network 오류 각각 alert1을 유지한다(4).
- 직접 FAILURE/CANCELED는 오류, SUCCESS는 완료, queued replay는 기존 확인, 신규queued만 새 예약 notice다(5).
전부 PASS/Node exit0. 실제 React DOM/브라우저/scheduler 검증은 아니다. ButtonPrimitive의 실제 이벤트 전달은 정적 소스로 props 전달을 확인했고 이 fixture에서는 native button 대역이다.

화면은 named section/제목, 오류 alert/상태 status, table caption·header, 이름 있는 가로 스크롤 영역 tabIndex0을 제공한다. 표 min-width640을 영역 안에서만 overflow-x:auto로 처리하며 버튼 행은 wrap한다. 실 키보드/스크린리더/모바일 렌더는 본인 NOT_RUN이다. E2E는 1365/390px의 overflow/focus/ArrowRight, empty/config없음/503복구/실패 주소/stale/예약/CSRF를 검사한다. loopback opt-in만 허용하고 실제 provider 호출 시험으로 위장하지 않는다.

## 원천·최종 주소·schema·실패 재개 연결

### Source와 원천 보존

backend/app/services/address_refresh.py:24–45의 source는 fuel_station/bus_terminal/ferry_port/rail_station/rest_area prefix + 원본 PK로 유일 target_key를 만든다. longitude124..132/latitude33..43 범위의 유효 좌표만 union_all하고 전체를 Python 리스트로 materialize하지 않는다. Geo API/token을 조회하지 않는다.

실제 Transport models 전체를 불변 객체에서 로드하고 Commonc067 실제 source/엔진·adapter와 소유 SQLite로 연결했다. 각5종 모델에 유효 좌표1행·좌표 NULL1행씩, 총10행을 넣었다:
- summary/처리는 정확히5대상이며 무좌표5행은 제외된다.
- 같은 좌표5대상은 fixture provider1회 + cache reuse4다.
- 파생 결과5행에 새 address.full이 보인다.
- 전후 원천5개 테이블 모든 열/행은 동일하다.
- provider는 주입 Resolver이며 실제 API/키/SDK/PG 호출은 없다.

이는 Weather 결과 재인용이 아니라 Transport 모델/union/adapter를 새로 실행한 결과다. 원천 주소·관리자 좌표/location_source/raw metadata·과거 fact를 새 파생 주소로 덮는 DML은 추가되지 않았다.

### 최종 표시/사용 범위

GET /v1/transport/admin/address-refresh와 Admin Dagster 표의 최근 최대50개 파생 결과가 실제 사용처다. 표는 address.full/provider/status/stale/확인일/다음날짜를 표시하고 API에는 region도 포함한다. 일반 source/map DTO의 원천 주소를 새 값으로 치환하지 않는다. 이 한계를 manifest와 guide가 명시하므로 “모든 일반 지도 주소가 변경됨”으로 확대하지 않는다. source 좌표가 없으면 기존 정방향 수집이 먼저라는 설명도 맞다.

### migration·DTO·Common

- migration0025는 entries/control 두 테이블 추가이며 기존 source/fact를 변경하지 않는다.
- 실제 upgrade 함수를 op recorder로 실행하여 Common metadata와21열의 이름/type/nullable/PK가 동일함을 확인했다. index3도 확인했다. 실제 DDL/운영 migration은 수행하지 않았다.
- 실제 AddressRefreshSummary Pydantic class AST만 격리해 model_json_schema를 만들고 docs/openapi.json과 정확히 일치함을 확인했다. 새 경로도 존재한다.
- TypeScript 요약/항목 타입은 같은 필드 의미를 유지한다. dict 항목을 arbitrary provider 원문으로 내보내는 구현이 아니라 Common의 유한 summary/sample projection을 소비한다.
- pyproject/uv.lock/direct pin은 c067이며 reverse-address extra를 포함한다. 추가 provider 구현을 이 repo에 복사하지 않는다.
- source.page/source.retries/필수 pending_failures를 Common에 그대로 전달한다. source context의 engine.dispose와 소유하지 않은 fixture resolver를 닫지 않는 경계를 확인했다.
- Common의 calendar6개월·수동 cycle·backoff·owner lease·cursor wrap·동일 좌표 캐시는 별도 검토 제품c067에 위임한다. 이번 actual adapter 실행이 그 callback 계약과 연결된다.

### Daemon OFF·스케줄

backend/app/dagster/address_refresh.py는 자기 location의 job/sensor를 등록하며 _pending은 configured/has_work를 읽는다. 자동 off라도 이미 시작한 수동 cycle의 재시도는 공통 상태 계약에 따른다. 등록은 실제 Daemon start/restore가 아니며 UI도 OFF이면queued 대기라고 설명한다. 실제 자동 주기·run event·failure resume를 Dagster에서 실행하지 않았다. 최신 사용자 CPU/메모리 수집 최적화는 별도 후속이며 이 주소 gate에 추가 구현하지 않는다.

## 작성자/CI/운영 증거와 한계

이 manifest가 전달한 exact-head pull_request workflow39090952872 SUCCESS(backend846/2skip, frontend/Admin)는 root 증거다. 본인이 GH run을 새로 조회하거나 전체846/211을 재실행한 수치가 아니다. **동일 head push workflow39090949959는 요청 시 pending이며 PASS로 계수하지 않는다. merge 전 별도 완료 확인은 root 영역이다.**

안전 evidence SHA를 직접 확인했다:
- reverse-address-final-ui26-verification-20261018.json: fcc89310e250b1828fc65a9151a8ebf92160aa72096bbb734a8790a616702e5e.
- reverse-address-transport-final-docker-verification-20261018.json: 8d068bd19fe3e9ddef6d0f9ae81a1f29b3a93c73feac49862a0a7b43afd84465.

Docker full은 테스트 archive6a93c61의835PASS/13SKIP/793.28초이며 source binding이 다른 과거 증거를 현재 수치처럼 쓰지 않았다. 6a→f8을 직접 비교하여 backend/app/schemas.py 및 frontend/lib/transport.ts 두 EOF whitespace만 다르고 rstrip 본문·Python AST가 같음을 확인했다. Admin211·UI Transport13/Weather13은 외부 root 실행이며 본인14 Vitest/9 TSX 경로에 합산하지 않는다. Docker JSON의 당시 CI pending 문구는 그 evidence 생성 시점 이력이며 현재 PR workflow SUCCESS와 구분한다.

전체 PG/행락/동시 claim, 실제 provider quota/권한, 운영 schema/API/UI/배포, Daemon, 실제 CPU/RSS와 resource limit 효과는 NOT_RUN이다. 단위시험의 범위가 운영 수용을 대신하지 않는다. 실제 root UI26의 원본 전체 로그 hash를 여기서 재계산하거나 스크린샷을 새로 판정하지 않았다.

## 독립 실행 정산

| 본인 확인 | 결과 |
| --- | --- |
| manifest SHA / 전체29변경 binding | 일치 |
| 고정 BFF 시험 | 9 PASS |
| actual HMAC + GET/Origin/body/bounded 음성 소유 시험 | 5 PASS |
| actual TSX 지연 GET·replay·신규예약 | 9경로 PASS |
| 실제5모델/adapter/Common 소유 SQLite | valid5/무좌표5제외/원천동일/1조회4reuse |
| migration 선언/Common table | 21열·index3 일치 |
| 실제 Pydantic schema/OpenAPI | 동일 |
| tested6a→f8 | 두 EOF 변경만 |
| base→head git diff --check | exit0 |
| tracked diff / 원 untracked9경로 | 변경 없음 / 보존 |

초기 자체 Python fixture는 두 번 실패했다. 첫째 0/0 좌표를 넣어 기존 bus 좌표 CHECK에 걸렸고, 둘째 같은 좌표5개가5회 provider를 부를 것이라는 본인 기대가 실제 cache reuse와 달랐다. 원천 제약과 캐시가 정상 동작한 것이며 제품 결함이 아니다. 이후 무좌표 NULL fixture와1조회/4reuse 기대값으로 정정하여 위 검증을 통과했다. 초기 실패를 제품 PASS 시험으로 합산하지 않는다. 고정 경로 조회 중 middleware.ts를 찾은 시도는 이 앱의 실제 proxy.ts 경로로 바로잡았다.

주요 SHA256:
- backend/app/services/address_refresh.py: ec748ebb966879d508d528c3c70fed43d053a0d4f4df032703e5b20d2e73c513.
- frontend/app/api/address-refresh/route.ts: 4dc74f8bea409f98606e0a99b9cc8be0be170d44d7dd1336857d7734bd84e5ca.
- frontend/components/address-refresh.tsx: c3b5296505c08808f10c77afdfb3d1961cfacfa0eeb33fd7ed92af872f6f5e44.

## 최종 결론

SOURCE_PASS_TRANSPORT_FIXTURE_ONLY / OPEN P0/P1/P2=0, P3=1. 직접 확인한 source/격리 fixture 범위에서 기능 차단 결함을 발견하지 못했다. 문서 수치 표현은 위 최소 정산을 권고하며 테스트·운영 기준 완화를 요구하지 않는다. pending 중복 CI와 운영 수용은 별도다. source/index/WIP/운영은 수정하지 않았다.

## 전달받은 요청 원문

```text
Transport86 소비자 최초 formal FULL 독립 적대 리뷰를 요청합니다. 동일 manifest /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r1.json SHA256 51a12f61808e910b49d98beeb1242566acbafebc8e174a2152e72a48daafd723. base61a566dee0b1cc40f858652c0683883c26e56411 -> exactheadf8e5dd06f8bfe478fdb57785e70b2304958333ad. 최종 head pull_request CI39090952872 전체 SUCCESS(backend846/2skip, frontend/Admin); 같은 head push 중복39090949959는 아직 pending이므로 PASS로 세지 말고 merge 전 별도 완료 확인합니다. Common c067/Docker최종835/13skip·Admin211·UI26(각앱13) 증거는 manifest에 구분. Weather/Common의 별도 PASS로 Transport 판정을 대신하지 말고 전체 base→head 및 관련 경로를 새로 검토하세요. Frontend/live UI(반응형·키보드·상태·오류/요청경합·auth/CSRF·BFF·자기Dagster범위) 렌즈이며 통과 목적이 아니라 결함 찾기가 목적입니다. 단일 Node 프로세스 제출 가드/replica 전역 exactly-once 미보장, 파생 주소 Admin/API scope와 원천 보존 한계도 확인하세요. 읽기 전용 immutable object와 소유 임시fixture만; 다른 작업자가 있으므로 소스/index/branch/타인변경 수정·되돌림 금지. 운영/SSH/Docker/실provider/키/Daemon 조작 금지. 새 상대 결과 비공개. /home/digitie/dev/reverse-address-transport-review-james-r1.md에 원문·SHA·P0-P2·파일:행·실패시나리오/판정/한계 및 이 요청 원문을 보존해 주세요. 최신 사용자 CPU/메모리 수집 최적화는 Track1/2 완료 뒤 별도이며 현재 주소 기능 gate만 검토합니다.
```

종료 UTC: 2026-10-18T03:05:53.372577+00:00
