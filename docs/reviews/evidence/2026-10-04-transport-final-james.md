<!-- SPDX-FileCopyrightText: 2026 digitie -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# James — Transport 최종 후보 독립 적대 리뷰 원본

## 실행·격리

- 실행 ID: `J-TRANSPORT-FINAL-20261004-78172335`.
- 관찰 시작: `2026-10-04 07:32:09 UTC` / `16:32:09 KST`.
- 검증 종료 관찰: `2026-10-04 07:41:13 UTC` / `16:41:13 KST`.
- 저장소: `F:/dev/kor-travel-transport`.
- 실제 base 객체: `e00e634b8502cdd1060d735b250ece96fd9fc945`.
- 실제 후보 객체: `781723356e3f73ae2f48f8df831b3a6970a898e3`.
- PR #67의 `headRefOid`도 후보와 같다. `gh pr view/checks`로 직접 확인했다.
- common Python 소비 pin: `430a9e9cd5429204579792b1d4f8e399366dcb2f`, `backend/pyproject.toml:11`.
- UI tarball 생성 원본은 `9da1889`, 이후 common Python 수정과 UI 코드는 독립적으로 유지된다.
- Windows Git `show`/`diff`/`rev-parse`로 고정 객체를 읽었다. 전체 비교에서 `docs/reviews/**`를 제외했다. 구현자의 이동 worktree source·상대 Popper 원문·통합 peer 판정을 읽거나 사용하지 않았다. 본인 baseline 원본만 참고했다. 소스·설치·DB·컨테이너는 변경하지 않았으며 이 evidence 파일만 작성했다.
- 담당 렌즈: frontend/API 소비 계약, 공통 UI·CSS·접근성, 인증·scope·URL·본문 상한, 대기/오류/정체 표시, live UI 증거. backend 전체 변경 목록과 변경 코드는 UI·운영 계약 연결 관점에서 읽었으며 PostgreSQL 운영 전문 리뷰를 대체하지 않는다.
- 기준 문서: 후보 CLAUDE.md, AGENTS.md, SKILL.md, hostile-review.md, agent-failure-patterns.md, dagster-recovery.md. 심각도는 저장소 hostile-review 기준이다.

## 판정

**PASS — P0/P1 발견 없음. 비차단 P2 두 건이 남는다.** 아래 P2는 수정하거나 `docs/journal.md`에 유지 근거를 남겨야 한다. 이 원본은 이 후보의 James 관점 결과이며 다른 리뷰어 결과·최종 통합 머지 승인·운영 배포 성공을 주장하지 않는다.

## 지적

### J-FINAL-P2-01 — 오래된 대기·시작·취소 중 실행이 전체 실행 조회에서 빠진다

- 위치: `packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts:51`; 소비 병합 `components/dagster-operations.tsx:10-11`; 설명 `docs/runbooks/dagster-recovery.md:51`.
- 분류: **P2**, baseline `J-BASE-P2-02`의 잔여. 이번 변경은 상한·상한 경고를 개선했지만 STARTED 단일 상태는 그대로다.
- 실패 시나리오: 이 location의 오래된 QUEUED 또는 STARTING/CANCELING 실행 뒤에 다른 job의 최신 실행 30개가 쌓인다. 최근 조회에서 이 실행은 밀려나고 active 조회도 STARTED만 허용하므로 목록·진행 중 집계에 나타나지 않는다. 1000건 경고도 발생하지 않는다. 공통 coalescing은 pending 상태도 새 예약을 막기 때문에 사용자가 같은 job의 다음 예약이 합쳐지는 원인을 이 화면에서 찾을 수 없다.
- 독립 재현: 후보의 `dagster-scope.ts`와 `dagster.ts`를 Windows Git으로 읽어 메모리에서 TypeScript transpile했다. WSL Node `v22.22.2`에서 서버가 받은 고정 query의 active 상태를 추출하고, 최근 SUCCESS 30개 + 그 이전 QUEUED/STARTING/CANCELING 각 1개를 query 조건대로 응답하는 fetch fixture로 `getDagsterOverview()`를 실행했다. 출력은 `queryStatuses:["STARTED"], recent:30, active:0, warning:null, omitted:["old-QUEUED","old-STARTING","old-CANCELING"]`였다. 이는 실제 운영 metadata에서 발생시킨 테스트가 아니라 고정 query·클라이언트의 결정적 재현이다.
- 영향: 데이터 손실이나 foreign scope 노출은 없지만, 시작 전·취소 중 정체에 대한 진단 가시성이 부족하다. 현재 live 증거는 STARTED 한 건이므로 이 조건을 다루지 않는다.
- 최소 수정: active query에 `QUEUED, STARTING, STARTED, CANCELING`을 모두 포함하고 1000건 상한·location filter·중복 제거·상한 경고를 유지한다. 최근 30건 밖의 각 상태가 소비 snapshot에 남는 회귀를 추가한다. 시작 시각이 없는 대기 실행의 duration을 임의로 만드는 것은 필요하지 않다.

