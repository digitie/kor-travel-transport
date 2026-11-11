## 2026-11-12 — Harvey 인수: C11 소비자 최종 gate 진행

부모 인계 b327e2a의 변경을 보존했다. 최신 상태는 [C11 검증 원장](docs/reports/2026-11-12-transport-c11-validation.md)에 기록한다. 아래 c9 내용은 당시 증거이며 새 엔진 브라우저 PASS를 뜻하지 않는다.

# 최종 소비자 인계 — 2026-11-12

로컬 필수 gate는 모두 통과했다. 전체 통합/릴리스/배포는 아직 미완이다.
현재 HEAD의 이 인계와 frontend 변경이 최종 c9 소비자 소스다. 기존5672cc2·53a8082·9e6600a는 보존했다.
부모 소유 .github/workflows/common-frontend-policy.yml은 보존·커밋 제외다. push/PR/운영 배포는 하지 않았다.

- c9 common2c1182e765bb2bc53e01e0962cf2a73683891e1d의 동일 UI/tokens·원장·lock·실제 checker 설치를 완료했다.
  CSS1.33.0+nativecss.fix.4는 양쪽 직접dev file dependency+루트 $lightningcss override다.
  관리자 core1.0.1/web1.0.3도 같은 부모 원본이다. 공개vendor3종·관리자5종 외 예전 tgz는 없다.
- installed guard·새 external canonical 양쪽 PASS. named/star/namespace reexport·literal import()/require 차단10개 PASS.
  외부/두 앱 UI/tokens checker가 exact2c bytes와 같고 설치 파일 UI94/tokens25/CSS19·관리자 core25/web85를 대조했다.
  admin script에는 명시 source에서 빠진 lib를 보강했다. 부모 workflow는 수정하지 않았다.
- 부모/직접 tar 비교: c8→c9는 UI/tokens 각각 check-dependencies.mjs만 다르다. 앱 runtime 소스 차이0건이다.
  checker-only로 UI build/browser 전체를 반복하지 않았다.
- c8 WSL/Docker unit 공개164/admin356·타입/lint·Doctor0/0(full complete, 생략0) PASS.
  n150 native/Alpine production build 양쪽 PASS, 각 CSS 경로 Chromium 공개4/admin18 PASS.
  두 경로 모두 실제 Pretendard WOFF2 200·loaded face를 확인했다. 추가 Dialog2개는 viewport/Tab/Escape를 검증한다.
- backend WSL1511PASS/39SKIP·Docker1508PASS/42SKIP·각 exit0. 원문은 transport-backend-{wsl,docker}-final.log/.exit.
  backend205파일 해시/mtime은 그대로다. 원 실패/중단 로그를 새 PASS로 덮지 않았다.
- 최신 최종 요약은 validation/transport-c9-validation-summary.json과 docs/reports/2026-11-11-common-ui-validation.{md,json}.
  UI9 installed 검증은 transport-c9-installed-validation.json, source 동등성은 transport-c8-c9-app-source-equivalence.json.
  중요 원 로그는 validation/transport-*이며 QA image와 n150 소스는 review용으로 보존한다.
- 완료된 본인 native/Docker QA 서버와 SSH tunnel은 ID/PID/cwd 확인 후 종료했다. backend 전체는 자연 종료했다.
  다른 에이전트/사용자 cache/DB/RustFS lifecycle은 건드리지 않았다.
- 다음 부모 작업: 통합·Transport 독립2리뷰·원격CI·PRmerge 뒤 parentgo로 공식 새 image 배포·실제 로그인/health/대표화면 smoke.
  배포 context·공식 entry/tag·secret 보존·instigator 경계는 검증 원장의 구체 계획을 따른다.

## 보존한 이전 단계 기록

# 최신 c8 소비자 상태 — 2026-11-12

- 구현53a8082·계약9e6600a 보존, c8 동기화는 현재 dirty다. 부모 workflow는 소유권을 유지하며 제외한다.
- 양쪽 UI/tokens/CSSfix4와 관리자 core/web을 원장·lock·실제 파일 bytes까지 확인했다.
  CSS는 직접dev file dependency+루트 override다. 양쪽 source/canonical guard PASS다.
- c8 WSL unit164/356·lint/type·Doctor0/0, n150 clean install/build PASS.
  native production browser 공개4/admin18 PASS, font WOFF2 200·실제 loaded face 확인.
