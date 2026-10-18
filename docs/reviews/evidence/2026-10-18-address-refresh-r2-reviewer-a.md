# Transport86 formal FULL post-fix — James 독립 리뷰 r2

**판정: SOURCE_PASS_TRANSPORT_FIXTURE_ONLY. OPEN P0=0 / P1=0 / P2=0 / P3=0.**
이전 T86-B-P2-01은 아래 독립 실제 코드 재현 범위에서 CLOSED, 본인 T86-A-P3-01은 CLOSED다. 현재 head에서 새로운 차단 결함을 발견하지 못했다.

- 검토 실행: /root/review_finish_a — Frontend/live UI·security·상태 진실성 렌즈.
- Base: 61a566dee0b1cc40f858652c0683883c26e56411.
- Exact head: 8c89e1a72d92b54865bb0f2db553c1c2cfe17561.
- 이전 본인 제품: f8e5dd06f8bfe478fdb57785e70b2304958333ad.
- Common pin: c067a7f6a11b106931a73cd7465503d90e54d976.
- Manifest: /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r2.json.
- 실제 manifest SHA256: 96463ba6d27c80a69cb2a3e43db907be47ce809d13301f3ba22f41bf85c3f527.
- 시작 UTC: 2026-10-18T03:30:24.652567+00:00.
- 새 상대 r2 결과는 읽거나 요청하지 않았다. 확정된 r1 양쪽 원문은 역사로 읽었다.

## 전체 범위·불변성·격리

CLAUDE/AGENTS/SKILL 및 hostile-review/agent-failure-patterns의 읽기 전용·독립 검토 규칙을 적용했다. 이전 본인 r1에서 새로 읽었던 전체29파일의 base→f8 기능/연결 경로를 계승하고, 이번 base→8c 전체33파일/1376+/10- 및 f8→8c 모든9파일 변경을 대조했다. 변경 경로+NUL+해당 head blob SHA256+LF로 결박한 전체33파일 SHA는 b888bca0d249c46c4c759ddae2a26fb58007b681d65e736c6358189853b4f6c9다.

이번 제품 변경은 **backend/app/services/address_refresh.py와 backend/tests/test_address_refresh.py 두 경로뿐**이다. 나머지는 journal/resume/guide와 확정 r1 원문/manifest 보존이다. 따라서 전체 frontend/BFF/auth/session/origin/proxy/CSS/E2E/TypeScript, Backend API/schema/OpenAPI/migration/models/Settings/Dagster 등록/Compose/Common pin·lock은 f8과 byte 동일함을 확인했다. 기존 검토를 단순 추정으로 재사용하지 않고 source 불변성을 확인했다.

제품/index/branch/원 WIP를 수정하거나 되돌리지 않았다. 시작·종료 tracked 상태는 변경 없으며 원래 untracked 로그9개 경로는 그대로다. 이 로그들은 읽지 않았다. 소유 임시 디렉터리·메모리 모듈·SQLite fixture만 만들고 종료 시 제거했다. 실제 환경/키, 운영/SSH/Docker/실제 PG/provider/실제 Dagster SDK/Daemon/브라우저 조작 0이다. 보고서 외 영구 새 산출물은 없다.

## T86-B-P2-01 — legacy ferry admission: CLOSED

### 기존 결함과 현재 경계

기존 f8은 국내 숫자 좌표 범위만 검사하여 location_source=data_go_kr_port_guideline의 무효 항구 좌표도 정상 주소의 원천으로 삼았다. 이때 원천 mutation은 없더라도 표에서 stale=false/ok의 정상 파생 주소를 보여 사용자에게 위치가 유효하다고 오해시킬 수 있었다.

기존 정본 근거를 별도로 읽었다:
- backend/app/main.py:826의 관리자 보정 CAS는 해당 provenance 좌표를 무효 취급한다.
- 같은 파일 :1215 및 :1225–1226은 지도 source에서 제외하거나 좌표를 None으로 반환한다.
- rail_maritime_collection.py의 PORT_GUIDELINE_SOURCE 해제 계약도 기존 정책이다.

