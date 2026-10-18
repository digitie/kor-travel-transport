# Transport86 최초 formal FULL — Popper 독립 적대 리뷰 r1

판정: **REQUEST_CHANGES**. 현재 exact head의 **OPEN P0=0 / P1=0 / P2=1**.
Weather/Common의 별도 PASS로 이 Transport 소비자 판정을 대체하지 않는다.

## 대상·격리

- Base: 61a566dee0b1cc40f858652c0683883c26e56411
- Exact head: f8e5dd06f8bfe478fdb57785e70b2304958333ad
- Common pin: c067a7f6a11b106931a73cd7465503d90e54d976
- Manifest: /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r1.json
- Manifest SHA256: 51a12f61808e910b49d98beeb1242566acbafebc8e174a2152e72a48daafd723
- 전체 base→head 29파일/954+/10-와 연결 모델·설정·인증·source 품질/수집 경로를 읽었다. 변경 경로 순서대로 path+NUL+SHA256+LF를 연결한 목록 SHA256은 2040d2fce3a3dac47c0928c48d8d30181c5707c6a26690876196d3cbfcd5d960이다.
- CLAUDE/AGENTS/SKILL, agent-failure-patterns/hostile-review, 관련 data-model/resume를 읽었다. 한국어 보고/읽기 전용·독립 리뷰 정책을 적용했다.
- immutable Git object를 추출한 소유 TemporaryDirectory, sterile env/-I/-B 및 --noconftest로만 실행했다. 기본 test conftest의 외부 DB/TRUNCATE와 앱 startup을 호출하지 않았다. 소스/index/branch/WIP 수정·되돌림, 실제 provider/키/운영/SSH/Docker/Daemon 조작 0. 새 상대 리뷰는 읽지 않았다.
- 시작 UTC는 수집하지 않았다. 종료 UTC는 아래에 기록한다.

## T86-B-P2-01 — 무효 legacy 항구 좌표를 정상 최신 주소의 원천으로 채택

**위치:** backend/app/services/address_refresh.py:26–41, 특히 공통 숫자 범위만 적용하는 :33–38.
연결 근거: backend/app/main.py:825–830, :1213–1226; backend/app/services/rail_maritime_collection.py:555–559.

**실패 조건:** FerryPort에 location_source="data_go_kr_port_guideline"이면서 국내 숫자 범위에 드는 legacy latitude/longitude가 남아 있다. 기존 API는 이 출처의 좌표를 무효로 다뤄 보정 CAS에서 None으로 취급하고(:826–830), 지도 조회에서 제외하거나 명시적으로 좌표 None을 반환한다(:1215,1225–1226). 재수집 경로도 이 출처를 확인하면 좌표를 해제한다(:555–559). 따라서 단순 finite/range 통과만으로 유효한 위치가 되는 계약이 아니다.

현재 새 union은 location_source 조건 없이 해당 행을 포함한다. 수동/자동 주소 배치가 그 좌표를 provider에 보내고, 별도 주소 테이블에서 status=ok/stale=false 및 다음 6개월 기한의 정상 파생 주소로 게시한다. Admin 표에는 source의 무효 provenance가 없어 해당 항구에 정상 최신 주소가 생긴 것으로 보인다. 원천 좌표를 덮어쓰지는 않지만 “유효한 좌표의 주소 갱신”과 기존 무효 좌표 정책을 깨뜨린다.

**본인 독립 재현:** 정확 Transport 모델/Settings/address_source/run_address_refresh와 Common c067을 소유 SQLite에 연결했다. 다섯 source 테이블과 새 두 테이블을 만들고 FerryPort 두 행만 넣었다:
- id1: source=data_go_kr_maritime, location_source=data_go_kr_port_guideline, 좌표127.1/37.1
- id2: source=data_go_kr_maritime, location_source=admin_manual, 좌표127.2/37.2
- 필수 이름·port_id·시각은 fixture이고 raw는 보존했다. resolver만 소유 고정 응답이며 실제 provider 호출은 0이다.

