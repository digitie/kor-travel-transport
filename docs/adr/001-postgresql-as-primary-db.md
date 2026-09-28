# ADR-001: PostgreSQL을 운영 기준 DB로 채택

- **상태**: accepted
- **날짜**: 2026-08-22
- **결정자**: agent + human (T-002)
- **컨텍스트**: 초기 운영 앱은 SQLite 기반이었다. ODROID 단일 프로세스 운영에서는 충분했지만,
  192.168.1.14로의 운영 이전과 함께 Docker Compose 기반 다중 컨테이너 구조, 동시 쓰기(수집
  스케줄러 + 수동 수집 + backup/restore), Alembic 기반 스키마 마이그레이션 이력 관리가
  필요해졌다.
- **결정**: 운영 기준 DB를 PostgreSQL 16으로 하고, SQLAlchemy 2 async + Alembic으로 스키마를
  관리한다. SQLite는 legacy import 원본 조회와 빠른 로컬 단위 테스트 호환성 용도로만 유지한다.
- **근거**: PostgreSQL은 Docker Compose 환경에서 동시 접속·트랜잭션 격리를 SQLite보다 안전하게
  처리하고, Alembic lineage(`0001_initial` → `0002_integrity_and_freshness` →
  `0003_legacy_source_identity`)로 스키마 변경 이력을 코드로 추적할 수 있다. CI에서도 동일한
  PostgreSQL 16 컨테이너로 `alembic upgrade head`와 `alembic check`를 검증해 로컬/CI/운영
  스키마 drift를 막는다.
- **결과 (긍정)**: 운영 배포마다 clean PostgreSQL `alembic upgrade head`로 스키마 상태를
  재현·검증할 수 있다. CI가 실제 PostgreSQL 컨테이너를 띄워 검증하므로 SQLite 전용 동작에
  의존하는 회귀를 잡아낸다.
- **결과 (부정)**: 로컬 1차 테스트(WSL2, Docker 없이)는 SQLite로 돌리므로, PostgreSQL 전용 제약
  조건(스키마 한정, 타입 캐스팅 등)의 회귀는 2차 Docker 테스트나 CI에서만 드러날 수 있다.
- **후속**: 새 스키마 변경은 항상 Alembic revision + 테스트 + `docs/architecture/data-model.md`
  갱신을 함께 진행한다([runbooks/migration.md](../runbooks/migration.md) 참고).