- n150 root는 validation/transport-c8-remote-runner.json을 읽는다. Docker build 재시도 runner2393019가 진행 중이다.
  동일 Node base를 전달해 metadata TLS 오류를 해결했고 현재 npm ci 이후 단계 확인 중이다.
  완료된 native 서버2383714/2383743·SSH175444만 검증 후 종료했다. 실제 배포가 아니다.
- backend WSL 최종1511PASS/39SKIP·exit0. 원 로그 transport-backend-wsl-final.log/.exit.
  새 Docker 전체 transport-backend-docker-final.log/.exit도1508PASS/42SKIP·exit0으로 종료했다.
  backend205파일 해시/mtime은 transport-c8-backend-source-preserved.json에 확인했다.
- 부모 c9 정본2c1182e가 준비됐다. UI/tokens 각각 checker만 다름을 직접 tar 대조로 확인했다. c8 runtime gate 뒤
  동일원본 vendor/원장/lock/실제 설치·새 guard를 검증한다. checker-only면 전체 UI build/browser 재실행 불요.
- 다음 작업: frontend Docker build/unit/browser, c9 빠른 동기화, 진행 중 backend 결과 회수와 기록/explicit commit.
  독립2리뷰·CI·PRmerge·부모go·실제 새 이미지 배포는 남는다. push/PR/배포는 아직 하지 않는다.

## 이전 단계 인계 기록

# 최신 재개 상태 — 2026-11-11

이하 중단 기록은 과거 이력이다. 현재 worker는 재개했고 기존5672cc2 및 dirty를 보존해 개선을 진행했다.
공개/관리자 Doctor0/0(complete, 생략0), 타입/lint, WSL/Docker unit164/356, 관리자 Chromium16개·공개 Chromium4개가 통과했다.
소비자 상태 소유권·도메인 분리·늦은 요청 취소와 분리 중 빈 상세 오버레이 회귀를 수정했다.
최신 정본은 docs/reports/2026-11-11-common-ui-validation.{md,json} 및 Doctor 기록이다.

현재 미완: backend WSL/Docker 전체 결과 회수, c7 pack 동기화·Transport 독립2리뷰·CI·머지·배포.
설치/실행한 pack은 integration-6-review, canonical은 integration-7-review이나 root/artifacts는 아직c6이다.
부모 소유 .github/workflows/common-frontend-policy.yml은 보존하고 worker 커밋에서 제외한다.

이전 WSL PID67256는1510PASS/39skip/1FAIL로 종료했다. 유일한 실패는 옛 지도 버전 계약이며 아래 집중 재검증에서 수정 확인했다.
수정된 계약을 collection한 WSL 전체 최종 runner PID128658를 시작했다. 로그 transport-backend-wsl-final.log와 .exit를 확인한다. 첫 Docker 실패 환경을 교정해 집중110개를 통과했고
전체 corrected run도 진행 중이다(로그 transport-backend-docker-corrected-full.log). 원 Docker transport-doctor-c6-backend-run-7f7f3d8e87e3는 알려진 실패 환경의 진단 실행으로 종료했다(PASS 아님).
로그: validation/transport-backend-wsl-final.log, transport-backend-docker-corrected-full.log. 이전 중단/디스크 고갈 실행은 PASS 아님.
임시 DB/캐시는 /tmp/transport-c6-qa-8pj9_c8v/backend-wsl-{final-tmp,pycache}와 격리 Docker 내부 tmpfs를 쓴다.
생성 node_modules/.next는 현재 본인 tmpfs의 capsule/frontend 및 capsule/packages/kor-travel-transport-admin/frontend 아래에 있다.
repo에서는 symlink로 참조하고 Next 빌드는 같은 소스 capsule에서 실행한다.
root 부족 때문에 옮겼으며 symlink를 source로 add하지 않는다. 다른 에이전트 tmp/cache는 건드리지 않았다.
F: /mnt/f/dev/transport-common-20261111-qa-ki7cjkq4에는 종료된 diskfull fixture 압축과 미완 의존성 복사본이 있다.
의존성 복사는 여유 복구 후 원본을 보존한 채 중단했다. 다음 설치 시 repo node_modules symlink를 npm이
교체하지 않도록 주의하고, 기존 모듈을 재사용하는 전용 설치 경로에서 lock을 생성해 가져오는 방법을 검토한다.
본인 backend source/venv는 수정/삭제하지 않았고 진행 중 검증은 중단하지 않았다.

