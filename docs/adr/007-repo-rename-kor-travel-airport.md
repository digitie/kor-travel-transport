# ADR-007: 저장소/패키지/n150 운영 식별자를 `kor-travel-airport`로 개명하고, 배포되는 웹앱 브랜드는 `parking-radar`로 분리 유지한다

- **상태**: accepted, 구현 완료. 브랜드 유지 범위는 [ADR-011](011-backend-internal-identity-transport.md)이 사용자 노출 표면(웹 타이틀·브라우저 저장 키·hostname)으로 좁혔다
- **날짜**: 2026-09-06
- **결정자**: agent + human
- **컨텍스트**: 이 저장소는 `kor-travel-map`, `kor-travel-geo`, `kor-travel-concierge`,
  `python-krairport-api`, `python-kasi-api` 등 `kor-travel-*`/형제 provider 라이브러리
  생태계와 함께 운영되지만, 저장소 이름만 `parking-radar`(웹앱 브랜드와 동일)라 이 생태계
  명명 규칙에서 벗어나 있었다. 사용자가 "프로젝트명을 kor-travel-airport로 바꾸고 웹페이지만
  parking-radar로 둬"라고 요청했다. 조사 결과 "parking-radar" 문자열은 이 저장소 전반에
  두 가지 서로 다른 의미로 쓰이고 있었다: (1) **저장소/패키지/n150 운영 스택 식별자**
  (GitHub 레포명, `pyproject.toml`/`package.json`의 `name`, Docker Compose project
  이름, 컨테이너 이름, 네트워크 이름, n150의 앱 디렉터리 경로), (2) **배포되는 웹앱
  자체의 브랜드/화면 표시 이름**(Next.js `metadata.title`, 백엔드 `Settings.app_name`,
  백업 dump 파일명 접두어, 쿠키/localStorage 키). PostgreSQL DB 이름/사용자
  (`parking_radar`)와 named volume(`parking-radar_parking_radar_postgres_data`)은 이
  두 범주 어디에도 속하지 않는 세 번째 종류 — **내부 저장 식별자**로, 외부에 전혀
  보이지 않으면서 바꾸려면 dump/restore가 필요해 순수 비용만 발생시킨다.
- **결정**:
  1. (1) 범주만 `kor-travel-airport`로 개명한다: GitHub 레포(`digitie/parking-radar` →
     `digitie/kor-travel-airport`), `backend/pyproject.toml`/`frontend/package.json`의
     `name`, `docker-compose.yml`/`docker-compose.db.yml`/`docker-compose.live.yml`의
     최상위 `name:`(컨테이너 이름 접두어 결정), Docker 네트워크 이름(`parking-radar-net`
     → `kor-travel-airport-net`), n150 앱 디렉터리(`/home/digitie/apps/parking-radar`
     → `/home/digitie/apps/kor-travel-airport`), 로컬 작업 디렉터리
     (`F:\dev\parking-radar` → `F:\dev\kor-travel-airport`).
  2. (2) 범주는 전혀 건드리지 않는다: `frontend/src/app/layout.tsx`의
     `metadata.title`/`description`, `backend/app/core/config.py`의
     `Settings.app_name`, `backend/app/services/backup_restore.py`의 백업 파일명
     패턴(`parking-radar-<timestamp>.dump`), `frontend/src/lib/dashboard-preferences.ts`의
     쿠키/localStorage 키. 사용자 눈에 보이는 것은 아무것도 바뀌지 않는다 — 기존 live
     사용자의 저장된 선택(쿠키)도 그대로 유효하다.
  3. (3) 범주(PostgreSQL `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` 기본값
     `parking_radar`, `DATABASE_URL` 기본값, named volume
     `parking-radar_parking_radar_postgres_data`)는 전혀 건드리지 않는다 —
     dump/restore 없이 순수 rename만으로는 바꿀 수 없고, 바꿔도 아무도 보지 못하는
     내부 식별자라 위험 대비 이득이 없다.
  4. `docs/journal.md`/`docs/tasks-done.md`/`docs/runbooks/migration.md`/ADR 본문처럼
     과거 사실을 기록하는 문서는 이번 개명에 맞춰 고치지 않는다 — 그 시점에는 실제로
     "parking-radar"라 불렸다는 사실 자체가 기록이다. 단, 파일 상대/절대 경로 링크
     (`F:/dev/parking-radar/...`)는 서술이 아니라 구조이므로 깨지지 않도록 전부
     갱신했다 — "역사를 다시 쓰지 않는다"는 원칙은 내러티브에만 적용되고, 죽은 링크를
     고치는 데는 적용되지 않는다.
  5. `.gitattributes`를 신규 추가해 `*.sh`를 항상 LF로 강제한다 — 이 작업 도중
     `scripts/deploy-server14.sh`/`scripts/n150-backup-cron.sh`가 Windows
     `core.autocrlf`에 의해 반복적으로 CRLF로 재변환되어 WSL/n150에서 shebang 파싱이
     깨지는 문제(이 세션에서만 3회 이상 재발)를 이번에 근본적으로 고쳤다. 이 개명
     작업과 직접 관련은 없지만, 같은 스크립트를 만지는 김에 함께 고쳤다.
- **근거**: 두 범주(저장소 식별자 vs. 제품 브랜드)를 분리하면 (a) 이 저장소를
  `kor-travel-*` 생태계의 다른 프로젝트와 같은 규칙으로 찾고 관리할 수 있고, (b) 실제
  서비스를 쓰는 사용자·기존 쿠키·백업 파일·URL 어느 것도 깨지지 않는다. named
  volume/DB 식별자는 `docker-compose.db.yml`의 volume `name:`이 이미 project-name과
  독립적으로 고정돼 있어(T-032에서 확립한 패턴), project 이름을 바꿔도 볼륨이 새로
  생기지 않는다는 것을 로컬에서 실제로 검증했다(기존 로컬 테스트 데이터 6,636행이
  개명 후에도 그대로 조회됨).
- **결과 (긍정)**: 저장소가 `kor-travel-*` 생태계 명명 규칙에 맞춰졌다. 배포된 웹앱의
  브랜드/쿠키/백업 파일은 전혀 영향받지 않아 사용자 관점에서는 무중단이다.
  `.gitattributes` 추가로 반복되던 CRLF 배포 실패가 근본적으로 사라졌다.
- **결과 (부정)**: 저장소 안에 "저장소 이름은 kor-travel-airport, 앱 브랜드는
  parking-radar"라는 이중 정체성이 생겨, 새로 합류하는 사람이 헷갈릴 수 있다 —
  README.md/CLAUDE.md §1에 이 분리를 명시적으로 설명해 완화했다. GitHub의 구
  이름(`digitie/parking-radar`) redirect에 의존하는 기존 북마크/스크립트가 있다면
  당장 깨지지는 않지만(GitHub가 redirect 유지) 언젠가 사라질 수 있다.
- **후속**:
  - n150 운영 cutover(디렉터리 이동 + compose stack 재기동)는 이 ADR 이후 별도 실행
    단계로 진행한다 — 진행 여부와 검증 결과는 `docs/journal.md`/`docs/resume.md`에
    남긴다.
  - 새 GitHub 레포 URL 기준 branch protection이 그대로 유지되는지(레포 ID 기반이라
    영향 없어야 함) 다음에 `docs/runbooks/branch-protection.md` 점검 시 재확인한다.