### J-FINAL-P2-02 — vendoring 문서의 Python pin이 실제 설치 계약과 다르다

- 위치: `packages/kor-travel-transport-admin/frontend/vendor/README.md:24`; 실제 정본 `backend/pyproject.toml:11`.
- 분류: **P2**, 신규 문서 불일치.
- 실패 시나리오·재현: 고정 후보에서 README는 Python 복구 코어를 common `090f984`로 고정한다고 설명한다. 같은 Git 객체의 pyproject는 `430a9e9cd5429204579792b1d4f8e399366dcb2f`를 설치한다. 두 파일을 `git show 781723...:<path>`로 읽으면 바로 확인된다.
- 영향: 실제 설치는 최신 후보이므로 runtime 장애가 발생한 증거는 없다. 다만 확산·재현·감사 과정에서 Python 복구 구현의 출처를 잘못 식별할 수 있다. UI tarball 출처 `9da1889`는 별도이며 그것까지 바꿀 필요는 없다.
- 최소 수정: Python pin 문장만 실제 전체 commit 또는 정확한 short SHA로 맞춘다.

## 검증 방법·결과

### 직접 수행한 확인

- base→후보 전체 파일 목록·diff를 읽었다. 공통 LoginForm에 인증 콜백만 연결하고 AppMenu에 transport href·활성 항목을 제공하는 구조, tokens/theme/Dagster stylesheet import 및 `@source` 포함을 확인했다. 로그아웃 POST·Origin·세션 쿠키 경계와 캐시 정리는 유지된다.
- 고정 scope probe는 임의 query·foreign location 변수·prototype operation 이름 `constructor`를 거부했다. source상 failure UUID 조회에도 서버가 location tag를 덧붙인다. 허용 작업이 GraphQL 원문·mutation을 브라우저에서 받지 않는다.
- proxy는 인증·Origin을 먼저 확인하고 요청 4KiB, 응답 4MiB, fetch signal 10초와 streaming body 상한을 적용한다. 전체 본문을 먼저 읽고 길이를 검사하던 Dagster 경로 baseline P1은 해소됐다. 다른 API의 기존 fetch 헬퍼까지 고쳤다는 주장은 하지 않는다.
- client는 실패 상세 최근 3건, 1000 events/페이지, 최대 20페이지, 15초 신호로 제한한다. failure 상세 장애는 정상 목록을 숨기지 않고 native 실행 링크가 남는다. 20페이지 이후의 원인은 UI 상세에서 생략될 수 있으며 전체 로그는 native UI가 담당한다.
- component는 조회 실패 시 기존 snapshot을 유지하고 오류·재시도를 제공한다. abort된 effect의 응답은 state에 적용하지 않으며 요청 종료 뒤 loading을 해제한다. 중복 recent/active UUID는 Map으로 합친다. runtime tag와 job 한국어 label 연결을 확인했다.
- baseline P2 로그인 비밀번호 유지·동시 제출 문제는 이전에 독립 리뷰한 common LoginForm 계약 소비로 해소됐다. baseline P2 active 조회 상한은 1000건+경고로 해소됐지만 상태 누락은 위 지적으로 남았다.
- candidate common tarball bytes를 Windows Git subprocess에서 직접 읽어 SHA256 및 package-lock SHA512 integrity를 재계산했다. 두 tarball 모두 일치했다. 최초 PowerShell JSON 파싱은 빈 키 때문에 실패했고 `ConvertFrom-Json -AsHashtable`으로 다시 실행한 결과만 PASS로 집계했다.
  - tokens: 23,734 bytes, SHA256 `22b7613085e55885987ce05720a178b65ac649b097763db650b8c7b8b4acaa84`.
  - UI: 25,988 bytes, SHA256 `5c7bb61dce3245bf175795c39a9310782557ce65948ddc161452faa7c0cfca4b`.
