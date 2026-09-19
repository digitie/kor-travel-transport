# SKILL — kor-travel-transport 에이전트 매뉴얼

## 1. 작업 원칙

- 사용자 요청과 `AGENTS.md`를 최우선으로 따른다.
- 기존 동작·API·테스트를 먼저 확인하고, 변경 범위를 작게 유지한다.
- 운영 데이터와 비밀값을 커밋하지 않는다.
- PostgreSQL 스키마 변경은 Alembic migration, 테스트, 데이터 모델 문서를 함께 바꾼다.
- UI 변경은 모바일/데스크톱 상태와 loading/empty/error/focus 상태를 테스트한다.
- 13번 호스트에서는 Docker 명령을 실행하지 않는다. n150에서만 Compose를 실행한다.

## 2. 계층과 책임

```text
frontend (Next.js) → backend API (FastAPI) → services → repositories/SQLAlchemy → PostgreSQL
                                               ├─ parking_snapshots: 원본 관측
                                               ├─ analytics cache: 파생 결과
                                               └─ backup/restore: 운영 파일과 DB 계약
```

- `backend/app/schemas.py`: API 계약
- `backend/app/services/analytics.py`: 분석 계산
- `backend/app/services/collection.py`: 외부 주차 수집
- `backend/app/services/holidays.py`: 공휴일 조회/파싱
- `backend/app/services/backup_restore.py`: 백업/복원 책임
- `frontend/src/lib/api.ts`: 모든 API 호출
- `frontend/src/lib/dashboard-preferences.ts`: 쿠키/localStorage 설정 기억

## 3. 데이터·시간 규칙

- DB event time은 `TIMESTAMPTZ`/SQLAlchemy timezone-aware datetime을 사용한다.
- API는 UTC ISO-8601로 응답하고 UI만 `Asia/Seoul`로 표시한다.
- `parking_snapshots`는 `(parking_lot_id, observed_at, source)` 중복을 막는다.
- 분석은 가능하면 원본 스냅샷을 기준으로 계산하고 캐시는 재생성 가능해야 한다.
- 5분 수집 컷오버는 base copy와 final delta를 분리하고, 마지막 관측 시각·행 수를
  새 DB에서 검증한다.

## 4. 구현·검증 금지 목록

1. main 직접 push 금지. feature branch + Draft PR + CI + 리뷰 후 머지한다.
2. 13번에 Docker stop/up/build 명령 금지.
3. 백업 파일·SQLite·`.env`·API key를 git에 추가하지 않는다.
4. 무관한 파일을 `git add -A`로 stage하지 않는다.
5. API 호출을 컴포넌트에 직접 흩뿌리지 않고 `frontend/src/lib/api.ts`를 통한다.
6. 모바일에서 `overflow-x: hidden`을 쓰지 않는다. 필요한 영역만 `overflow-x: auto`,
   루트는 `overflow-x: clip`으로 둔다.
7. Hallmark 토큰 밖의 임의 색상·폰트·spacing을 CSS에 추가하지 않는다.
8. 인증 없는 백업 UI는 내부망 전제임을 문서·운영 설정에 남긴다.
9. `python-krairport-api` 등 형제 provider 라이브러리가 이미 있는 기능을 backend 안에
   wrapper/adapter로 다시 만들지 않는다. 부족한 기능은 해당 라이브러리를 직접 고친다
   ([ADR-004](</F:/dev/kor-travel-transport/docs/adr/004-krairport-provider-library.md>)).

## 5. 검증 게이트

```bash
python -m pytest backend/tests -q
npm --prefix frontend run test -- --run
npm --prefix frontend run build
docker compose config
docker compose run --rm --no-deps backend pytest -q
docker compose run --rm --no-deps frontend npm run test -- --run
```

live 검증은 n150에서만 실행하며, 백업 생성/다운로드/복원과 320/375/414/768px UI를
확인한다. 실패·미검증 항목은 `docs/journal.md`에 기록한다.

