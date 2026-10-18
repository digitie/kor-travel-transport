# Transport86 formal FULL 독립 James 리뷰 r3

판정: **CONDITIONAL_SOURCE — 새 P2 2건 OPEN, Source PASS 미발급**.
OPEN P0=0 / P1=0 / P2=2. 작성자가 수정 또는 기존 리뷰 절차에 따른 명시적 disposition을 해야 한다.
기존 ferry admission·current-source MAX·본인 P3는 닫혔지만 아래 새로운 실패 경계를 발견했다.
이는 운영 관측/새 승인요건/Track1·2 전체 완료 판정이 아니다.

## 관찰한 immutable 대상과 격리

- 실제 manifest: /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r3.json.
- 관찰 SHA256: 5effb1be7ca00fd6872f6dd1ef25cc9b9e7f79bae683c3b329d0369e7af92c87, 요청과 일치.
- repo: /home/digitie/dev/kor-travel-transport-codex-reverse-address-20261018.
- base 61a566dee0b1cc40f858652c0683883c26e56411 → exact head 1554783755ccf30be24bcafbab039322c6a685d3.
- 이전 본인 r2 대상 8c89e1a72d92b54865bb0f2db553c1c2cfe17561, Common c067.
- 현재 Common 522525aed3db934767c1c9e742b3bfc68e91679c.
- 실제 시작 UTC 2026-10-18T04:11:44.299384+00:00.
- Linux WSL Ubuntu-26.04의 immutable Git show/diff/tree만 사용. 공유 source/index/branch/checkout·다른 작업자 WIP 변경0.
- CLAUDE/AGENTS/SKILL 및 hostile-review/agent-failure-patterns runbook을 확인했다.
  독립 James lens로 전체 기능과 dependency를 검토했다. 새 상대 r3 결과/모형을 읽거나 요청하지 않았다.
- 자신 소유 TemporaryDirectory, sterile HOME/TMPDIR/PATH/LANG, 공개 read-only Node dependencies와 Python3.12/SQLAlchemy만 사용.
  Vitest용으로 소유 복사본의 cacheDir만 소유 temp로 바꿨고 제품 및 제품 test 본문은 그대로 실행했다.
  추가 반례는 소유 test 사본에만 넣었다. source/private env/키를 읽지 않았다.
- 실제 production/SSH/SDK/provider/DB/Docker/Daemon/브라우저/서버/새 CI 접근·실행0.
  SQLAlchemy metadata·PostgreSQL dialect compile만 사용했으며 DB engine/socket/SQLite도 만들지 않았다.

## 새 지적

### T86-A-P2-01 — 새 주소 패널의 시각·갱신 날짜가 브라우저 시간대에 따라 달라진다

**P2 OPEN.**

- 위치: packages/kor-travel-transport-admin/frontend/components/address-refresh.tsx:10,
  최근 정상 확인 사용 :70, 확인일/다음 갱신일 사용 :90.
- 계약 근거: CLAUDE.md:32는 저장/API UTC aware와 화면 Asia/Seoul을 구분한다.
  기존 lib/journey.ts:36–37의 dateTime도 명시적으로 Asia/Seoul을 사용한다.
- 원인: 새 date 함수는 toLocaleString('ko-KR')만 호출한다. 언어 locale은 시간대를 고정하지 않는다.
- 실패 조건: 관리자의 브라우저/OS 시간대가 UTC 등 KST 이외인 상태. 같은 UTC timestamp의 확인/다음 갱신 날짜가 달라진다.
- 실제 반례: immutable TSX를 TypeScript로 transpile해 소유 Node VM에서 실제 date 함수를 노출하여 실행했다.
  입력 2026-01-31T18:30:00Z:
  - TZ=UTC: 2026. 1. 31. PM 6:30:00
  - TZ=Asia/Seoul: 2026. 2. 1. AM 3:30:00
  - 기존 실제 journey.dateTime은 두 TZ 모두 26. 2. 1. AM 3:30.
  즉 월/일도 바뀐다. 월말 6개월 다음 갱신일을 해석하는 관리자에게 특히 혼동을 준다.