- live UI 빌드 원본 `cf30bcfc36277a26f03e0f682d5ec6f1b9672e2b`와 후보의 공개 frontend 및 관리자 frontend를 `git diff --quiet`로 직접 대조했다. exit 0, 두 tree의 코드 차이는 없다.
- GitHub PR check 직접 조회: `37185005593`, `37185007505`의 backend/frontend/transport-admin 각 SUCCESS. `live-e2e` 두 항목은 **SKIPPED**이며 PASS로 바꾸어 기록하지 않았다. 이 실행에서 전체 테스트 suite·build를 직접 재실행하지 않았다.

### 허용된 live 원본 증거의 독립 열람

구현자 원본 `2026-10-04-transport-live-ui.md`와 JPG 네 장을 읽고 이미지 pixels를 직접 열람했다. 원문 해시 `6C2E14391206956A3B9C2FBF016EC6F1E86C08C1459F246DF335B85ADB782828`가 전달값과 일치한다. 전용 n150 compose·production Next·Dagster 1.13.24의 관찰이며 운영 서비스 테스트가 아니다.

- desktop: 한국어 12/12 스케줄, 소유 실패·장시간 실행, active 메뉴와 로그아웃, runtime 4시간·cron 상세가 읽힌다.
- mobile: 375px 표는 내부 스크롤 구조이고 메뉴·로그아웃·경고·요약 카드가 가리지 않는다.
- outage: 오류와 다시 시도 메시지가 기존 12/12와 두 실행 위에 공존한다.
- native failure: 실제 airport job RUN_FAILURE/STEP_FAILURE 이벤트 화면이며 링크의 실패 진단 연결을 뒷받침한다.
- 원문에 정상/실패 로그인·비밀번호 초기화·로그아웃, 320/375/414/768/1440px, 키보드 region/ArrowRight, foreign 제외, Dagster 중지 뒤 snapshot 유지·복원 재시도·확인 시각 갱신이 기록돼 있다. 캡처와 source 계약은 그 기록에 부합한다. 각 실제 입력·클릭은 구현자가 수행했으며 James가 직접 실행했다는 뜻은 아니다.

독립 재계산한 JPG SHA256:

| 원본 | SHA256 |
|---|---|
| desktop | `fc9a3c01f9a3e4a2a041eb207b1a2ff44c6d8b02224c38fad87f18b57a5f217d` |
| mobile | `525455fe7cab0bf4c8ae8b35275a0d6e92166301fdfd261d6bd7aa9f1ada9212` |
| outage | `17f8726d6b4bfec2014160a8eb8522dbce74780d6e5aa39d1e92cf15640da375` |
| native failure | `be511fdcf2eb001884f6c4b29f9678394b9357869d4d541279c991c6b6f85841` |

## NOT_RUN·불확실성

- James의 live browser 독립 조작: **NOT_RUN**. computer-use skill을 읽고 CUA tab 2 선택을 시도했지만 이 child의 `cua.getState()`는 `apps:[], browsers:[]`였다. 부모 브라우저를 임의로 관찰했다고 주장하지 않고 원본 증거 열람으로 범위를 한정했다.
- 운영 shared coordinator 설정 적용·daemon/launcher 실제 worker 강제 종료·5시간 실제 대기·운영 RSS 실측: **NOT_RUN**. parent 원문도 동일 한계를 명시한다.
- legacy untagged run, active 1000건 초과, failure 20,000 event 초과의 실제 장기 운영 조합: **NOT_RUN**. 코드의 상한·경고·native 링크를 정적으로 확인했으며 무한 메모리 누적을 주장할 근거는 없다.
- 상한 1000건은 메모리 보호의 의도된 부분 목록이다. 반면 조회 대상 상태 자체를 제외하는 J-FINAL-P2-01은 상한 설계만으로 설명되지 않는다.
- 본 보고서 파일 SHA256은 저장 후 별도 전달한다. 본문 내 자기 해시는 넣지 않아 원본의 불변성을 유지한다.
