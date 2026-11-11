> 이 문서는 c8/c9 당시 증거다. 최신 C11 상태는 [C11 검증 원장](2026-11-12-transport-c11-validation.md)을 따른다.

# Transport 공통 UI·Doctor 최종 후보 검증 — 2026-11-12

지정 clone·`agent/codex-common-unification-20261111`과 기존5672cc2·구현53a8082·계약9e6600a를 보존했다.
현재 설치 정본은 부모 단일 `integration-9-review`, common source는
`2c1182e765bb2bc53e01e0962cf2a73683891e1d`다. 로컬 필수 gate는 통과했지만
정식 RELEASE·독립 Transport 리뷰·원격CI·PRmerge·운영 배포는 아직 완료하지 않았다.

## 동일 산출물·실제 설치

공개/관리자에 같은 UI0.2.0·tokens0.1.1·CSS1.33.0+nativecss.fix.4 원본을 사용한다.
지도 core1.0.1/web1.0.3을 사용하는 관리자는 부모와 같은 tgz를 유지했다.
두 원장도 부모 c9 원본 bytes와 같고, source/tgz/lock/실제 설치를 대조했다.
각 앱의 CSS는 직접 devDependency인 file tgz이며 루트 override는 `"lightningcss": "$lightningcss"`다.
strict install에서 legacy-peer/force는 사용하지 않았으며 독립 npm pack도 만들지 않았다.

실제 설치 파일은 앱마다 UI94·tokens25·CSS19개, 관리자 core25·web85개가 tgz와 같다.
사용하지 않는 예전 vendor는 없으며 공개3종·관리자5종만 남겼다.
parent c9 증거와 직접 tar 비교 모두 UI/tokens 각각의 `package/check-dependencies.mjs`만 달라짐을 확인했다.
VWorld3종·CSSfix4 tgz bytes도 그대로다. 외부 checker와 두 앱 UI/tokens의 실제 checker는 exact2c 코드와 같다.

## 실제 통과 결과

| gate | 공개 web | 관리자 |
| --- | --- | --- |
| c9 installed guard·external canonical | PASS | PASS |
| WSL 타입·ESLint10 경고0 | PASS | PASS |
| Doctor0.9.22 full warning | 오류0/경고0·56파일 | 오류0/경고0·198파일 |
| WSL unit | 164 PASS | 356 PASS |
| 격리 Docker unit | 164 PASS | 356 PASS |
| n150 clean install·native production build | PASS | PASS |
| Alpine Docker production build | exit0 | exit0 |
| native production Chromium | 4/4 PASS | 18/18 PASS |
| Alpine/WASM 실제 image Chromium | 4/4 PASS | 18/18 PASS |
| native·Alpine 실제 Pretendard | WOFF2 200·face loaded | WOFF2 200·face loaded |

두 Doctor는 `complete=true`, `skippedChecks=[]`다. 코드 개선과 좁은 오탐7개는
[Doctor 기록](2026-11-11-react-doctor-findings.md)에 설명했다.
공개 browser는375/1440px 현재 표·RHF 요금·입력 변경·과거 차트·달력·Escape 초점을 확인했다.
관리자18개는 로그인/폰트/필터/탭8·역 매핑4·버스/공항4·375/1440px Dialog 경계/Tab/Escape2개다.
각 CSS 경로의 같은 사례 수를 합쳐 서로 다른 시나리오44개라고 보고하지 않는다.

backend 전체도 종료코드를 회수했다. WSL은1511PASS/0FAIL/39SKIP·exit0·3276.16초,
Docker는1508PASS/0FAIL/42SKIP·exit0·3493.99초이며 각각 warnings6개다.
Docker 추가 skip3개는 Docker CLI가 없는 앱 이미지의 호스트 전용 Compose 렌더 검사다.
backend205파일은 c8 동기화 전후 해시와 mtime이 그대로다.

## c9 정책 검증과 c8 증거 연결