## 상세현황 요청 후 추가 관측

- 구현 커밋 `53a8082` 보존. 부모 workflow는 여전히 untracked로 보존하며 worker commit에서 제외한다.
- WSL 전체92% 구간의 실패1건은 test_transport_admin_contract.py의 지도 vendor 버전 계약이다.
  이전 web1.0.1/core1.0.0 두 기대값만 실제 web1.0.3/core1.0.1로 갱신했다.
  별도 WSL/Docker 단일 회귀는 각각1PASS/exit0(`transport-backend-map-contract-{wsl,docker}.log`).
  기존 WSL·진행 중 Docker는 수정 전 collection한 결과이므로 단일 통과를 전체 통과로 기록하지 않는다.
  WSL 이전 임시 fixture만 종료 확인 후2.04GB 정리하고 수정본 전체를 별도 재실행했다.
- 전체 실시간 수는 validation/transport-backend-interim-status.json, 최종 결과는 두 full 로그를 확인한다.
- Doctor 최신 원본은 transport-{public,admin}-doctor-53a8082.json이며0/0 full complete다.
  transport-font-runtime.json의 두 앱 WOFF2 200·로드 face 증거도 확보했다.

## 과거 슬롯 조정 중단 기록

# Transport Doctor 개선 작업 인계 — 2026-11-11

## 중단 사유와 재개 경계

사용자가 common/upstream reviewer B 슬롯 확보를 위해 이 worker 실행을 끝내고
Doctor 개선은 후속으로 미루도록 명시했다. 요청 시점의 코드와 설치 상태를 보존했다.
태스크는 **미완**이다. B 검토 후 저장된 context에서 재개한다.
코드 되돌리기·삭제·reset·checkout·stash는 실행하지 않았고 다른 저장소 소스를 수정하지 않았다.
중단 이후 새 설치·테스트·리팩터링·커밋·push·PR·배포를 진행하지 않는다.
이 인계 파일만 현재 상태 기록을 위해 추가했다.

## 정본 위치

