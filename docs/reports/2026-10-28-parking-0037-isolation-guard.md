# 0037 downgrade의 격리 수준 명시 거절

## 현재 보완과 이전 증거

잠금 보완 d73313c02abcbb28b06cbdb9787d8091b802f124는 WSL/Docker 각12PASS·CI40610095559의
backend/frontend/admin SUCCESS·live SKIPPED를 회수했다. 이후 독립 James가 RR snapshot P1을 발견해
merge를 보류했다. 원 d733/WT/ref·두 리뷰·CI·12회귀와 이전833/전체/실패 원장은 그대로 보존한다.
새 작업의 제품 변경은0037 PostgreSQL downgrade의3줄 guard와 격리 회귀뿐이며 API/수집/모델/deps/UI는 같다.
새 정확 head의 CI·두 독립 증분 리뷰는 별도 미완 gate다. 운영/원본 삭제·자동 schedule·prune는0이다.

## 왜 table lock만으로 부족했는가

REPEATABLE READ와 SERIALIZABLE에서 첫 SELECT 이후 snapshot은 고정된다. Alembic이 version을 읽은
뒤 writer가 영구 행을 commit하고 그 다음 ACCESS EXCLUSIVE를 획득해도, 뒤의 빈 검사에 그 행이
보이지 않을 수 있다. PostgreSQL은 이 격리에서 최신 commit을 보려는 잠금을 첫 SELECT 이전에
잡아야 한다고 명시한다. [PostgreSQL18 LOCK 문서](https://www.postgresql.org/docs/18/sql-lock.html).

고정 SQLAlchemy2.0.52/asyncpg0.31.0·Alembic1.19.1과 별도 PG18.6의 실제 transaction으로 검증했다.
각 표별 RR/SERIALIZABLE version SELECT→snapshot 기록→별도 writer INSERT/COMMIT→실제 Alembic37→36을
실행하면 commit 후 세 표가 모두 사라졌다. writer commit이 없었던 예제나 단순 SQL 추론이 아니다.
원본 snapshot·기존0036 통계 sentinel은 유지돼 별도 원본 삭제와 혼동하지 않는다.

최소 보완은 실제 `Connection.get_isolation_level()`이 READ COMMITTED가 아니면 잠금/DDL 전에 거절하는 것이다.
명시 SQLAlchemy execution_options의 AUTOCOMMIT도 별도로 거절한다. get_isolation_level만으로
AUTOCOMMIT 여부가 판정되지 않는다는 공식 계약을 따른다.
[SQLAlchemy Connection 문서](https://docs.sqlalchemy.org/en/20/core/connections.html#sqlalchemy.engine.Connection.get_isolation_level).
그 뒤 기존5초 timeout·고정 순서 잠금·빈 재검사·DROP/version atomic transaction을 유지한다.
호출 중인 RR/SERIALIZABLE transaction의 격리를 낮추거나 새 connection으로 바꿔 성공을 위장하지 않는다.
SQLite 분기는 PostgreSQL 전용 격리 검사를 실행하지 않는다.

## 실제 RED→GREEN과 한계

| 소스/실행 | 실제 결과 | 판정 범위 |
| --- | --- | --- |
|첫 RED + 원d733|9FAIL/12PASS·actual1|RR3/SERIALIZABLE3의 실제 행 소실과, asyncpg 미지원 READ UNCOMMITTED fixture3실패를 분리해 보존했다.|
|지원 모드로 정정한 RED2 + 원d733|9FAIL/12PASS·actual1|RR3/SERIALIZABLE3은 실제 소실6건. AUTOCOMMIT3은 기존 LOCK의25P01 거절이며 데이터 소실로 세지 않는다.|
|새 guard WSL|21PASS·F/E/skip0·actual0|RR3/SERIALIZABLE3/AUTOCOMMIT3 모두 명시 거절·schema37/행1/원본·0036통계 보존. 기존RC/SQLite12회귀도 통과.|
|동일 새 guard Docker|21PASS·F/E/skip0·actual0·독립 wait0|동일21회귀·원 child 종료·source 전후 동일.|

RED2와 GREEN의 격리 반례 함수 AST는 같고, RED2 migration은 d733 Git blob과 LF 정규화 후 같다.
반례는 실제 version SELECT/기록한 server격리/snapshot·별도 writer commit·head/table/행수로 판단한다.
테스트 마지막의 schema 복구는 뒤 테스트 격리용이며 dump가 행 소실 순간을 그대로 보존한다는 뜻이 아니다.
첫 READ UNCOMMITTED fixture 실패는 제품 지원이라고 포장하지 않았고 그 원문/DB도 보존했다.

WSL pytest8.47초/Docker8.61초, 기존 FastAPI deprecation warning 각1건이다. 이21집중을 전체 검증으로
표시하지 않는다. d733 CI/두 리뷰와 새 source의 CI/두 리뷰를 분리한다. 독립 reviewer의 별도 ownPG RR3
RED 원장도 있지만 이 문서의21 GREEN을 그 reviewer가 직접 실행했다고 주장하지 않는다.

## 환경·정리·정책 미완

새 UUID DB4개·PG18.6/server180006·disk volume·2GiB/1CPU·internal subnet·port0이다.
동결106/Git10 WSL runtime을 전후 검산하고 기존 strict106 image71be1a0e…를 읽기 전용 source로 재사용했다.
앱 QA native client16은 유지해 backup/restore native18·운영 ARM 이미지 수용으로 확대하지 않는다.
새 전체·provider·운영SQL·수집·스케줄 실행은0이며 다른 PG/venv/이미지/프로젝트를 변경하지 않았다.

원장 `/var/tmp/parking37-downgrade-isolation-20261028-6588baf8f27f`의
`final/focused-proof.json` SHA `e0d766dccc91453a981915de667242474caf1a5b7ad8341180326f3380f103a1`에
소스별 JUnit·실제 종료·격리9건의 관측·동일 source/runtime·4dump를 연결했다.
각 dump/hash·client0·정확CID/owner·원 child 종료 확인 후 소유 PG/network만 정리하고 disk volume은 보존했다.
`final/cleanup.json` SHA `e641c98882608e06356bd556210f46dbd1a6c04d096738cbd612552627727ce1`이다.

원본48시간·통계영구는 여전히 미완이다. PR162/163 reader 실제 API/cache/bundle/outlook 연결,
운영 backfill/연속coverage·history48h/cursor410·해상도·현재/Map export·복원 보호와 검산 후 bounded prune가 남는다.
이 격리 보완은 삭제 활성화나 완전 보존의 영수증이 아니다.