- 재현은 Node의 실제 Intl/Date로 확인했으며 실브라우저를 실행한 것이 아니다.
  기존 브라우저 UI13은 두 viewport 범위이지 서로 다른 timezone 검증이 아니다.
- 권고: 기존 KST dateTime helper를 재사용하거나 명시적인 timeZone:'Asia/Seoul' 옵션을 넣고,
  UTC/Seoul/음수 offset에서 동일 KST 날짜·시각을 요구하는 회귀를 추가한다.
  제품/API 저장 timestamp나 실제 6개월 계산을 바꿀 필요는 없다.

### T86-A-P2-02 — 단일 BFF에서도 launch 결과 불명 후 같은 요청 재시도가 뒤늦은 첫 launch와 중복될 수 있다

**P2 OPEN.**

- 위치: app/api/address-refresh/route.ts:32의 upstream timeout, :63–89의 조회→launch,
  :90–91의 catch 후 무조건 submissionInFlight 해제.
  UI components/address-refresh.tsx:60은 실패 시 requestId를 유지하며 같은 요청으로 재확인하도록 안내한다.
  위 경로 prefix는 packages/kor-travel-transport-admin/frontend/다.
- 실패 조건:
  1. 첫 launchRun 요청이 서버에 도달했으나 run row commit 전에 client fetch가 TimeoutError/전송 오류로 종료된다.
  2. BFF는 502를 반환하고 guard를 푼다. 원격에서 진행하던 요청의 중단/무효가 증명된 것은 아니다.
  3. 사용자가 지시대로 같은 UUID로 재시도한다. 첫 row가 아직 미commit이면 previous/active 조회 모두 빈 결과일 수 있다.
  4. 두 번째 launch가 commit된 다음 첫 요청도 늦게 commit하면 같은 request tag의 native run이 둘 생긴다.
- 이는 복수 replica에서의 전역 exactly-once 문제가 아니다. 하나의 module/Node process에 순차 POST 두 번만으로 발생한다.
  동시 진입 409 회귀는 정상 응답 대기 중의 guard만 검증하므로 이 UNKNOWN 구간을 덮지 않는다.
- 소유 실제-route Vitest 반례: 원래 9개를 그대로 유지하고 위 interleaving을 추가했다.
  첫 mutation의 client promise는 TimeoutError로 reject하지만 서버 측 늦은 commit을 별도 callback으로 보존했다.
  실제 POST 첫502 → 같은 UUID POST 둘째202 → 첫 commit callback 순서에서 launch 호출2/native commit2였다.
  중복 native 수=1 단언이 실제로 실패해 **1 FAIL/9 PASS, 468ms**였다.
  제품 route를 수정하거나 native 결정 알고리즘을 다른 것으로 대체하지 않았다.
  upstream transport/commit interleaving만 대역으로 모델링했다.
- 결과: 한 번의 수동 요청+안내된 재확인이 두 run을 만들 수 있다.
  Common lease가 동시에 같은 sidecar를 쓰지 못하게 하더라도 두 native run/대기·실패 또는 차후 재실행 자체는 남는다.
  단일 process guard와 provider cache만으로 같은 요청의 native 예약 1회를 보장하지 않는다.
- 검증 한계: 실제 Dagster/DB/네트워크에서 이 지연을 주입한 것이 아니다.
  실제 SDK의 launch 처리가 해당 시간 안에 반드시 commit되거나 취소된다는 보장은 이 소비자 코드에 없다는
  source/transport 반례다. 일반 응답 손실이 commit 이후라면 previous 조회가 잡는 정상 경로는 그대로 인정한다.
- 권고: 원격 mutation이 시작된 뒤 결과가 불명확하면 같은 requestId를 곧바로 새 launch로 재사용하지 말고
  readonly 재조회/명확한 UNKNOWN 상태를 유지하거나, native 서버의 원자적 idempotency 경계에 연결한다.
  단순 고정 sleep이나 timeout 증대로 '없음'을 확정하면 안 된다. replica 범위 문구와 별개로 이 한계도 정직하게 다룬다.

## 전체 base→head와 이전 지적 disposition