현재 backend/app/services/address_refresh.py:33–43은 FerryPort branch에
location_source IS NULL OR location_source != data_go_kr_port_guideline을 추가한다. NULL은 SQL의 UNKNOWN 비교에 빠져 함께 제외되지 않도록 명시적으로 살린다. 다른 source branch와 숫자 범위 검사는 그대로다. source selection이 DatabaseAddressSource에 한 번 전달되므로 신규 page뿐 아니라 retry/pending/summary/sample의 같은 원천 join에 적용된다.

### 독립 old→new 실제 코드 재현

실제 Transport models와 f8/8c adapter 두 객체, Commonc067 reverse_address/address_providers 소스를 불변 Git object에서 별도 메모리 모듈로 로드했다. 소유 SQLite에 다섯 원천 table 및 두 파생 table만 만들었다. 실제 provider/키/SDK는 사용하지 않았고 Resolver만 소유 응답 함수다.

FerryPort6행은 서로 다른 국내 유효 숫자 좌표를 가지며 출처는 다음과 같다:
1. data_go_kr_port_guideline
2. admin_manual
3. NULL
4. komsa_port_call
5. vworld_place
6. kakao_place

동일 fixture 결과:

| 관찰 | f8 | 8c |
| --- | --- | --- |
| provider fixture 호출 | 6, legacy 포함 | 5, 키2..6만 |
| source total | 6 | 5 |
| legacy 정상 파생 결과 표시 | 있음 | 없음 |
| NULL/수동/나머지 유효 출처 | 포함 | 모두 포함 |
| 기존 legacy sidecar | 생성 | row 자체 보존, 조회에서 숨김 |
| 원천 전체 열/행 | 보존 | 전후 동일 |

f8 실제 run으로 legacy의 ok 파생 행을 먼저 만든 뒤 8c selection을 적용했다. 새 page/summary/sample은 정확히2..6만 반환하고 legacy 행을 삭제하거나 수정하지 않는다. 새 force 실행도2..6만 호출하며 legacy sidecar 전체 dict가 전후 동일했다.

추가로 소유 fixture의 legacy sidecar만 과거 due error 상태로 만들어 현재 retry/pending 경계를 검사했다:
- next_retry_at가 due여도 source.retries(now,10)은 legacy를 내보내지 않는다.
- pending_failures는 false, summary.failed=0, sample은 legacy를 표시하지 않는다.
- 저장된 error 행 자체는 여전히 그대로다.

이는 새 코드가 단순 “이번 provider 호출만 생략”한 것이 아니라 과거 잘못 게시된 결과의 사용자 표시·집계도 차단한다는 확인이다. 기존 파생 데이터를 영구 삭제해 과거 증거를 없애는 방식이 아니다.

### AUTO=false 수동 실패 cleanup

별도 소유 SQLite에서 f8 실제 force 실행의 legacy1만 provider 오류를 내고 나머지5는 성공시켰다.
- 이전 결과 failed1/remaining1, manual cycle이 남고 backoff 중 has_work(automatic=False)는 false.
- 같은 상태를 8c source로 읽으면 pending_failures=false이며 cleanup 필요로 has_work는 true.
- 새 force=False 배치를 실제 실행하면 provider 호출0, remaining0으로 종료한다.
- 후속 pending은 false, 기존 legacy error 행은 변하지 않으며 원천 provenance/좌표도 그대로다.

따라서 무효 원천 오류가 수동 cycle을 영구 pending으로 붙잡지 않는다. UI의 “수동 실패는 이어 처리” 안내와 새 admission이 충돌하는 반례를 발견하지 못했다. 두 독립 Python fixture는 모두 exit0이며 이번 실행 실패/환경 보정은 없었다. 원래 r1 두 반례/REQUEST_CHANGES는 역사에 보존된다.