정확 함수 출력:
- source.page 대상: ferry_port:1, ferry_port:2
- resolver 호출 키: ferry_port:1, ferry_port:2
- legacy sample: status="ok", stale=false, address 존재
- admin_manual 포함=true, legacy source provenance 보존=true
반례 프로세스 exit0은 “문제가 발생했음을 assert로 확인”한 결과이며 제품 PASS가 아니다.

**영향:** legacy 좌표가 남은 경우 불필요한 provider quota 소비와 잘못된 항구 주소의 정상 표시/장기 캐시. 실제 운영에 이 행이 존재한다고 관찰한 주장은 하지 않는다. 모델/기존 API가 명시적으로 지원·차단하는 상태로 재현했다.

**최소 권고:** FerryPort branch에서 기존 guideline 무효 조건을 source union 선택에 적용한다. 원천 데이터를 정리·변경하거나 관리자 좌표를 덮지 않는다. admin_manual/komsa_port_call/vworld_place/kakao_place의 유효 좌표는 유지한다. legacy 제외·관리자 양성·이미 저장된 legacy sidecar의 summary/sample 숨김·활성 실패 cleanup을 회귀로 확인한다. 수정 후 별도 exact head로 재검토가 필요하다.

## 직접 수행한 독립 검증

### 실제 Transport/Common SQLite 및 schema

정확 제품 module을 임시 src에 추출하고 Weather의 읽기 전용 dependency interpreter를 사용했다. SDK/Dagster import 없이 정확 _pending 함수 AST를 Settings/address_source에 연결했다.

- 다섯 종류가 모두 id1인 경우에도 kind:id 키 다섯 개가 충돌하지 않는다. 서로 다른 좌표에 resolver5회, summary/sample5개.
- 갱신 전후 원천 다섯 테이블의 모든 열을 비교해 동일했다. 원천 주소·좌표·검색 문맥·raw_item_json의 관리자 흔적이 바뀌지 않는다.
- null 짝/0·0/국내 범위 밖은 제외하고 코드의 경계124/33 및132/43은 포함한다. 이는 숫자 범위 검사이며 위 legacy provenance 검증의 대체가 아니다.
- AUTO=false 수동 실패 tail → remaining1/backoff pending=false. cursor 앞 신규 bus_terminal:2는 즉시 처리하며, 119초에는 실패 재시도 run을 요청하지 않고120초에 재개해 완료한다.
- 실패 원천 삭제 후에는 cleanup tick으로 cycle이 끝나고 영구 pending이 남지 않는다.
- 좌표 변경 뒤 이전 좌표의 파생 주소는 sample에서 제외되고 due가 된다.
- resolver 중 시계를91초 진행하고 새 owner가 claim한 반례에서 이전 worker는 OwnershipLost를 전파하고 sidecar를 쓰지 못한다. finally도 새 owner를 해제하지 않는다.
- source context 본문 예외에도 실제 engine dispose가 호출된다. 키 미설정/주입 resolver 없음은 engine 생성 전에 not_configured로 닫힌다.
- migration0025 upgrade의21열 이름/nullable, 두 복합 PK·index 집합이 Common metadata와 일치한다. 별도 source_guard를 보존하고 downgrade 후에도 해당 행이 남는다. PostgreSQL DDL은 compile만 했다. down_revision=0024_collection_run_owner와 앱 ALEMBIC_HEAD=0025가 연결된다.
- 실제 AddressRefreshSummary Pydantic class AST의 JSON schema가 저장 OpenAPI component와 일치한다.
- 기존 test_transport_coordinate_sources_keep_original_fields도 소유 SQLite에서 수행했다.

**실행 정산:** 최초 자체 묶음은6 PASS/3 FAIL. 두 FAIL은 fixture가 별도 행에도 같은 unique identity/terminal_id를 써 insert가 거절된 문제였고, 하나는 좌표가 바뀐 표본이 “주소 None으로 남는다”고 잘못 기대한 fixture 문제였다(정확 계약은 sample에서 제외). 제품을 바꾸지 않고 소유 fixture의 identity를 구분하고 기대를 수정해 해당3시험만 재실행, **3 PASS**를 확인했다. 따라서 서로 다른 검증9개를 확인했으나 단일 전체 묶음9 PASS라고 쓰지 않는다. 최초6/3 및 수정3의 실행 이력도 이 문서에 보존한다. legacy P2는 위와 별도 반례다.

