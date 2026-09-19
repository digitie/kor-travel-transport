# 의존 라이브러리 기준

2026-09-19 원격 `main`과 provider 변경 이력을 확인한 뒤 lock을 갱신했다.

- Frontend: Next.js 16.3.2, React/React DOM 19.2.8, TypeScript 7.0.2, Vitest 4.1.11, Playwright 1.62.1
- Backend: FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.x, asyncpg 0.31.x, Uvicorn 0.52.x
- Provider: `python-krex-api`는 `adda2879f8bc1f0896867d28eee5583594ecda01`,
  `python-opinet-api`는 `1601ef360300b35cba09942d8ededf806ac86f2d`로 고정한다.
  각각 전체 VDS 조회와 Chromium 자동 탐색 응답 본문 복구를 포함한 수정 PR 기준이다.
  provider PR과 통합 PR의 운영 검증·머지 게이트는 별도로 관리한다.
- Test: pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0, AnyIO 4.14.2

정확한 resolved 버전과 해시는 `frontend/package-lock.json`, `backend/uv.lock`을 기준으로 한다. 런타임 이미지는 Node 22와 Python 3.12를 사용한다. Major 업데이트는 lock 갱신 후 WSL 테스트, Docker 테스트, live E2E를 모두 통과해야 반영한다.

2026-09-19 `npm audit --omit=dev`에서 Next.js 16.3.2의 critical 1건과 sharp의 high
1건이 보고됐다. 교통정보 PR의 변경으로 도입된 항목은 아니며, 별도 의존성 보안 갱신
작업으로 추적한다. 운영은 Linux이지만 AVIF 이미지 처리 취약점의 영향까지 없다고
판정한 것은 아니다. 검토할 공지는 GHSA-p293-qw3h-jr36, GHSA-2xp9-vwfh-vxw4,
GHSA-rgj7-g3m4-5g8c다.