## 본인 T86-A-P3-01: CLOSED

docs/reverse-address-refresh.md:26은 “Chromium 1365×900·390×844를 합해 각 앱13개”로 정정됐다. UI13은 두 화면 합계이고 Weather/Transport 총26이라는 실제 evidence와 맞는다. 시험 수/기준/timeout 변경은 없다. 본인 r1의 비차단 P3 원문도 그대로 보존돼 있다.

## Frontend/live UI·security 전체 재확인

이 영역의 소스는 f8과 동일하다. 본인 r1의 **고정 BFF9 PASS, actual-HMAC/Origin/body/summary5 PASS, 실제 TSX의 상태·지연 GET9경로 PASS**를 바이트 동일한 source binding으로 계승한다. 이 숫자를 이번에 다시 실행했다고 쓰지 않는다.

- BFF GET/POST가 서명 세션을 각각 검증한다. 화면 proxy의 쿠키 존재만으로 API 권한이 생기지 않는다.
- exact configured Origin, JSON/UUID 한 필드/1024 bounded body, 고정 자기 location/repository/job/config/tag를 유지한다.
- 신규 mutation은 일반 readonly GraphQL operation allowlist에 들어가지 않는다.
- GET은 서버 관리자 token32 이상 및 고정 요약 경로를 사용한다. Backend require_admin_token은 불일치404로 닫힌다.
- GraphQL 각10초/131072, 요약12초/262144, client POST35초 제한과 raw 오류 비노출을 유지한다.
- submissionInFlight check/set 사이에 await가 없고 finally로 해제한다. 단일 Node 프로세스에서 동시 진입을 막으며 다중 replica/재시작/unknown upstream 확정까지 exactly-once를 보장한 구현은 아니다.
- 실패·취소 replay, 이전 완료, 기존 queued, 신규 예약의 notice/alert 구분이 유지된다. loadError와 launchError를 분리하여 상태 조회 성공이 예약 오류를 지우지 않는다.
- HTTP/네트워크 예약 실패는 요청 ID를 유지하여 결과 확인을 재시도하고, 정상 HTTP 응답으로 이전 terminal run을 확인한 경우 새 수동 의도를 만들 수 있다.
- 버튼 busy/configured, named section/표 header/caption, status/alert, tabIndex0 가로 스크롤·모바일 wrap은 그대로다. 실제 React DOM/키보드/스크린리더/브라우저는 본인 NOT_RUN이다.
- 표의 legacy 행은 Backend source에서 빠지므로 기존 compiled UI가 별도 provenance 분기를 가져야만 숨겨지는 구조가 아니다. 새 API의 sample/total에서 제외됨을 직접 확인했다.

서명 세션 정책·자기 scope는 기존 계약을 그대로 사용한다. durable revocation 또는 분산 원자 예약이 새로 구현됐다고 주장하지 않는다. 이 source PASS가 root의 기존 위임을 새 승인 조건으로 바꾸지는 않는다.

## API·schema·source·공유 의존성·운영 경계

- migration0025의 두 Common table21열/복합 PK/index3, app ALEMBIC_HEAD 및 Pydantic=OpenAPI/TypeScript는 r1과 byte 동일하다. r1의 직접 선언/AST 비교 범위를 계승하며 새 DDL/실제 PG migration을 실행하지 않았다.
- 달력6개월/VWorld 우선·Kakao 보조/batch50 및 상한500/timeout기본5·최대10/순차 bounded 요청·owner lease/backoff/cursor wrap은 Commonc067으로 위임한다.
- source.page/source.retries/필수 pending_failures 메서드 연결, source context의 engine finally dispose, 자기 location job/sensor를 다시 추적했다.
- 활성·queued skip/pending 검사는 실제 Daemon 시작과 별개다. 이 변경은 Daemon을 start/restore하지 않고 OFF 정책을 유지한다.
- 일반 collector/provider 구현·source/fact·관리자 보정·공개 지도/export·기존 스케줄은 바뀌지 않는다. 새 ferry 입구는 기존 지도의 provenance 정책과 동일한 조건을 재사용한다.
- 파생 주소의 최종 사용은 Admin/API의 최근 최대50개 표면이다. 원천 주소/관리자 좌표/과거 fact 또는 일반 locations/지도 필드를 치환하지 않는다.
- 수집 CPU/RSS 최적화는 Track1/2 완료 뒤 별도 workload 실측으로 다룬다는 최신 순서가 문서에 명시돼 있다. 이번 주소 gate로 그 작업을 완료 처리하지 않는다.