전체 delta는 37파일1761 additions/10 deletions다.
코드/설정/테스트·OpenAPI·Admin/BFF·CSS·E2E 및 기존 원문 archive를 포함해 읽었다.
37개 changed blob의 결박은 아래 표에 있다. 최신 pin만 보고 기능 승인을 대신하지 않았다.

- **T86-B-P2-01 ferry admission CLOSED.** 실제 address_source는 5개 실제 모델의 readonly union이다.
  좌표 범위 124..132/33..43를 적용하고 FerryPort에서만 guideline 출처를 제외한다.
  NULL과 admin_manual은 남는다. 원천/이전 sidecar를 삭제하거나 업데이트하는 코드가 없다.
- **T86-B-P2-02 provider-wide last MAX CLOSED (source/SQL 경계).**
  실제 Transport 모델 전체를 DB 없이 import하고 actual address_source 함수 AST를 실행해 실제 SQLAlchemy SELECT를 얻었다.
  exact old c067와 new5225의 실제 DatabaseAddressSource.summary를 전달 경계 fake Engine에서 실행해 SELECT objects만 포착했다.
  old MAX는 현재 원천 address_targets join이 없고, 새 MAX는 원천 5종 union+provider/target join 및 longitude/latitude 일치를 포함한다.
  legacy ferry 제외가 MAX의 원천 선택에도 남는다. status='ok' 필터를 추가하지 않아 같은 좌표 실패의 last-good도 남긴다.
  두 모듈 모두 fake Engine에 전달된 것은 SELECT 6개뿐이었다. 숫자/DB 반환값은 위조하지 않고 query 구조만 검사했다.
  삭제·이동·제외·orphan 결과의 수치 PostgreSQL drill은 root 별도 증거이지 본인 DB 실행이 아니다.
- **본인 r1 P3 UI13 표현 CLOSED 유지.** guide:26은 1365×900·390×844를 합해 각 앱13이라고 적는다.
  한 viewport마다13 또는 이번 reviewer가 브라우저13개를 새로 실행했다고 쓰지 않는다.
- 기존 r1/r2 A 원문은 Git archive와 외부 원본 bytes가 각각 동일:
  r1 0c6794d1a2da4d2cc9e63e26f97daffedd6ca29a8155f7d63ffc8c08cf745baa,
  r2 e312cd3fc00977a57c6358e6f8b1e3f320522cbb365b58cce47e336bbb8b28ed.
  기존 B 원문 둘도 외부 확정본과 bytes 동일했다. 새 r3 peer 판정을 참조하지 않았다.
- 원래 r2 Source PASS는 당시 검사 범위의 역사로 보존한다. 오늘 발견한 P2를 과거 보고서에 소급 편집하지 않는다.

## 관련 계약 검토

1. API summary는 main.py:794–798의 require_admin_token dependency로 fail-closed하고 readonly endpoint다.
   DTO/OpenAPI/TS에 같은 top-level summary 필드가 연결된다. 원천 API/지도 응답 필드를 파생 주소로 치환하지 않는다.
2. BFF는 HMAC signed 기존 Admin session, 정확 Origin, JSON/단일UUID, body1024, response bound 128/256KiB와
   generic upstream 오류를 사용한다. 새 route의 scope는 자기 location/implicit repository/address_refresh_job과 force=true로 고정한다.
   readonly GraphQL operation allowlist에 mutation을 등록하지 않는다.
   위 P2-02 외에 임의 job/config·타 project override나 원문 오류/키 반사 경로를 발견하지 못했다.
3. 현재 일반 동시 POST의 module guard, 이전 FAILURE/CANCELED/SUCCESS replay의 상태 분리,
   loadError/launchError 분리는 보존된다. run 링크는 고정 public Dagster base+encodeURIComponent(runId)다.
   문서의 replica 전역 exactly-once 미보장은 유지되지만 UNKNOWN gap과는 별개다.
4. Component는 section/table caption, status/alert, native disabled button,
   focus 가능한 overflow-x:auto 결과 region을 사용한다. 640px table을 좁은 화면에서 가로 스크롤하도록 안내하며
   전체 페이지 overflow 숨김으로 검증을 무마하지 않는다. 실제 반응형/키보드 렌더는 root UI13에만 귀속한다.
