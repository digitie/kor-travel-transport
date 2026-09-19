# 의존 라이브러리 기준

2026-09-19 원격 `main`과 provider 변경 이력을 확인한 뒤 lock을 갱신했다.

- Frontend: Next.js 16.3.2, React/React DOM 19.2.8, TypeScript 7.0.2, Vitest 4.1.11, Playwright 1.62.1
- Backend: FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.x, asyncpg 0.31.x, Uvicorn 0.52.x
- Provider: `python-krex-api` pinned to `d153f3cdd87c9cfacceeb94310bbe6067a1bbfa8`,
  `python-opinet-api` pinned to `1aa2c577058d4a56256adaebb0682058c406747c` (latest
  `main`, browser collector hardening and 24-hour run/search limits)
- Test: pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0, AnyIO 4.14.2

정확한 resolved 버전과 해시는 `frontend/package-lock.json`, `backend/uv.lock`을 기준으로 한다. 런타임 이미지는 Node 22와 Python 3.12를 사용한다. Major 업데이트는 lock 갱신 후 WSL 테스트, Docker 테스트, live E2E를 모두 통과해야 반영한다.