## Evidence와 CI 정산

manifest에 지정한 root 안전 증거를 읽었다. 본인 actual operation이나 새 CI 실행으로 합산하지 않는다.

1. reverse-address-transport-legacy-verification-20261018.json SHA256은 ab836d6d3afad71660aef86ff27fbeb5bd18a0bb986922965b4646e9fbcaa6bc로 일치한다. source binding5개도 현재8c Git blob과 각각 일치한다.
2. 현재8c 집중 WSL21/Docker21, root 실제 PG17 drill 및 fresh API/native Dagster loopback UI13은 이 증거의 별도 실행이다. UI compiled source는6a이지만 제품 UI가8c와 동일하다는 한계가 명시됐다.
3. 과거 full Docker835/13SKIP은6a 기능 baseline이다. 이번8c의 full Docker라고 기록하지 않는다. 이전 full CI846/2와 이번 PR CI848/2도 구분한다.
4. 안전 CI JSON transport-address-8c-ci-39092813701.json의 head=8c89/event=pull_request/conclusion=success를 확인했다. backend/frontend/transport-admin은 SUCCESS, live-e2e는 skipped다.
5. 공개 CI backend log에서 “848 passed, 2 skipped, 6 warnings in 910.63s”를 직접 읽었다. 이는 제공된 CI 결과 확인이며 본인 실행한 suite가 아니다.
6. 중복 push39092810095는 전달 당시 진행 중이다. 새로 PASS라고 세지 않으며 merge 전 완료 확인은 기존 root 계획대로 별도다. SKIP인 live-e2e도 PASS로 세지 않는다.
7. legacy JSON에 남은 “당시 full CI pending” 문구는 evidence 생성 시점 이력이며 후속03:28:37 완료된 PR workflow와 구분한다.
8. 해당 Docker JSON image 식별값은 제공된 빌드 증거의 값이다. 본인 Docker inspect/실제 운영 image identity 검증을 한 것으로 확대하지 않는다.

원본 r1 A 보고서 archive는 본인이 저장한 파일과 byte 동일하다(SHA0c6794d1a2da4d2cc9e63e26f97daffedd6ca29a8155f7d63ffc8c08cf745baa). B r1 REQUEST_CHANGES도 보존되어 당시 A source PASS가 원래 B P2를 덮었다고 쓰지 않는다. 새 상대 r2 원문은 열람하지 않았다.

## 독립 정적·실행 결과

| 항목 | 결과/범위 |
| --- | --- |
| Manifest SHA/base/head | 일치 |
| Full33변경 binding | b888bca0… |
| 이전→현재 제품 delta | source/test 두 파일만 |
| 실제 f8→8c ferry source old/new fixture | legacy6→5, NULL/수동 등 유효5 보존 |
| page/summary/sample/retry/pending | legacy 제외·기존 sidecar 보존 |
| AUTO=false legacy 실패 cleanup 실제 배치 | provider0/remaining0/후속pendingfalse |
| 원천 전후 비교 | 불변 |
| P3 guide UI13 범위 | 정정/CLOSED |
| 현재 safety evidence source5 SHA | 전부 일치 |
| base→head git diff --check | exit0 |
| 변경 MD6개 상대 링크43회 | 누락0 |
| tracked 및 기존 untracked9경로 | 변경 없음/보존 |