5. 소비자 _pending은 Common source.has_work(automatic=설정)로 연결하고 page/retries/pending_failures callback을 그대로 전달한다.
   Common engine은 batch1..500/30초 기본예산, SQL keyset/wrap·retry interleave·owner lease/finally release,
   마지막 정상 payload와 provider error backoff·manual cycle 유지 계약을 보존한다.
   센서는 자기 job/location의 nonterminal을 확인하고 600초 주기로 due일 때만 예약한다.
   자동 sensor default 등록은 daemon 프로세스를 시작하는 코드가 아니다. Daemon OFF 정책을 임의 복구하지 않는다.
6. migration0025는 0024를 parent로 파생 sidecar2표만 추가한다.
   실제 upgrade 함수 AST를 DB 없는 capturing op로 실행해 Common metadata와 비교:
   entries15열/3indexes, control6열/0indexes의 이름·PostgreSQL type·nullable·PK가 모두 동일했다.
   5개 source 모델 AST는 base와 동일하므로 원천 필드/좌표/admin lineage schema를 바꾸지 않는다.
7. root/backend dependency·lock·health assertion의 최신 pin5225를 c067로 역치환하면 r2 세 파일이 각각 bytes 동일하다.
   현재 Common c067→5225의 package source 변경도 reverse_address.py 하나뿐이다.
   r2→155에서 adapter 및 frontend tree 전체는 bytes 동일하다. health helper 구현·interval·SDK·도메인/Compose 정책을 pin과 함께 바꾸지 않는다.

## 본인 직접 검증 결과

- exact BFF Vitest module: **9 PASS /451ms**. auth 미설정/CSRF/job injection/전용 selector/기존 replay/일반 동시성/오류 비반사를 확인.
  인증 자체는 원 테스트의 mock이며 HMAC의 실제 cryptographic 검증을 이 9개로 주장하지 않는다.
  기존 실제 session.ts의 signature/exp/user/config 검사를 source로 읽었다.
- own UNKNOWN interleaving 1개 추가: **원9 PASS+새1 FAIL /468ms**. 위 P2-02의 RED다. 원9를 두 번 더해18 PASS라고 세지 않는다.
- actual component own hook fixture **7 PASS**:
  QUEUED 신규/재조회, SUCCESS, FAILURE, CANCELED 표시;
  늦은 GET200 뒤에도 launch failure 유지;
  전송 결과 불명 후 재시도에 같은 UUID 유지.
  실제 transpiled 함수+소유 hook/JSX façade이며 React DOM/실브라우저 검증이 아니다.
- 실제 Date/Intl 및 기존 helper의 UTC/KST 비교에서 날짜 차이 확인. P2-01의 반례다.
- actual Common+actual Transport source SELECT 구조 old/new 대조: provider/current source/양 좌표 조건 확인, 엔진·DB·socket0.
- migration metadata 2표와 source model5 AST 불변 확인.
- 전체 base..head git diff --check exit0; 변경 MD 상대 file targets53개 missing0.
- 공개 consumer verification SHA31892dbe8c2348052e902438840c5c4028e94fd4ff2e24172015e34579074d1a 및
  legacy verification SHAab836d6d3afad71660aef86ff27fbeb5bd18a0bb986922965b4646e9fbcaa6bc 일치.
- 시험 파일 외 actual source·index·branch 변경0. 임시 시험 프로세스 모두 종료.

## root 증거와 NOT_RUN 한계

manifest가 제공한 exact PR39094548318 backend849 PASS/2SKIP/1603.62초 및 duplicate push39094545635 SUCCESS,
root22/Docker22/UI13/소유 PG drill은 root 귀속이다. 이번 reviewer가 CI 로그/현재 GH 상태·Docker·PG를 새로 실행하거나
직접 관찰한 증거로 세지 않는다. live-e2e skip은 PASS가 아니다.
consumer verification JSON의 생성 시점 Transport CI pending은 당시 기록으로 보존하며 최종 metadata와 모순으로 단정하지 않는다.
old6a+c067 fullDocker835/13과 old8c full848/2·focused21은155의 전체 시험으로 전용하지 않는다.

