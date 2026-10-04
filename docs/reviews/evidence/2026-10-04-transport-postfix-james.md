<!-- SPDX-FileCopyrightText: 2026 digitie -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# James — Transport 최종 수정 후보 독립 적대 리뷰 원본

## 실행과 격리

- 실행 ID: `J-TRANSPORT-POSTFIX-20261004-027a9ca1`.
- 관찰: `2026-10-04 08:16:14~08:22:14 UTC` / `17:16:14~17:22:14 KST`.
- 저장소: `F:/dev/kor-travel-transport`.
- 실제 base 객체: `e00e634b8502cdd1060d735b250ece96fd9fc945`.
- 실제 수정 후보 객체: `027a9ca1ef943d792278cc8a09964bb6e4ea5c44`.
- 이전 독립 검토 후보: `781723356e3f73ae2f48f8df831b3a6970a898e3`.
- common Python pin: `430a9e9cd5429204579792b1d4f8e399366dcb2f`. common PR #25의 후속 병합 여부와 별개로 pyproject/uv.lock은 이 정확한 객체를 유지한다.
- Windows Git `show/diff/rev-parse`로 고정 소스·테스트·runbook을 읽었다. 전체 base 비교와 이전 후보 이후 delta를 함께 검토했다. `docs/reviews/**`를 diff에서 제외하고 타 리뷰어 원문·통합 판정 문서·peer evidence는 열지 않았다. 첫 전체 delta 출력에는 `docs/journal.md`의 수정 요약이 함께 포함됐지만, 그 요약의 타 리뷰어 판단을 이 리뷰의 검증 근거로 사용하지 않았다. 이후 확인은 제품 source/tests/runbook과 본인 finding에 한정했다.
- 기존 본인 원본은 변경하지 않았다. 작업자 source·설치·venv·DB·컨테이너·Git commit을 수정하지 않았으며 새 원본 evidence 파일만 작성했다.
- 렌즈: 공통 LoginForm/AppMenu/DagsterOperations 소비, API/auth/scope/URL/bodylimit, loading/error/stale/overlap, 레이아웃·키보드·모바일·cron/label, 복구 변경이 UI 계약에 주는 영향.

## 최종 판정

**PASS. 기존 J-FINAL-P2-01/02 모두 CLOSED. 새 P0/P1/P2 finding 없음.**

이 판정은 위 불변 후보의 James 관점 리뷰다. 진행 중인 전체 WSL/Docker 테스트나 운영 배포를 미리 PASS로 선언하지 않는다. 다른 독립 리뷰와 원 작업자의 최종 통합 머지 게이트를 대신하지 않는다.

## 이전 finding disposition

| stable ID | 수정 위치 | 독립 확인 | disposition |
|---|---|---|---|
| J-FINAL-P2-01 | `packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts:51` | active query가 QUEUED/STARTING/STARTED/CANCELING을 모두 포함한다. 1000건 상한·두 run 조회의 location tag filter가 유지된다. 최근 30건 밖 세 상태의 실제 공통 UI 렌더링·링크·한국어 label을 재현했고 시작 시각 없는 pending 상태에 정체 오탐이 없다. source 회귀와 원 작업자 새 live evidence의 실제 metadata assertion/화면이 일치한다. | CLOSED |
| J-FINAL-P2-02 | `packages/kor-travel-transport-admin/frontend/vendor/README.md:24-25` | README의 전체 Python pin이 pyproject와 uv.lock의 `430a9e9cd5429204579792b1d4f8e399366dcb2f`와 일치한다. UI source `9da1889`와 Python revision을 별도로 설명한다. | CLOSED |

## 직접 수행한 검증

### 불변 소스와 공개 계약

이전 후보에서 검토한 base 전체 delta와 이번 후보의 전체 파일 목록/수정 delta를 대조했다. 관리자 frontend의 이번 변경은 scope 한 줄, 회귀 두 파일, vendoring 문서뿐이다. `git diff --quiet 781723... 027a9ca...`로 auth component·shell·app/proxy/CSS·client·streaming helper·tarball이 동일함을 확인했다(exit 0). 공개 frontend 변경도 이번 복구 변경에 포함되지 않는다.

