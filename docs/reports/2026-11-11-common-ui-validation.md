# Transport 공통 UI 통합 검증 — 2026-11-11

## 범위와 기준

기존 clone과 `agent/codex-common-unification-20261111` 브랜치를 유지했다.
기준 HEAD는 `59e1d8213c09a82a4ed9cc4396a6414ef0332b9c`이다.
공개 `frontend`, 공유 `frontend/src` parking-ui, 관리자 frontend만 UI 의존성과 소비 코드를 갱신한다.
백엔드·DB 스키마·운영 설정·RustFS 수명주기는 변경하지 않는다.
기존 미커밋 이관 초안을 보존하고 구현·검증을 이어받았다.

## 구현과 정책

표는 공통 VirtualTable, 프리미티브는 공통 shadcn Radix export를 사용한다.
기존 LoginForm/AppMenu/DagsterOperations/map-controls의 역할과 도메인 API를 유지한다.
다중 지도 필터는 공통 Radix Popover를 조합하되 입력·선택 칩·10개 상한·키보드·Escape 계약을 보존한다.
RHF/Zod는 역 매핑 근거와 요금 시간 입력, Zustand는 인스턴스별 메뉴·요금 결과에 실제 사용한다.
Pretendard는 로컬 폰트 CSS를 로드하고 본문에 적용한다.

부모 version-targets.json exact를 적용했다. nested PostCSS8.5.32·undici8.12.4와 공개 Testing Library DOM10.4.2도 override로 일치시켰다. TypeScript 5.9.3은 부모가 확인한 peer 호환성,
@types/node 22.20.5는 실행환경22 기준이다. Tailwind/plugin은4.3.5다.
ESLint10.14.0은 Next plugin·typescript-eslint·react-hooks·jsx-a11y-x의 지원 조합으로 실행하며
eslint-config-next의 구 React/import/a11y plugin 묶음을 제거했다.
React Doctor0.9.22 `--help`에서 실제 옵션을 확인했다. `doctor`는 전체 프로젝트를
`--yes --no-telemetry --no-supply-chain --no-parallel --scope full --blocking warning`로 검사한다.
공급망 진단 제외는 외부 Socket 전송을 막기 위한 것이며 React 진단/유지보수 검사는 계속 실행한다.
CI는 설치 직후 산출물/소스 guard, Doctor, 타입, lint, 단위, 빌드를 실행한다.

## 현재 검증 경계

검증 대상은 후보4 UI와 같은 부모 원장이다. 최종 산출물은 아직 부모가 freeze하지 않았다.
첫 후보 기준 WSL 공개164개/관리자350개 단위, 두 타입·lint·빌드·의존성 guard는 통과했다.
같은 파일명 tgz 교체와 로컬 parking-ui 변경은 npm의 옛 lock 메타데이터를 재사용할 수 있었다.
해당 항목을 실제 재설치하고 `npm ls --all`로 nested lucide/Base UI 잔재를 발견·정리했다.
첫 후보의 로컬 Docker 공개/관리자 빌드도 성공했으나 이후 후보 변경의 증명으로 확대하지 않는다.

브라우저에서 common MapTabPanel forceMount 비활성 표시와 Nova Tabs 방향 속성 회귀를 재현해 부모에게 알렸다.
각 앱 CSS로 공통 회귀를 우회하지 않았다. 초기 Playwright 두 실행의 같은 출력 경로 충돌은
검증 환경 실패이며 제품 실패와 구분한다. 재검증은 고유 output 디렉터리와 순차 실행을 사용한다.

후보4 실제 Chromium은10개 통과/공통 회귀2개 실패다. 공통 로그인/폰트/필터6개와 역 매핑4개는 통과했다. 320/375/768/1440px 로그인 재시도·비밀번호 비움·서버 원문 비노출,
375/1440px 입력·칩 제거·Escape·10개 상한을 검증했다. 운영 접속은 사용하지 않았다.
실패한 두 항목은 `e2e/common-adoption.spec.ts`의 지도 활성 작업면1개와 수평 탭 본문 배치다.
기존 역 매핑 E2E의 새로고침 중 편집 허용 기대는 현재 source의 documentReady 잠금과 충돌했다.
이 테스트를 조회 중 비활성·완료 뒤 저장 계약으로 갱신했다.
Doctor는 warning 차단으로 강화했고 현재 미통과다. 정확한 잔여 진단은
[Doctor 진단 원장](2026-11-11-react-doctor-findings.md)에 기록했다.

독립 리뷰2건·원격 CI·PR·머지·운영 배포는 부모 통합 뒤 별도 게이트다. 현재 NOT_RUN이다.

## 후보4 최종 소비자 검증

| 게이트 | 결과 |
| --- | --- |
| 소스·tgz·lock 원장 guard | 두 frontend 통과 |
| 타입·ESLint10 | 두 frontend 통과 |
| WSL unit | 공개164/관리자350 통과 |
| WSL Next production build | 두 frontend 통과 |
| Docker build | 공개 image와 관리자 builder 통과 |
| 격리 Docker Compose unit | 공개164/관리자350 통과. network none, DB/volume 생성 없음 |
| 실제 Chromium | 10통과/2실패. 공통 Tabs 두 회귀 재현 |
| Doctor0.9.22 full warning gate | 공개 오류0/경고6, 관리자 오류0/경고48. 실패 |
| 전체 backend WSL | 실행 중, 결과 미확정. 통과로 보고하지 않음 |
| backend Docker/독립2리뷰/원격CI/PR/배포 | NOT_RUN |

이미지는 검증 전용 tag/image ID이며 운영 배포 이미지를 뜻하지 않는다.
[구조화된 검증 원장](2026-11-11-common-ui-validation.json)에 artifact integrity와 image ID를 고정했다.
전체 backend 실행 로그는 `/tmp/transport-backend-tests.log`, 실행 PID는25324다. backend source/lock은 변경하지 않았다.
추가 후보 적용 후에는 해당 gate를 다시 실행해야 한다.

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
   공개 frontend는 공식 Compose의 project/service 이미지, admin은 `kor-travel-transport-transport-admin-web`
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