부모 `validation/common-c8-c9-runtime-equivalence.json`과 직접 비교를
`validation/transport-c8-c9-runtime-equivalence.json`에 연결했다.
c8 소스 사본303파일과 비교해 runtime 소스 차이도0건이다.
소비자 차이는 원장·vendor·lock 및 관리자 검사 script의 `--source lib` 보강뿐이다.
명시 source 목록이 lib를 제외하던 부분을 보완해 로컬/CI 검사 범위를 맞췄다.

c8 runtime gate가 모두 통과한 뒤 부모 c9 UI/tokens·원장을 복사하고 명시적 file install로
lock과 설치본의 SRI를 갱신했다. 새 installed guard와 exact2c external canonical은 두 앱 모두 exit0이다.
새 checker로 named/star/namespace reexport·literal import()/require()를 앱마다 격리 검사해
총10개 금지 source가 실제 차단됨을 확인했다. 이 음성 검사의 exit1은 기대한 차단 결과다.
checker만 달라진 c9 때문에 UI unit/native exports/build/browser 전체를 다시 실행하지 않았다.

## 원문 증거

모든 최신 검증 로그는 이 저장소 `validation/transport-*`에 둔다.

- 최종 요약: `transport-c9-validation-summary.json`, `transport-c9-installed-validation.json`.
- c9 guard: `transport-{public,admin}-c9-{guard,external-canonical}.log/.exit`, `transport-c9-guard-probes.json`.
- Doctor/unit: `transport-{public,admin}-c8-{doctor.json,unit.log,docker-unit.log}`.
- production build: `transport-{public,admin}-c8-{native-build,docker-build}.log/.exit`.
- browser: `transport-{public,admin}-c8-{native,docker}-browser.log/.exit`.
- font: `transport-c8-native-font-runtime.json`, `transport-c8-docker-font-runtime-{public,admin}.json`.
- backend: `transport-backend-{wsl,docker}-final.log/.exit`.
- source/mtime: `transport-c8-backend-source-preserved.json`, `transport-c8-c9-app-source-equivalence.json`.

실제로 검증한 QA image는 아래와 같다. 운영에 배포한 image가 아니다.

- 공개 `transport-c8-public-qa:2jhvh18v` — `sha256:851e35f7b3a462b4438041db13c5932b3139697f53d3bdb58edd11817d8025c4`.
- 관리자 `transport-c8-admin-qa:2jhvh18v` — `sha256:f6f66eb943c4901006a53663b34f9fcb98b5a09f0fffd2eb597ca0bfa4159e99`.

## 실패 보존·자원 경계

이전 WSL1510PASS/39SKIP/1FAIL·Docker1507PASS/42SKIP/1FAIL은 옛 지도 버전을 기대한
같은 계약 assertion이었다. 정확한 web1.0.3/core1.0.1 기대값으로 수정한9e6600a 뒤 단독·전체를 재검증했다.
수정 전 collection된 원 전체 실패를 단독 통과와 합쳐 PASS로 바꾸지 않았으며 원 로그를 보존했다.
초기 중단·디스크 고갈·잘못된2GB/noexec 환경도 이전 실패/중단 기록으로 남겼다.
c4 Doctor6/48·브라우저10/2와 c6 기록은 JSON의 candidate6History 및 이전 커밋에 보존한다.

root 고갈 때 관리자 gate 종료코드 기록이 실패해 별도 재실행했다. 큰 설치/빌드는 n150의
본인 전용 `/var/tmp/transport-c8-qa.2jhVH18V`로 분리했다. 첫 Docker Hub TLS 실패는 같은 Node22.23.1-alpine
캐시를 양쪽 동일 image ID로 전달해 해결했고 원 실패 로그도 보존했다.
첫 native browser 준비 대기는 테스트 시작 전 만료됐으며 실제200 뒤 별도4/18을 통과했다.
완료된 본인 native/Docker QA 서버·SSH tunnel만 ID/PID/cwd를 확인해 정리하고 image·로그는 보존한다.
종료 확인한 본인 WSL fixture만 정리했다. 다른 에이전트·기존 사용자 cache·DB/RustFS lifecycle은 건드리지 않았다.
부모 소유 `.github/workflows/common-frontend-policy.yml`은 보존하고 worker 커밋에서 제외한다.