- 저장소: `/home/digitie/dev/common-unification-20261111/kor-travel-transport`
- branch: `agent/codex-common-unification-20261111`
- 보존한 후보 HEAD: `5672cc24934b13492ce19b38ec2e90b47611f1de`
- 현재 미커밋 변경은 아래 Doctor 개선과 integration5-review 동기화다. 스테이징은 비어 있다.
- Windows 도구 cwd는 유효하지 않다. `exec_command`는 `workdir C:\`, `shell powershell`을 사용하고
  개발 명령은 `wsl.exe -d Ubuntu-26.04 -- bash -lc`로 Linux에서 실행한다.
- 긴 편집은 PowerShell UTF-8 here-string을 `wsl.exe --exec python3` stdin에 전달했다.

## 후보 5672cc2와 현재 dirty 검증을 혼동하지 말 것

5672cc2 당시 후보4에서는 WSL 공개164/관리자350 단위, 두 타입·lint·build·guard,
격리 Docker 공개164/관리자350 단위와 공개/관리자 builder build를 통과했다.
Chromium은10통과/공통 탭2실패, Doctor는 공개6/관리자48 warning으로 실패했다.
원장은 `docs/reports/2026-11-11-common-ui-validation.{md,json}`와
`docs/reports/2026-11-11-react-doctor-findings.md`에 있다. 이 기존 원장을 현재 dirty 통과 근거로 쓰지 않는다.
현재 dirty 전체 unit/build/browser는 아직 재실행하지 않았다. 원격CI·독립2리뷰·push·PR·운영 배포도 미실행이다.

## integration5-review 설치

부모 `../artifacts/`에서 UI/tokens와 common-artifacts.json을 두 frontend에 복사했다.
각 frontend로 cd한 뒤 아래 명시 설치를 실행했고 양쪽 guard는 통과했다.

```sh
npm install @kor-travel/ui@file:vendor/kor-travel-ui-0.2.0.tgz @kor-travel/tokens@file:vendor/kor-travel-tokens-0.1.1.tgz --strict-peer-deps --ignore-scripts --no-audit --no-fund
npm run check:dependencies
```

첫 시도는 repo 루트에서 npm --prefix와 상대 file 경로를 조합해 ENOENT로 실패했다.
이후 실제 각 frontend cwd에서 위 명령으로 바로잡았다. force/legacy-peer 플래그는 사용하지 않았다.
새 pack의 source AST 검사와 Dagster focus 보존을 소비한다. 재개 때 부모의 더 새 후보가 생겼는지
확인한 후 같은 파일·원장을 다시 맞춘다. 설치와 해당 frontend의 테스트/서버 실행을 겹치지 않는다.
admin의 file parking-ui는 현재 공개 src 변경 뒤 **재설치하지 않은 상태**다. 마지막 npm install이
up-to-date라고 해도 설치본이 갱신됐다고 가정하지 말고 원본/설치본 해시를 비교한다.
기존 토큰 radix.css bridge·버전 exact·ESLint10·Doctor full warning gate는 유지했다.

현재 체크인 예정 원장에 저장된 정확한 배포 산출물 식별:

- `@kor-travel/ui` `0.2.0` — `sha512-m81yqLBWVdTwA1bwRB/HVOdhi2KFQV5ijMh2QfkxYIV5YUI7o7q7YK8qFCejqqUsz2FAXDPgHm8rcFjibbqfZQ==`
- `@kor-travel/tokens` `0.1.1` — `sha512-95d/E3rHhORo8etrQear9Phtj9PYgoek5yRueAEGFZkXxMGbfrywyH7hjYKVnDRgJak4rotJ653MOWTyKTY+sQ==`
- `vworld-map-web` `1.0.3` — `sha512-9S0TUlgu4ky9ztjkanf0lhoijydhcX5ehHtyQB1jla+rGnuPLK4POiH4wIb2v5ATKuO5hOnHEG534gfyuEH+5g==`
- `vworld-map-core` `1.0.0` — `sha512-tP++7XNg9UYXeeUc+aX8q+RD6/dkVzZuBSXPHUKEqHIRobLjUo1HcPEJruOU0bUzHGxnJL/8reIM7xI+vXYaUw==`

## 보존한 Doctor 수정

### 공개 frontend

- `fee-calculator.tsx`: 요금 요청·Zustand 결과 상태·입력 정체/취소 수명을 `useFeeQuote`로 분리했다.
  폼/공항·주차장 선택은 기존 컴포넌트에 유지했다. 아직 FeeCalculator 자체 복잡도 경고가 남는다.
- `history-chart.tsx`: 터치/마우스 제스처를 `HistorySurface`로 분리했다. HistoryChart 복잡도는 아직 남는다.
- `pages/current-status-view.tsx`: 요약 수치를 순수 `currentMetrics` 모델로 만들고 카드 렌더는 공통 mapping으로 분리했다.
  해당 CurrentMetrics 경고는 마지막 Doctor에서 사라졌다.
- `pages/history-view.tsx`: 조회 수명·취소·결과 scope를 `useHistorySeries`로 분리했다. HistoryView 경고는 아직 남는다.
- backend proxy의 검증된 허용 경로 + `redirect:manual`, dashboard-context의 요청 정체를 검사하는 finally에만
  `react-doctor-disable-next-line`을 붙였다. 사유를 바로 위 한국어 주석에 기록했다. 광역 ignore는 추가하지 않았다.
- 실제 CLI 배포 JS에서 `react-doctor-disable-next-line react-doctor/<rule>` 문법을 확인했다.

### 관리자 frontend

- 비 React export를 별도 모듈로 이동하고 실제 import를 변경했다:
  `lib/vworld-presentation.ts`(키 자리표시자 정리/문자열 redaction),
  `lib/dagster-snapshot.ts`(도메인→common snapshot),
  `lib/reference-places.ts`(여객선 날짜/기준정보 설명).
- `transport-reference-list`의 선택 ID 반복 includes를 Set으로 변경했다.
- `transport-map.test.tsx`의 cluster fixture index key를 point.id로 변경했다.
- `app/api-test/page.tsx`는 response.ok를 명시해 정상/실패 HTTP 상태를 구분하고 네트워크/JSON 오류를 처리한다.
- airport-details/bus-journey/rail-station-mapping의 실제 guarded finally 줄만 해당 loading 진단을
  좁은 근거 주석으로 예외 처리했다. 실제 finally 경계와 AbortSignal/sequence 검사·기존 경합 테스트에 근거한다.
  다른 진단을 baseline이라는 이유로 해제하지 않았다.
- 마지막 관리자 type-check가 transport-reference-list의 hasCoordinates 미정의 2건을 보고했다.
  호출부에서도 필요한 import를 삭제했던 것이어서 import를 복구했다. **복구 후 타입/lint/Doctor 재실행은 하지 않았다.**

## 마지막 검증 로그

- 공개 현재 dirty 타입·lint는 통과했다. 마지막 Doctor JSON:
  `/tmp/transport-doctor-public-r2.json` — 오류0/경고3, gate exit1.
  남은 경고: FeeCalculator(16/13), HistoryChart(16/18), HistoryView(19/17)의 cyclomatic/cognitive 복잡도.
- 관리자 현재 dirty는 위 import 복구 뒤 검증 대기다. `/tmp/transport-doctor-admin-r2.json`은 **없다**.
  type-check가 먼저 실패해서 Doctor까지 도달하지 않았다.
- 앞 후보4 진단 원본: `/tmp/transport-public-doctor-c4.json`, `/tmp/transport-admin-doctor-c4.json`.
- 후보4 unit/build: `/tmp/transport-public-c4-tests.log`, `/tmp/transport-admin-c4-fixed-tests.log`,
  `/tmp/transport-public-c4-build.log`, `/tmp/transport-admin-c4-build.log`.
- 후보4 Docker unit: `/tmp/transport-public-docker-c4-tests.log`, `/tmp/transport-admin-docker-c4-tests.log`.
- 후보4 브라우저: `/tmp/transport-browser-c4.log`,
  admin `test-results/common-c4/`의 screenshot/trace. 로그인/필터6 + 역 매핑4 통과, common 회귀2 실패.
- 버전/무결성 설치 중단은 없다. integration5 양쪽 guard는 통과했고 install 프로세스는 종료됐다.

## 부모에게 보낸 정확한 탭 재현/수정안

1. `packages/kor-travel-transport-admin/frontend/e2e/common-adoption.spec.ts:54`:
   `/fuel`에서 `[data-slot="map-stage"]:visible` 1개를 기대하나2개가 보인다.
   common map-controls.css의 `:not([hidden]) { display:flex }`가 Radix forceMount의 inactive
   data-state도 구분해야 한다. 공통 패널이 inactive일 때 hidden을 주는 방식도 가능하다.
2. 같은 파일`:65`: 375px `/parking`에서 `.parking-views[data-slot=tabs]`의 flex-direction이
   column이어야 하는데 row다. common tabs.tsx의 Root에 `orientation={orientation}`을 실제 전달하고
   data-horizontal/data-active 어휘를 Radix data-orientation/data-state 선택자로 바꿔야 한다.

부모의 최신 지시에서 common orientation 전달 + forceMount hidden + 공식 shadcn CSS 수정 및
계약 시험을 추가 중이라고 확인했다. 이 worker는 앱별 CSS 우회나 common 소스 수정을 하지 않았다.

## 중단한 본인 프로세스

이전 전체 backend 검증 PID25324(uv 부모25320)가 아직 CPU를 사용하고 있어 사용자 자원 우선순위
조정에 맞춰 정확 cwd/pytest cmdline을 확인한 뒤 SIGINT를 전달했다. 두 PID의 종료를 확인했다.
`/tmp/transport-backend-tests.log`는 약51% 진행 뒤 중단 원문/pytest teardown traceback을 보존한다.
중단 중 tmp_path teardown의 KeyError traceback이 생겼다. 전체 backend 통과가 아니며
독립적인 제품 실패로 단정하지도 않는다. 이 로그는 현재 dirty frontend 검증이 아니다.
DB/RustFS/다른 테넌트/다른 에이전트 프로세스는 건드리지 않았다. dev/prod14305 listener와
검증 Compose 컨테이너는 이미 종료돼 있었다. 추가 확인에서 남아 있던 본인 공개14300 서버 PID53693도
정확 frontend cwd/리스너를 확인한 뒤 SIGTERM으로 종료했다.

현재 repo cwd 아래 남은 node/npm/pytest/uv/next/playwright 작업 확인 결과:

없음. 공개14300 서버 PID53693 종료까지 확인했다.

## 재개 후 다음 작업

1. 이 파일·git status/diff·최신 부모 후보 계약을 읽고 현재 dirty를 보존한다. HEAD5672cc2는 유지한다.
2. 관리자 hasCoordinates import 복구를 type-check로 확인한다. vworld helper 이동 후 test mock/import,
   파일 상단 Vitest 환경 주석 위치도 확인한다. 현재 새 lib3개를 누락하지 않는다.
3. 양쪽 Doctor를 다시 실행해 실제 진단 목록을 갱신한다:
   `npm run doctor -- --json --json-out /tmp/transport-doctor-<public|admin>-next.json`.
   script는 실제0.9.22 `--scope full --blocking warning`이다.
4. 남은 복잡도는 도메인 데이터/조회 훅과 표현 컴포넌트로 실제 관심사를 나눈다.
   공개는 FeeCalculator 선택/폼, HistoryChart 계산/표현, HistoryView 달력/결과를 더 나눈다.
   관리자는 조회 수명/표현 분리와 rail mapping의 dirty 소유권·bus terminal visible count 소유권,
   map 445행 책임 분리가 핵심이다. 진단만 숨기는 이름 바꾸기/광역 ignore는 하지 않는다.
5. 공개 src를 admin file parking-ui 설치본에 동기화하고 해시를 비교한다. 새 공개 파일을 만들면
   `frontend/src/package.json` files 목록에도 넣어 Docker admin에서 누락되지 않게 한다.
6. sourceguard·lint/type·unit·Doctor warning0 확인, 부모 common 탭 수정 후보로 두 재현과 대표 브라우저를 재검증한다.
   build/Docker는 최종 소스/산출물 기준으로 수행하고 원장·journal/resume/tasks를 사실에 맞게 갱신한다.
7. 관련 파일만 explicit add하고 후속 커밋한다. 현재 dirty는 미커밋/미검증이므로 완료로 표시하지 않는다.
   독립2리뷰·CI·PRmerge·부모 go 이후에만 이미지 배포한다. 지금은 push/PR/배포하지 않는다.

## 보존한 git status 스냅샷(이 인계 파일 추가 전)

```text
 M frontend/common-artifacts.json
 M frontend/package-lock.json
 M frontend/src/app/api/backend/[...path]/route.ts
 M frontend/src/components/fee-calculator.tsx
 M frontend/src/components/history-chart.tsx
 M frontend/src/components/pages/current-status-view.tsx
 M frontend/src/components/pages/history-view.tsx
 M frontend/src/lib/dashboard-context.tsx
 M frontend/vendor/kor-travel-tokens-0.1.1.tgz
 M frontend/vendor/kor-travel-ui-0.2.0.tgz
 M packages/kor-travel-transport-admin/frontend/app/api-test/page.tsx
 M packages/kor-travel-transport-admin/frontend/common-artifacts.json
 M packages/kor-travel-transport-admin/frontend/components/airport-details.tsx
 M packages/kor-travel-transport-admin/frontend/components/bus-journey.tsx
 M packages/kor-travel-transport-admin/frontend/components/dagster-operations.tsx
 M packages/kor-travel-transport-admin/frontend/components/map-overlays.test.tsx
 M packages/kor-travel-transport-admin/frontend/components/map-overlays.tsx
 M packages/kor-travel-transport-admin/frontend/components/rail-station-mapping.tsx
 M packages/kor-travel-transport-admin/frontend/components/transport-map.test.tsx
 M packages/kor-travel-transport-admin/frontend/components/transport-map.tsx
 M packages/kor-travel-transport-admin/frontend/components/transport-reference-list.test.ts
 M packages/kor-travel-transport-admin/frontend/components/transport-reference-list.tsx
 M packages/kor-travel-transport-admin/frontend/package-lock.json
 M packages/kor-travel-transport-admin/frontend/vendor/kor-travel-tokens-0.1.1.tgz
 M packages/kor-travel-transport-admin/frontend/vendor/kor-travel-ui-0.2.0.tgz
?? packages/kor-travel-transport-admin/frontend/lib/dagster-snapshot.ts
?? packages/kor-travel-transport-admin/frontend/lib/reference-places.ts
?? packages/kor-travel-transport-admin/frontend/lib/vworld-presentation.ts
```
