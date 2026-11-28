# ADR-017: 웹 production runner의 non-root와 역할별 예외

- **상태**: accepted (→ 진행: `docs/tasks.md` T-BUILD-ECOSYSTEM-20261113 B4)
- **날짜**: 2026-11-13
- **결정자**: 미기록 (원문에 결정자 표기 없음)
- **컨텍스트**: 공통 CI-33은 production 멀티스테이지와 최종 non-root를 규정한다. 기존 공개 Dockerfile은 builder
  자체로 실행했고 관리자 runner에도 USER가 없었다. 공개·관리자의 Compose/start 계약과 런타임 파일 접근을
  보존하면서 이 차이를 해소해야 했다. 범위는 Transport 공개·관리자 Next 웹 runner다.
- **결정**:
  1. 두 웹 이미지는 dependencies/builder와 구분된 production runner에서 `USER node`(1000:1000)로 실행한다. 기존
     Node/npm 버전·start 명령·Compose 계약과 호스트 권한·volume·공유 DB는 바꾸지 않는다.
  2. Next standalone(server.js + 의존성 prune)은 이번 필수 조건이 아니다. 전체 `node_modules`를 보존하는 것은 런타임
     호환 결정이며 이미지 크기 절감을 주장하지 않는다.
  3. backend/code-server/migrate(같은 Python 이미지)와 비활성 LEGACY Dagster nginx gateway는 현재 root 역할을 유지하는
     **명시적 범위 예외**다. 웹 CI-33 반영으로 이들이 non-root가 되었다고 표시하지 않으며, 다른 역할이나 공용 daemon을
     바꿀 권한을 뜻하지 않는다.
  4. non-root 수용은 실제 새 이미지를 기본 USER로 실행한 증거로만 인정한다(`--user root`나 권한 우회 결과, 기존 native
     QA는 소급하지 않는다). 실제 새 이미지 수용(→ `docs/tasks.md` B4) 전에는 운영에 적용하지 않는다.
  → 세부: [경로별 권한과 수용 조건](../design/2026-11-13-normal-image-build.md#웹-production-runner-경로별-권한과-수용-조건adr-017-세부)
  (경로별 권한 표·standalone 제외 근거·역할별 현재 계약·probe 검사 항목)
- **근거**: TypeScript Next config는 설치된 loader가 tsconfig와 SWC/native binding을 읽고, 관리자 parking-ui는
  install-links로 설치된 package를 transpile하며 worker는 prebuild 산출 public 파일을 요구한다. 별도 tracing 검증
  없이 standalone/prune으로 바꾸면 런타임 회귀 위험이 크다. backend/CS는 bootstrap·collector-state/backup·root 소유
  bind config 읽기 계약이, gateway는 시작 때 설정 파일을 쓰는 계약이 있어 웹과 함께 UID를 바꾸면 검증 범위가 커진다.
- **결과 (긍정)**: 실제 새 이미지 수용(B4)을 통과하면 공개·관리자 웹이 공통 CI-33의 최종 non-root 요구를 만족한다.
  기존 start/Compose 계약이 그대로라 배포 절차가 바뀌지 않는다. 2026-11-28 현재 B4의 실제 새 이미지 수용은 미실행이다.
- **결과 (부정)**: 웹 이미지 크기는 줄지 않는다. backend/CS/gateway는 root로 남아 최소 권한 요구가 미해결이다.
- **후속**: 역할별 예외를 해소하려면 해당 역할의 최소 권한·bootstrap/state/backup/config·nginx 포트/파일 계약을
  검증한 별도 변경이 필요하다. 실제 새 amd64/arm64 이미지 QA와 적용 조건은 `docs/tasks.md` B4와 위 세부 문서를 따른다.