### 실제 Transport BFF/화면 본문 Node VM

정확 route/origin/dagster-scope/component 소스를 transpile했다. 세션과 fetch는 명시적 소유 대역, 실제 network/browser는0이다. **43조건 PASS / Node exit0**:
- same/different requestId의 첫 previous 조회를 막은 동안 후속 요청409, launch1회, 이후 가드 정상 해제.
- 실제 selector가 kor-travel-transport/__repository__/address_refresh_job이고 force=true다. 임의 client job 선택을 허용하지 않는다.
- prior FAILURE/CANCELED/SUCCESS/QUEUED는 원래 status/replayed=true로1조회만 수행한다.
- previous/active/launch 예외 후502·비밀 문자열 미노출, 다음 요청 정상 진입.
- 미인증401/잘못된 Origin403/추가 job 필드422/과대 본문422는 upstream 전에 거절.
- GET이 고정 /v1/transport/admin/address-refresh와 x-transport-admin-token을 사용하며 no-store, private를 반환.
- 실제 component 함수에서 FAILURE/CANCELED/HTTP503/network 실패 뒤 GET200을 늦게 완료해도 launchError를 보존한다.

## 전체 source 계약·운영 설정 확인

- 새 주소 저장은 별도 Common tables이며 기존 fact/원본·관리자 보정 쓰기·export/map 응답을 바꾸지 않는다. 다만 provenance 입구 누락은 위 P2다.
- API의 새 sync GET은 require_admin_token(불일치404)와 threadpool 경계를 사용한다. API는 provider를 직접 호출하지 않고 상태만 읽는다.
- backend pyproject/uv.lock pin은 c067이며 reverse-address extra와 기존 python-vworld-api가 연결된다. Transport의 async DB URL을 Common address_engine이 sync psycopg2로 정규화하고 pool_size1/max_overflow0·connect5초/statement10초/lock2초를 사용한다. source context는 각 작업 뒤 dispose한다. 이 per-engine 제한을 전체 process의 단일 전역 pool 제한이라고 주장하지 않는다.
- Dagster consumer는 page5인자/retries/필수 pending_failures를 정확 전달한다. own location/job/sensor 등록과 active/queued skip,600초 sensor와 수동 cycle/backoff·lease·cursor wrap 연결을 읽었다. Common c067 자체의 별도 리뷰는 의존성 맥락이며 Transport 검증을 대신하지 않았다.
- 설정의 batch1..500/timeout>0..10과 기본50/5, auto=true가 compose/example과 일치한다. shared CS environment와 backend API 양쪽에 provider key/새 옵션이 연결된다. 일반 collector/provider 로직·기존 schedule·daemon OFF 정책은 변경하지 않는다.
- BFF 직렬화는 단일 Node 프로세스다. 복수 replica/재시작/상위 timeout 뒤 늦은 확정까지 전역 exactly-once를 보장하지 않는 문서 한계를 확인했다.
- 최종 주소는 Admin 최근 최대50개/API의 파생 결과다. 일반 locations/map 원천 필드를 치환하거나 관리자 좌표/fact를 갱신하는 기능으로 판정하지 않는다.
- E2E source를 읽었다. loopback 제한, 두 viewport,13case 구조, queued와 완료 구분, 실패·키 없음·503·CSRF 기준을 확인했다. 직접 브라우저를 실행하지 않았다.
- git diff --check base..head는 직접 exit0으로 확인했다.

## CI·기타 증거의 범위

공개 GH read-only 조회에서 정확 f8e5 head의 pull_request39090952872는 completed/success였다. 동일 head push39090949959는 조회 당시 in_progress/conclusion없음이었다. 후자는 PASS에 집계하지 않으며 merge 전 root가 별도 완료 확인해야 한다. 이 리뷰가 새 CI를 실행하지 않았다.