## 부모 go 이후 이미지 배포 계획



1. 최종 UI/tokens/map 단일 pack을 고정하고 양쪽 원장·tgz·lock integrity를 다시 대조한다.
   코드/필수 테스트·독립2리뷰·원격CI·PRmerge까지 확인한 exact merge SHA를 배포 source로 사용한다.
2. `docs/runbooks/deployment.md` 최신 Odroid 절차와 ADR-014를 따른다. Manager CLI의
   `targets validate --json`과 `dagster-instance-config show --json`으로 대상·instance 정본을
   읽기 전용 확인하고 값 자체를 로그에 재출력하지 않는다. 앱·빌드·이미지 장치는 NVMe여야 한다.
3. 저장소 루트가 두 frontend Dockerfile의 실제 build context다. 공개는 `frontend/Dockerfile`,
   관리자는 `packages/kor-travel-transport-admin/frontend/Dockerfile`이다. 공개 디렉터리만을
   admin context로 쓰면 parking-ui file 의존성이 빠진다. `.dockerignore`의 env·백업 제외를 유지한다.
4. 공식 staging과 release lock을 사용하며 원 운영 `.env.prod`, 회전 백업, 중앙 env/override와
   API key·로그인/session 값을 보존한다. env 값·렌더된 Compose 전체·키는 출력/커밋하지 않는다.
   비공개 runtime 값은 기존 env로 주입하고 이미지 빌드 인수의 공개 브라우저 키도 원문을 기록하지 않는다.
5. backend 전체 배포 entry는 `scripts/deploy-prod.sh --host <Manager가 승인한 대상>`,
   관리자 entry는 `scripts/deploy-transport-admin-prod.sh --host <동일 승인 대상>`이다.
   backend 태그는 공식 스크립트의 `kor-travel-transport-backend:rel-<merge SHA 앞12자리>` 규칙을 따른다.
   공개 frontend의 공식 기본 tag는 `kor-travel-transport-frontend:latest`, admin은 `kor-travel-transport-transport-admin-web:latest`
   이름과 전체 `TRANSPORT_ADMIN_RELEASE_SHA`를 사용한다. 표시 tag만 믿지 않고 실제 image ID와
   baked release를 배포 영수증에 함께 고정한다. 새 image ID를 기존 latest 후보와 혼동하지 않는다.
6. 이번 변경의 공개/관리자 이미지를 모두 새로 빌드하되, backend/code-server 동반 전환이 필요하면
   공식 스크립트의 Transport instigator 중지·run/worker drain·원 상태 복구 절차를 지킨다.
   공용 Dagster daemon은 RUNNING 유지, DB/RustFS/다른 테넌트는 recreate/down/삭제하지 않는다.
   admin 전환은 기존 project의 gateway/admin 역할만 선택하며 다른 역할을 제거하지 않는다.
7. 배포 뒤 gateway/backend health와 release SHA, `/login`, 실제 로그인/로그아웃·세션,
   지도↔목록·필터·상세 Escape/포커스, 통계 표, `/parking` 네 뷰·요금 계산을 확인한다.
   320/375/414/768/1440 폭에서 비활성 패널 노출·가로 넘침과 폰트 로드를 확인한다.
   운영 데이터 읽기와 기존 순수 요금 계산만 smoke하며 수집·백업 생성·복원·DB 유지보수는 별도 권한 없이 실행하지 않는다.
8. 실패 시 원 script의 스키마 불변/실패 단계별 rollback 경계를 따른다. backend health 또는 UI 실패를
   code-server만의 rollback으로 덮지 않는다. 불명확한 하위 프로세스 종료와 재배포를 겹치지 않는다.

이 계획은 실제 이미지 배포 완료 보고가 아니다. 부모 go 이전 후보 배포는0이다.
