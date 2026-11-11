# Transport 공통 UI·Doctor 검증 — 2026-11-11

기존 clone과 `agent/codex-common-unification-20261111`, 후보5672cc2 및 이전 dirty를 보존했다.
Transport 공개/공유 parking-ui/관리자만 수정한다. API·인증·수집 정책·DB 스키마·RustFS 수명주기는 변경하지 않았다.
최종 RELEASE와 운영 배포는 미완이며 이번 결과는 integration-6-review 소비자 소스의 검증이다.

## 구현 결과

공통 Radix/shadcn·VirtualTable, Tailwind4.3.5 및 exact 의존성, 실제 RHF/Zod/Zustand/Pretendard와
기존 LoginForm/AppMenu/Dagster/map-controls를 유지한다. 공통 web1.0.3/core1.0.1 산출물을 사용하며
이전 core1.0.0 vendor는 제거했다. 공개/관리자의 UI·tokens tgz와 원장은 동일 bytes다.

Doctor의 공개6/관리자48 경고를 도메인 상태 소유권·조회 수명·표현 분리로 개선했다.
현재 양쪽 전체 warning gate는0이며 상세 조치와 좁은 오탐7개는
[Doctor 검증 기록](2026-11-11-react-doctor-findings.md)에 있다.
분리 중 발견한 느린 Dagster의 다른 성공 응답 표시 지연과 빈 상세 오버레이의 모바일 검색 차단도
재현 테스트와 브라우저 검증으로 고쳤다. 공통 source/CSS monkeypatch는 없다.

## 실제 검증 현황

| 게이트 | 현재 관측 결과 |
| --- | --- |
| c6 source/tgz/lock guard | 두 frontend 통과 |
| 최신 canonical guard | c7 UI/tokens 해시와 c6 설치본 불일치로 차단. root pack은 아직c6 |
| 타입·ESLint10 경고0 | 두 frontend 통과 |
| Doctor0.9.22 full warning | 공개56/관리자198파일, 오류0/경고0, complete=true, 생략0 |
| WSL unit | 공개164/관리자356 통과 |
| 격리 Docker unit | 공개164/관리자356 통과. 새 상세 회귀 뒤 관리자 재통과 |
| Next production build | 두 WSL 빌드와 현재 소스의 두 Docker 이미지 생성 확인. 후속 관리자 수정도 Docker 재컴파일 통과 |
| 관리자 실제 Chromium | 최신 c6 수정 이미지16/16 통과: 로그인/폰트/필터8·역 매핑4·버스/공항4 |
| 공개 단독 Chromium | 375/1440px 현재 표·요금·과거 차트/달력/초점4/4 통과 |
| backend 전체 WSL/Docker | 별도 실행 중. 최종 summary 미회수, PASS 아님 |
| 독립 Transport 리뷰2건·원격CI·PRmerge·운영 배포 | 미실행, 부모 통합 게이트 |

검증 로그는 저장소 `validation/transport-*`다. 공개/관리자 실제 image ID·현재 소스 해시는
`transport-docker-source-receipt.json`, 브라우저는 `transport-browser-overlay-fix.log`,
백엔드는 `transport-backend-wsl-retry.log`와 교정 뒤 `transport-backend-docker-corrected-full.log`를 확인한다.
원 실패 기록은 `transport-backend-docker.log`, 집중 원문은 `transport-backend-docker-focused.log`에 보존한다.
원격 reusable 정책은 부모가 작성한 `.github/workflows/common-frontend-policy.yml`을 보존하고
worker 커밋에서는 제외한다. foundation5e064808fabd3a54968dd20910eaccd04eba9f38 병합 전에는
원격 CI 통과로 보고하지 않는다. 로컬 canonical 검사와 원격 main 정책 검사는 구분한다.

## 실패·자원 경계

5672cc2 당시 c4 결과(Doctor6/48, 브라우저10/2)는 과거 이력이며 현재 통과 수에 더하지 않는다.
이전 중단 backend 실행과 이번 디스크 고갈 시점에 종료된 backend 검증도 PASS가 아니다.
원 로그를 보존하고 현재 WSL 임시 DB/캐시를 본인 전용 tmpfs로 분리해 전체를 다시 실행한다.
첫 Docker backend는 tmpfs2GB/noexec 때문에 백업 여유 검사와 실행 대역을 차단했고 Git 소유권/alternate 경로도 빠져 있었다.
교정한6GB/exec·읽기 전용 Git 객체·컨테이너 한정 safe.directory 환경에서 집중110개를 통과했고 전체를 재실행 중이다.
운영/백엔드 코드는 바꾸지 않았다. Docker backend는 source를 read-only로 마운트하고 network none·임시 SQLite만 사용한다.
운영 DB·컨테이너·RustFS·다른 테넌트를 생성/중지/삭제하지 않았다.

루트 고갈 때 본인 종료 검증의 임시 DB만 F:에 압축 보존하고 제거했다. 본인 node_modules·.next는
전용 tmpfs로 옮겼으며 generated symlink도 git에서 제외한다. 다른 에이전트 경로나 기존 사용자 cache는
정리하지 않았다. F: 의존성 복사는 부모 공간 확보 후 불필요해져 원본을 보존한 채 중단했다.
Docker build의 한 호출은 이미지 생성 후 stdout 기록이 ENOSPC로 실패했다. 이미지 존재만으로 끝내지 않고
현재 파일46개 해시와 실행 테스트를 대조했으며, 뒤의 관리자 상세 수정 이미지는 정상 exit0으로 재생성했다.

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

## 로컬 빌드 공간 분리

루트 밖 node_modules symlink는 Turbopack의 해석 경계를 넘어 직접 빌드가 거부됐다.
앱 설정을 넓혀 우회하지 않고 같은 소스300파일을 전용 tmpfs의 동일 상대 경로 구조로 복사하고 기존 의존성을
같은 파일시스템 안에서 재사용한다. env 파일은 제외한다. 공개·관리자 capsule 빌드를 모두 통과했다.
source 해시/경로는 `validation/transport-wsl-capsule-receipt.json`에 둔다. 이 검증 capsule은 새 clone/branch나 운영 배포가 아니다.