이번 실제 browser/provider/SDK/DB/PostgreSQL/SQLite/Docker/production migration/deploy/UI/Daemon/CPU·RSS는 NOT_RUN.
단일 process UI/BFF fixture로 운영 다중 instance·실제 timeout 분포나 provider 과금량을 증명하지 않는다.
이 미실행을 새 승인요건으로 확대하거나 root의 기존 위임을 철회하지 않는다.
Track1·2 전체 수용 뒤 CPU/RSS 최적화라는 사용자 순서와 Daemon OFF를 유지한다.

도구 준비 오류: shell에서 git grep regex의 pipe quoting이 한 번 깨져 exit1이었고 Python argv 호출로 즉시 정정했다.
존재하지 않는 origin.test.ts를 한 번 조회해 Git exit128이었으며 실제 origin.ts를 검토했다.
이들은 제품 오류가 아니다. 의도한 새 UNKNOWN 반례 RED 외 소유 fixture 실행 오류0.

## Findings 요약

| ID | 심각도 | 상태 | 핵심 |
| --- | --- | --- | --- |
| T86-A-P2-01 | P2 | OPEN | 주소 확인/다음 갱신 시각이 브라우저 timezone에 따라 날짜까지 변함 |
| T86-A-P2-02 | P2 | OPEN | 원격 launch 결과 UNKNOWN 후 같은 UUID 재시도가 늦은 첫 commit과 중복 가능 |

P0=0/P1=0/P2=2. 기존 지적 closure와 새 실패를 구별하며 이 exact155에 무조건 SOURCE PASS를 발급하지 않는다.

## 37개 immutable changed blob SHA256