846/2skip, Docker835/13skip(최종 기능6a93와 EOF-only f8 binding), Admin211 및 UI26은 manifest/root의 수치다. 본인 실행에 합산하지 않았다. 실제 PostgreSQL DB/DDL/행락·native Dagster/run·provider 권한/응답·운영 migration/배포/UI·CPU/RSS는 NOT_RUN이다. 수집 CPU/메모리 최적화는 이번 기능 gate 범위 밖이고 Daemon을 시작하지 않았다.

비차단 문구 관찰: docs/reverse-address-refresh.md:26의 두 viewport에서 “13개씩”은 실제 E2E 구조의 두 화면 합 앱당13과 혼동될 수 있다. 실제 수용 수치는 각 앱13/합26으로 구분해야 한다. 이것을 추가 P0/P1/P2로 계수하지 않는다.

## 주요 source SHA256

| 경로 | SHA256 |
|---|---|
| backend/app/services/address_refresh.py | ec748ebb966879d508d528c3c70fed43d053a0d4f4df032703e5b20d2e73c513 |
| backend/app/dagster/address_refresh.py | b35d22481f934fd5167952bf209b845b4cd7ff1d398263a6990065ad2063940f |
| backend/alembic/versions/0025_reverse_addresses.py | 52b52c28c19da21783e3453ea026e9486ebcb5545d160ced4f59ef102aed1128 |
| backend/app/main.py | 9e3636bc26cdb17a70888cb018de64d698e3840e7719678d281ee8777aca6a82 |
| Admin route.ts | 4dc74f8bea409f98606e0a99b9cc8be0be170d44d7dd1336857d7734bd84e5ca |
| Admin component | c3b5296505c08808f10c77afdfb3d1961cfacfa0eeb33fd7ed92af872f6f5e44 |

## 실제 전달받은 요청 원문

parent NEW_TASK payload를 그대로 보존한다. 메시지 자체의 UTC timestamp는 제공되지 않았다.

```text
Transport86 소비자 최초 formal FULL 독립 적대 리뷰를 요청합니다. 동일 manifest /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r1.json SHA256 51a12f61808e910b49d98beeb1242566acbafebc8e174a2152e72a48daafd723. base61a566dee0b1cc40f858652c0683883c26e56411 -> exactheadf8e5dd06f8bfe478fdb57785e70b2304958333ad. 최종 head pull_request CI39090952872 전체 SUCCESS(backend846/2skip, frontend/Admin); 같은 head push 중복39090949959는 아직 pending이므로 PASS로 세지 말고 merge 전 별도 완료 확인합니다. Common c067/Docker최종835/13skip·Admin211·UI26(각앱13) 증거는 manifest에 구분. Weather/Common 별도 PASS로 Transport 판정을 대신하지 말고 전체 base→head와 연결 코드를 새로 검토하세요. Backend/PostgreSQL/ops(5종 원천union/유효좌표·원천보존·migration0025/lineage/DTO/OpenAPI·Common pin/page/retries/pending callback·영속복구/센서/배포설정) 렌즈이며 통과 목적이 아니라 결함 찾기가 목적입니다. 단일 Node 프로세스 제출 가드/전역 exactly-once 미보장, 파생 주소 Admin/API scope도 확인하세요. 읽기 전용 immutable object와 소유 임시fixture만; 다른 작업자가 있으므로 소스/index/branch/타인변경 수정·되돌림 금지. 운영/SSH/Docker/실provider/키/Daemon 조작 금지. 새 상대 결과 비공개. /home/digitie/dev/reverse-address-transport-review-popper-r1.md에 원문·SHA·P0-P2·파일:행·실패시나리오/판정/한계 및 이 요청 원문을 보존해 주세요. 최신 사용자 CPU/메모리 수집 최적화는 Track1/2 완료 뒤 별도이며 현재 주소 기능 gate만 검토합니다.
```

보고서 종료 UTC: 2026-10-18T03:07:24.724682+00:00
