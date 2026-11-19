# USED 백엔드 라이브러리 정렬 — 2026-11-20

## 변경과 근거

기준은 Opinet PR224의 검증된 c1b5 tree이며, canonical merge2a315와 같은 tree다.
실제 쓰는 앱 축을 SQLAlchemy2.1.9, asyncpg0.32.0, FastAPI0.165.0, Pydantic2.14.4/core2.50.5,
settings2.16.3, Alembic1.20.1, HTTPX0.28.1, Uvicorn0.54.0으로 exact 선언·lock 정렬한다.
Common Python은 정본 e2899128f78c9622ec3ef79674cff8d1c3aec6f9를 사용한다.
공유 Dagster1.13.24/postgres0.29.24와 호스트 제어 평면은 바꾸지 않는다. 쓰지 않는 psycopg3는 추가하지 않는다.

127개 lock graph에서 변경은8개 패키지 버전과 Common Git ref, root requirement metadata다.
기타 provider pin(새 Opinet11f1 포함), GDAL/Dockerfile, UI/토큰 팩은 유지한다.
의존성 갱신 자체를 cold latency 해결이나 성능 향상으로 주장하지 않는다.

## 의미 있는 검증

- 격리 환경에 실제 새 lock의122분포를 설치하고 모든 설치 버전과 Git direct_url commit을 lock에 대조했다.
- 실제PG Alembic upgrade/check 및 기존 OpenAPI byte check PASS다.
- 새 회귀는4,099개 live 관측과 migration 중복을2,048행 fetch 창 너머로 읽는다.
  최대 ID 조회 뒤 들어온 행을 배제하고 live 우선·순서·전체 JSON bytes·세션 해제를 검산했다(실제PG PASS).
- 기존 native COPY의400행 경계·UTF8/JSON·같은 TX·중간 실패/취소/중복/수량 오류 rollback·15초 예산,
  source mutation/cursor/ETag 및 history stream 계약의 고유105개를 정산했다. 최초600초 실행은98개 unchanged PASS/새 시험1FAIL/마지막6개 미완이며 timeout124를 보존했다. 새 시험만 수정 후1PASS, 미완6개만89.87초6PASS다. 통과한 기존 시험을 반복하지 않았다.
- 초기 새 회귀의 실패를 보존했고 QueuePool 전용 introspection이 시험 엔진의 NullPool과 맞지 않는 가정을 고쳤다.
  실제 wrapped AsyncSession의 transaction 해제를 검사하도록 시험만 고쳤고 해당 새 회귀1개는 PASS다.
- 최초 NTFS uv cache rename PermissionError는 원문을 보존하고 자기 ext4 cache 설치만 재시도했다.
  공용 venv·cache 정리·운영 호출은 하지 않았다. 최초 timeout 뒤 자기 DB 삭제의 ObjectInUseError도 보존했다. 시험 자식 종료·자기 UUID와 client0을 확인한 별도 cleanup에서 해당 DB만 삭제했고 새 회귀/미완 시험의 자기 DB도 정상 삭제했다.

- Common의 선택 application checker는 source/lock exact9축과 Common package tree를 검사했고11항목/failing0 PASS다. 미사용 psycopg3는 NOT_USED이며 설치/runtime 증거와 분리한다. CI는 producer b566840cb111fa8b1184498aa892b0fd5ce7e5c6를 fetch-depth0으로 고정해 같은 선택 guard를 실행한다. 이 ref는 현재 unmerged 후보이며 consumer merge는 실제 producer merge·ancestry 확인 뒤에만 진행한다.

- SQLAlchemy2.1의 기본 PostgreSQL driver 변경 경계를 별도 순수1개로 확인했다. 기존 Dagster URL의 명시적 psycopg2 driver 계약은 PASS이며 host profile이나 미사용 psycopg3를 바꾸지 않는다.

## 수용 경계

현재 운영 수용은 PR223/fa204의 SDK621·원20복원·5폭/auth/map·6PNG PASS다.
첫 rail20010,828.562ms는1초 미달이고 이어진304185.851ms는 단일 표본이다. p95 성공으로 쓰지 않는다.
새 라이브러리는 아직 이미지/native/SDK에 반영하지 않았다. 새 source exact CI와 두 좁은 독립 검토 뒤
canonical merged source로 같은 builder/cache를 사용하고 GDAL은 기존 정상 cache를 검산한다.
CI 순서 최적화는 이 변경 범위가 아니다.

별도 로컬 release-key 조사는 source/data가 같은 A/A/B/B에서 artifact1/1/2/2와 fingerprint2/0/2/0을 확인했다.
canonical payload digest는 같지만 새 snapshot ID 때문에 HTTP 표현과 ETag는 달랐다.
이 후보에는 key 제거·TTL 변경·호환 alias·prewarm 또는 새 artifact framework를 포함하지 않는다.