| 파일 | SHA256 |
| --- | --- |
| .env.example | 993df92432f86dce5153441ad9adafdfc819a2a202051bbcddea9444d2a14b02 |
| backend/alembic/versions/0025_reverse_addresses.py | 52b52c28c19da21783e3453ea026e9486ebcb5545d160ced4f59ef102aed1128 |
| backend/app/core/config.py | 113a3ef4f03409d651bfacd1228720a7e2bf77bce280bf00011949f97d1a13d6 |
| backend/app/dagster/address_refresh.py | b35d22481f934fd5167952bf209b845b4cd7ff1d398263a6990065ad2063940f |
| backend/app/dagster/definitions.py | 82edf50a11399cbf7cb7638831c0f7d7b9e9017768298d79c1d43884e12d15bd |
| backend/app/db/session.py | 6c1fdaf1dadfd98ed0021770f7c1d0d05e74825384c086e664728070987c3feb |
| backend/app/main.py | 9e3636bc26cdb17a70888cb018de64d698e3840e7719678d281ee8777aca6a82 |
| backend/app/models.py | a7919bc474961b895d0430bfed7b97059ade4c11ab007f8224c3531642908ad9 |
| backend/app/schemas.py | 657bca9fe4a6d4e3278187b87e727d8690f74dffd3f8f2483d8d8034e4267710 |
| backend/app/services/address_refresh.py | 9bd7052a38845035fab8dec28fcff28ccc5243679a692da9403d58125a54bff7 |
| backend/pyproject.toml | dc505626f8d1bb94e8987662daa3b06154ed8d619cbe0688fdab6633a662fd9f |
| backend/tests/test_address_refresh.py | b0fd1ad70a4dac728f40ec1482562d200157b801eeef6e9c2e6a47a2e53f4361 |
| backend/tests/test_health_cpu_contract.py | 5a78b10f5b7203309c8518e62d63440a57a330399c7e03ea01042a921f5cbb10 |
| backend/uv.lock | e3f42cde2719f4f6849ffeda5185572cc41af0c6189e78952d761574d327836f |
| docker-compose.shared.yml | 375777103c9b16f9773f98b259d3f496f9534f3404c322199d174854abaabb82 |
| docker-compose.yml | e581c28dc002270156ad7e60f8c7c5f3b4676b0bd593a3c12b9cba40d9ee85e9 |
| docs/architecture/data-model.md | 90ee9995b1e6f8778835d5d068ea8ad234afc4f05245b66391c7a7c3425ca97b |
| docs/journal.md | d31e6f1d90d585d93eb0afc52f216eaeced299b5ad36cd76c612c75dee94d419 |
| docs/openapi.json | d41a044243c522f77fb8473c3d7df3fe62d161f2cff68526268e1c4d4e0fd907 |
| docs/resume.md | 96709e23e401bda6535805a8c3c04d6b35466e76d50b49fdf64c60315d090674 |
| docs/reverse-address-refresh.md | 26c82701a8ec6acffa6e7a63a0f468107595390212d5f9b2bb4e23d319128d66 |
| docs/reviews/2026-10-18-address-refresh-r1.md | 602d9c4a81c2c30f5dd1c1a715d9a4d25e7a4ea0cec95e89125cc5791adecbab |
| docs/reviews/2026-10-18-address-refresh-r2.md | fd4ecb9a0acc0b20677bc3ce73e765cef537aff9814ae10c8e4d53a4282c71ad |
| docs/reviews/evidence/2026-10-18-address-refresh-r1-manifest.json | 51a12f61808e910b49d98beeb1242566acbafebc8e174a2152e72a48daafd723 |
| docs/reviews/evidence/2026-10-18-address-refresh-r1-reviewer-a.md | 0c6794d1a2da4d2cc9e63e26f97daffedd6ca29a8155f7d63ffc8c08cf745baa |
| docs/reviews/evidence/2026-10-18-address-refresh-r1-reviewer-b.md | 3cf97813be890bd0030d78508d56ccd0ecb95f6bce0adc9033e508f8133a4132 |
| docs/reviews/evidence/2026-10-18-address-refresh-r2-manifest.json | 96463ba6d27c80a69cb2a3e43db907be47ce809d13301f3ba22f41bf85c3f527 |
| docs/reviews/evidence/2026-10-18-address-refresh-r2-reviewer-a.md | e312cd3fc00977a57c6358e6f8b1e3f320522cbb365b58cce47e336bbb8b28ed |
| docs/reviews/evidence/2026-10-18-address-refresh-r2-reviewer-b.md | e3b770f16b506db16483c1c5f2be4098ccf6ad3eaae2ba213f0d7af6ada7e391 |
| packages/kor-travel-transport-admin/frontend/app/admin/dagster/page.tsx | c32cc8ea45d3adacfb0eada99b7cb1d6abb2e6445d96c89ce9a403462069935a |
| packages/kor-travel-transport-admin/frontend/app/api/address-refresh/route.test.ts | 0ee596cd3f960d5867a58a4714832527fbe511353a5607183a2c2232c5d89b6f |
| packages/kor-travel-transport-admin/frontend/app/api/address-refresh/route.ts | 4dc74f8bea409f98606e0a99b9cc8be0be170d44d7dd1336857d7734bd84e5ca |
| packages/kor-travel-transport-admin/frontend/components/address-refresh.module.css | 64ac06bc40ca6740de9dca6d0cc027a915d1af2523d6957d5c9088af1595729d |
| packages/kor-travel-transport-admin/frontend/components/address-refresh.tsx | c3b5296505c08808f10c77afdfb3d1961cfacfa0eeb33fd7ed92af872f6f5e44 |
| packages/kor-travel-transport-admin/frontend/e2e/address-refresh.spec.ts | 623d52a6b5d75a3629e437cfa585cac954eb28df3a9e730d5ec64f71274231f2 |
| packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts | d7d21646c0d94ed597020ec798f93a8075ba9a8c9178fcb720484ece26ecaa5b |
| packages/kor-travel-transport-admin/frontend/lib/transport.ts | af09290f1f26e7e2fc365d3d13a84da2017b6c642736252f8ad01e03d363ae27 |

compact ordered path/SHA256 list SHA256: ef46c7dc7537cb191fbbcf71144db40bacf940bc85d9b2b9db43d096c187547b.

## 실제 전달된 요청 원문