- 로그인 인증·URL 정제·Origin·로그아웃 POST·쿠키·캐시 정리 계약은 유지된다. 공통 메뉴의 실제 href·활성 항목·transport 62rem 전환 및 theme/token import가 유지된다.
- proxy는 인증/Origin 다음 요청 4KiB·응답 4MiB·fetch 10초 및 body streaming deadline을 적용한다. 브라우저의 raw GraphQL/mutation/location selector를 그대로 전달하지 않는다.
- overview는 fail union을 정상 빈 목록으로 바꾸지 않는다. component는 abort된 응답을 적용하지 않고 요청이 실패해도 마지막 snapshot을 유지한다. 재시도 시작과 종료에서 loading/error를 갱신한다.
- 실패 상세는 최근 3개, 페이지 1000 event, 최대 20페이지, 15초 및 화면 조회 25초 신호를 유지한다. 상세 누락 때 native 링크를 통한 진단을 제공한다. 오래된 pending 상태가 추가돼도 실패 상세 조회 수가 늘지 않는다.
- 최근/active 동일 run ID 병합과 per-job runtime tag, 한국어 label, terminal duration, cron 원문·주기 설명, location 범위 native URL 계약이 유지된다.
- backend 변경도 UI/외부 계약 연결 관점에서 읽었다. 만료 상태의 fence 추적 유지, 같은 op의 sticky revoked lease, 후속 provider 중단, 새 session/op의 native owner 조회가 추가되며 공개 DTO·모바일 호출 경로·provider budget 변경은 없다. metadata 오류는 provider 시작 전에 전달하고, terminal 확인과 동일하게 영구 revoked 상태로 바꾸지 않는 회귀가 있다. PostgreSQL 운영 전문 판정은 별도 리뷰의 책임이다.

### 고정 소스 + 고정 UI tarball의 독립 실행

Windows Git이 반환한 후보 `dagster-scope.ts`, `dagster.ts`, `dagster-operations.tsx`와 후보의 UI tgz bytes를 메모리에만 읽었다. tgz를 RAM에서 풀어 dist 모듈을 로딩하고 WSL Node `v22.22.2`/기존 TypeScript/React의 `renderToStaticMarkup`으로 실제 소비 컴포넌트를 실행했다. source 또는 설치 파일을 쓰지 않았다.

검증한 fixture와 결과:

- 최근 SUCCESS 30개 + 최근 밖 QUEUED/STARTING/CANCELING 3개 + 상한 넘은 STARTED 1개 + recent 중복 1개.
- query 상태 배열: `QUEUED, STARTING, STARTED, CANCELING`.
- active 응답 5개와 최근 30개는 UUID 중복 제거 뒤 34개로 병합된다.
- 세 pending 상태의 native 링크와 대기 중/시작 중/취소 중 label이 모두 표시된다.
- pending만 포함한 렌더링에는 정체 의심이 없다. STARTED를 추가하면 정체 summary와 실행 행 표시가 함께 나타난다.
- 실행 표와 스케줄 표의 `role=region`, `tabindex=0` 각각 두 개를 확인했다.
- active 응답 1000개에서 상한 경고를 확인했다.
- failure cursor가 계속 바뀌는 응답에도 20회 뒤 종료하고 null을 반환한다.
- prototype operation `constructor`, overview scope injection, failure scope injection을 모두 거부한다. overview 두 목록에 location filter가 유지된다.
- 고정 tgz SHA256: `5c7bb61dce3245bf175795c39a9310782557ce65948ddc161452faa7c0cfca4b`, 기존 불변 tarball과 일치한다.

실행 출력은 `merged:34, pendingLinksAndLabels:true, pendingNotStalled:true, stalledSummaryAndRow:true, keyboardRegions:2, cap1000Warning:true, failurePageCap:20, foreignAndPrototypeRejected:true`였다.

첫 일반 CJS 모듈 해석 방식은 이 검증 환경의 공통 UI import를 찾지 못했다. 설치 변경 없이 고정 tgz RAM 로딩으로 대체했다. 초기 harness의 정체 문자열 개수와 빈 스케줄 fixture의 region 개수 기대값도 실제 summary/행 및 빈 상태 계약과 달라 실패했다. pending 단독 정체 오탐 검증과 스케줄 1개 fixture로 기대를 구체화한 최종 실행(exit 0)만 PASS로 집계했다. 이 실패를 제품 결함 또는 전체 test suite 실패로 분류하지 않는다.

### CI 직접 확인