이번 새 직접 실행은 위 두 Python SQLite fixture·Git/evidence/hash/링크 비교다. r1의 14개 Vitest/9개 TSX·migration/schema 시험은 이번 직접 실행에 합산하지 않는다. 이번 fixture 실패는 없었다. r1 자체 잘못된 fixture의 초기 실패 정산은 원문에 그대로 남긴다.

주요 새 source SHA256:
backend/app/services/address_refresh.py = 9bd7052a38845035fab8dec28fcff28ccc5243679a692da9403d58125a54bff7.

## 미실행 한계와 최종 판정

실제 PostgreSQL 행락/경합/DDL·native Dagster run/event·실제 provider quota/권한·credentials·운영 migration/API/UI/배포/CPU/RSS·다중 Node 프로세스는 본인 NOT_RUN이다. root 기존 PG/loopback 증거와 source PASS를 구분한다. 이 검토의 운영 미실행을 기존 root 위임의 추가 승인 장벽으로 바꾸지 않는다.

SOURCE_PASS_TRANSPORT_FIXTURE_ONLY / OPEN P0/P1/P2/P3=0. 현재 검토 렌즈·격리 실행에서 원 지적을 닫았고 새로운 차단 결함을 발견하지 못했다. source/index/branch·타인 변경은 건드리지 않았다.

## 실제 전달 요청 원문

```text
Transport86 formal FULL post-fix r2를 독립 James/Frontend·live UI·security 렌즈로 수행하세요. 목적은 통과가 아니라 결함 발견이며 애매하면 지적. 정확히 같은 immutable manifest /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r2.json SHA256 96463ba6d27c80a69cb2a3e43db907be47ce809d13301f3ba22f41bf85c3f527. base61a566dee0b1cc40f858652c0683883c26e56411 → head8c89e1a72d92b54865bb0f2db553c1c2cfe17561, WT /home/digitie/dev/kor-travel-transport-codex-reverse-address-20261018. 자신의 r1과 이번 최종 전체 delta를 읽고 새 회귀를 의심하세요. Original r1 B legacy ferry admission P2는 history에 보존하고 이번 수정의 NULL/admin_manual 유지/이전 파생 결과 숨김/원본 불변을 실제 코드로 검증. A P3 UI13은 앱당 두 viewport 합계라는 guide 정정도 확인. exact-head PR CI39092813701 SUCCESS, PostgreSQL848P2S/910.63초, frontend/Admin SUCCESS; duplicate push39092810095는 아직 진행으로 PASS 아님. current8c focusedWSL21/Docker21, 실제PGdrill, freshAPI/native loopbackUI13 PASS; 세부한계 manifest/evidence 필수 확인. 이전6a fullDocker835/13을8c full이라고 읽지 마세요. source/API/UI/migration/shared dependency 전체를 검토하되 production/SSH/provider/daemon/Docker 조작과 env/비밀 접근은 금지. Git object immutable snapshot 및 자신 소유 temp/fixture만 read-only 검증, source/index/branch 변경 금지. 다른 에이전트도 있으니 편집/되돌림 금지. 새 상대 r2 결과는 둘 다 최종 확정 전 읽거나 요청하지 마세요. 기존 확정 r1/common/weather history는 참고 가능. 실제 전달된 이 요청 원문, 관찰한 manifest hash/base/head, 시각/격리, 검사/실패/미실행 한계, 각 findings file:line/구체재현/P0-P2와 기존 P3 disposition을 보존한 최종 원문을 /home/digitie/dev/reverse-address-transport-review-james-r2.md 에 작성하고 SHA256과 verdict/OPEN P0/P1/P2를 보고하세요. 운영 검증의 부재는 SOURCE PASS와 분리하며 root 기존 위임을 새 승인요건으로 바꾸지 마세요.
```

종료 UTC: 2026-10-18T03:34:54.453161+00:00