```text
Transport86 formal FULL r3独立レビューをお願いします。immutable manifest /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r3.json SHA2565effb1be7ca00fd6872f6dd1ef25cc9b9e7f79bae683c3b329d0369e7af92c87。base61a566dee0b1cc40f858652c0683883c26e56411→head1554783755ccf30be24bcafbab039322c6a685d3、WT/home/digitie/dev/kor-travel-transport-codex-reverse-address-20261018。Common522525aed3db934767c1c9e742b3bfc68e91679c、old8c/c067のr2 B P2 last_resolved_at問題をCommon40で修正済み。今回exact CI両方SUCCESS; PR39094548318 backend849PASS2SKIP1603.62s、root22/Docker22/UI13/actualPG drillもPASS。元r1/r2 rawと失敗履歴を保持、whole base→155 full review、最終pinだけでなく全feature/依存契約を評価。自身P3 closure/元ferry除外も維持確認。source/own sterile pure fixtures read-only、other agents present、shared source/index/branch変更・production/SSH/SDK/provider/DB/Docker/daemon操作不可。この制約はreviewerのみ。peer新r3は両者finalまで見ない。actual request/hash/time/tests/limits/openP0–P2/verdictを /home/digitie/dev/reverse-address-transport-review-james-r3.md にraw保存しSHA報告。適用AGENTS/レビューrunbookを再利用/確認し、独立FULLをお願いします。
```

검토 종료 UTC: 2026-10-18T04:21:22.772757+00:00

## 원문 확정 직전 root 복구 방향 질문에 대한 별도 설계 메모

위 exact155 판정/반례/본문은 그대로 보존한다. 이 절은 검증 완료 구현안이 아닌 복구를 보존할 후보이며 새 코드/SDK 실행은 없다.
앞선 본문 prefix SHA256은 53733fabe6086e491c7107f570072d0fa7d8c54823b02b4ce071311de273f927이다.

- UNKNOWN 상태를 단순 TTL 후 해제하면 늦은 commit 반례를 해결하지 못한다. 반대로 무기한 process/global guard만 유지하면
  한 번의 오류가 영구 정지가 되므로 그것만으로 수정 종결할 수 없다.
- root는 설치된1.13.24 GraphQL ExecutionMetadata/ExecutionParams에 지정 runId 입력이 없음을 확인했다고 전달했다.
  본인은 SDK/schema를 실행해 재확인하지 않았다. 따라서 현 mutation에 runId 필드만 추가하라는 제안은 하지 않는다.
- 검토할 최소 방향은 이미 존재하는 native run identity의 원자성을 사용하는 것이다. 인증된 고정 job operation에서
  project/location/job/requestId에 결박된 deterministic run_id로 공식 create_run_for_job을 수행하고,
  동일 identity가 이미 있으면 실제 selector/config/tags가 일치하는 run만 재조회하도록 한다.
  create 전에 caller-controlled raw run_id로 다른 project의 run을 재사용하게 해서는 안 된다.
- create 후 submit 사이 중단을 별도 복구 상태로 취급한다. UNKNOWN 재시도는 같은 native identity를 확인/복구해야 하며 새 run_id를
  생성하면 안 된다. submit_run 재시도의 실제 coordinator/queue/worker 의미는 별도 source·소유 SDK 회귀로 검증해야 한다.
  run PK 유일성이 곧 worker exactly-once를 증명한다고 단정하지 않는다.
- 검증해야 할 최소 실패점은 (a) create commit 전 client timeout, (b) commit 후 response loss,
  (c) create 후 submit 전 중단, (d) submit 후 response loss 및 같은 요청 재시도다.
  각각 native run1·고정 scope·재개 가능·중복 dispatch 없음으로 구분해 확인한다.
- UI는 UNKNOWN을 완료로 바꾸지 않고 같은 logical request의 확인/복구를 유지한다.
  매번 새 UUID로 바꾸거나 고정 대기시간을 늘려 불명 상태를 숨기는 방식은 피한다.

이 메모는 기존 권한을 새 승인요건으로 바꾸지 않으며 실제 구현 경로/검증은 root와 작성자 소유다.
추가 기록 UTC: 2026-10-18T04:21:58.615017+00:00