`gh pr view 67`의 head는 `027a9ca1ef943d792278cc8a09964bb6e4ea5c44`였다. `gh pr checks`를 직접 읽어 다음 두 실행의 backend/frontend/transport-admin 각각 SUCCESS를 확인했다.

- `https://github.com/digitie/kor-travel-transport/actions/runs/37187027193`
- `https://github.com/digitie/kor-travel-transport/actions/runs/37187024121`

두 workflow의 live-e2e 항목은 **SKIPPED**다. 이를 live PASS로 바꾸어 집계하지 않는다. 전체 테스트 수치와 build 실행을 본 리뷰에서 직접 재실행했다는 주장도 하지 않는다.

## 허용된 새 live 증거 열람

원 작업자의 `2026-10-04-transport-live-ui-postfix.md`와 `2026-10-04-transport-postfix-{desktop,pending,mobile,outage}.jpg`만 읽었다. 전용 n150 Compose·후보 027a9ca production Next·Dagster metadata를 사용한 원본이다. 실제 provider 수집 성공과 metadata fixture SUCCESS를 구분하고, 실제 Failure op와 합성 과거 STARTED를 구분해 기록했다.

원문 SHA256 `79368B90F018D6739995CC9F833EB63D8756358784D172351DFEC18BEE8CA8C7`가 전달값과 일치한다. 네 JPG도 직접 해시 재계산하고 pixels를 열람했다.

| 증거 | SHA256 | 읽힌 내용 |
|---|---|---|
| desktop | `181CDF2208558E92D4569C1FC33747B33A7AD6379A49F754801CDBB68C4489B9` | 12/12 스케줄·최근 34개·성공29·실패1·정체1, 실제 native failure 메시지, 메뉴 Dagster 활성 |
| pending | `4DF130A8B03E68E91DEA1984ED1699A3274997D9469633C12B771385D94B067F` | 취소 중·시작 중·대기 중 세 실제 ID와 STARTED 정체 행, 각 native 링크 |
| mobile | `418B576479109920B30412DA2FEB6F7F4856683D495C3D3388EBAE7BBAD67D49` | 메뉴·로그아웃·경고·두 열 카드·조회 확인 시각이 좁은 폭에서도 읽힘 |
| outage | `19FCFCC8904A6EE2571BE72F5578F733E99686AB83AB050D9F1306BD215F1011` | 한국어 조회 오류·다시 시도 안내가 기존 34개/12개 snapshot과 함께 유지됨 |

원문은 세 pending run이 실제 `get_runs(limit=30)` 결과에서 빠진다는 assertion 뒤 브라우저에서 추가 목록 표시를 확인했다. 해당 ID 접두사와 label이 pending 캡처에 일치한다. 375 viewport의 실제 DOM 폭360, 표 scrollWidth608/width308과 ArrowRight 0→40, 전용 Dagster 중지 뒤 snapshot 유지·복원 재시도·확인 시각 17:03:54도 기록돼 있다. 직접 열람한 이미지와 고정 source 계약에서 모순을 찾지 못했다. 원문의 격리 PostgreSQL recovery/definitions/runtime 35 passed·21.16초는 원 작업자 수행 결과로 인용하며 James 직접 실행으로 세지 않는다.

## NOT_RUN과 잔여 범위

- James 독립 live browser 조작: **NOT_RUN**. 기존 computer-use skill 사용을 이어가며 CUA 문서를 다시 로딩하고 현재 inventory를 확인했다. 이 child는 `apps:[], browsers:[]`여서 원 작업자 live 원본 열람으로 한정했다.
- 전체 WSL·전체 Docker PostgreSQL 진행 중 결과: **NOT_RUN/미확정**. 요청 시점 진행률과 무실패 진행을 완료 PASS로 세지 않았다.
- 운영 shared coordinator 설정 적용·운영 daemon/launcher 실제 worker kill·실제 장시간 대기·운영 RSS: **NOT_RUN**. 상한과 메모리 구조를 확인했지만 운영 실측을 대체하지 않는다.
- active 1000개를 넘는 목록과 failure 20,000 events를 넘는 상세는 의도된 부분 조회다. 경고·native 링크를 보존하며 이번 수정으로 범위가 무한 확대되지 않는다.
- 이 보고서의 자기 SHA256은 저장 후 별도 반환한다. 원본을 이후 통합 판정에 맞추어 수정하지 않는다.
