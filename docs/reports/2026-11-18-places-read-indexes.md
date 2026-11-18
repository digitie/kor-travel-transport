# 장소 읽기 인덱스 후속 — 2026-11-18

## 원인과 범위

기준 소스는 3c20ab3507c18308f7f21f37cfee7e86f4f17707다. 부모가 보존한 실제
production-plan-3c20.json에서 최근 돌발 후보15,699행을 최신ID289개로 줄이는 CTE는
1,272.871ms였다. 수집시각 index scan은972.040ms·shared read blocks3,765다.
주유소는 단일 last_seen_at index로5,830행을 읽고 incremental sort 뒤625개를 반환했다
(scan434.283ms·shared read blocks2,252). 중첩 plan 시간을 합산하거나 이 block을 모두 heap으로 단정하지 않는다.

조회·DTO·cache·최근24시간/좌표/출처/검색 조건을 유지하고 다음 두 index만 추가한다.

| 표 | 이름 | 키/포함 열 |
|---|---|---|
| fuel_stations | ix_fuel_stations_seen_id | last_seen_at DESC, id DESC |
| highway_incident_snapshots | ix_highway_incidents_recent_cover | collected_at INCLUDE(id,source,identity_key,observed_at) |

기존 index는 다른 조회의 비용을 바꾸지 않도록 유지한다. ORM metadata와 Alembic 정의가 일치하며
기동 검사 ALEMBIC_HEAD도 새 revision으로 갱신한다.

## migration 계약

- 0043_reference_input_revisions → 0044_places_read_indexes. 새 head는24자로 기존
  alembic_version.version_num VARCHAR(32)에 들어간다.
- PostgreSQL의 일반 transactional CREATE/DROP INDEX다. upgrade는 주유소→돌발,
  downgrade는 역순이며 index와 version 변경을 같은 transaction으로 commit한다.
- 양쪽 방향 모두 SET LOCAL lock_timeout='2s', statement_timeout='120s'.
  120초는 각 statement 상한이며 전체 migration의 단일120초 예산이 아니다. commit/rollback 뒤 GUC가 복원된다.
- 운영 적용은 부모의 기존 SDK 소유 CS/API pause·drain 후 수행한다. 이 PR에서는 운영 DDL·apply를 실행하지 않았다.
  일반 index 생성 중 쓰기는 대기할 수 있고,2초 잠금 실패 또는 statement 실패는 전체 transaction을 되돌린다.
- concurrent/resume framework,표/열/원문 변경,backfill,통계 갱신 강제는 추가하지 않는다.
  index-only scan 이득은 visibility map 상태에 의존한다.

## 실제 로컬 PG 검증

전용 테스트 DB 안에 무작위 격리 schema를 만들고 실제 모델의 열·제약·기존 index와
주유소2,400행·돌발3,603행을 사용했다. 실제 Alembic revision planner와 version UPDATE를 실행했다.
시험 뒤 격리 schema를 제거하며 공용 metadata/schema anchor를 바꾸지 않는다.

- 새 시험11개 PASS(최초6.45초):9개 시나리오의 upgrade/downgrade 전후 **전체 item 필드·count·order** 동등,
  독립 Python oracle의 ID/count 동등,생성 index 정의·valid/ready·commit된 version·GUC 복원 확인.
- 시나리오:전체,포함 bbox 경계,미제공 좌표 포함,미제공+범위,출처,escape된 검색,빈 범위,limit1,limit5000.
  동일 timestamp ID 정렬,24시간 정확 경계/직전/미래,최신 행 좌표가 잘못됐을 때 옛 valid 행이 부활하지 않는 경우도 포함한다.
- 두 번째 index가 writer 잠금과 충돌하는 upgrade와 downgrade를 실제로 각각 실행했다.
  SQLSTATE55P03·약2.05초 뒤 첫 index 작업과 Alembic version까지 원복,writer 행 보존을 확인했다.
- 최초9회 생성시간32.98~40.50ms(중앙33.82),삭제28.72~35.27ms(중앙30.98).
  이는 작은 로컬 fixture의 migration 시간이며 운영 소요시간 예측이 아니다.
- 기존 전체 스키마의 실제 alembic upgrade head,alembic check도 PASS:
  No new upgrade operations detected.

기존 장소·좌표·돌발·fuel JSON·source walk·읽기 관측과 새11개를 함께 실행한
WSL+Docker PG 집중시험은84 PASS(51.84초)다. 광범위 전체 suite·앱 Docker 재빌드 시험은 반복하지 않고
정확 GitHub CI에 맡긴다. 새 파일 전체 Ruff 및 변경 Python의 E/F 검사는 PASS다. 기존 모델·session의 상위 Ruff 설정에서
지적된 import/forward annotation4건은 기준3c20에도 존재하며 이번 변경에 포함하지 않는다.
최종 새11개 재확인은6.35초에 PASS했다. 추가로 기존 lifespan8개가4.99초에 PASS했다
(SQLite 기동·정렬 index·실제 schema guard/head 계보·OpenAPI 일치 포함).
따라서 서로 다른 관련 시험은총92개이며 새11개 반복 실행을 합산하지 않는다.

별도 사전 TEMP-table 실험(동일 SQL·두 종류,relation합계6,692,864B)에서 강제 planner 옵션 없이
돌발 seq scan361local blocks→covering index-only19blocks/heap fetch0,
주유소 item branch2,304행/240blocks→625행/70blocks가 관측됐다.
3회 중앙12.64→11.69ms,단일 EXPLAIN execution8.400→6.937ms이며9개 결과 SHA가 동일했다.

## 수용 한계와 다음 단계

작은 로컬 실험은 운영 HTTP1초 달성이나 CPU 약1초 제거를 입증하지 않는다.
실제 CPU/DTO 비용과 source union194.894ms는 남으며 새 revision cache를 도입하지 않는다.
부모가 동결 commit의 두 독립 검토·정확 CI 뒤 병합/SDK 적용을 정산한다.
적용 후 같은 요청과 데이터에서 계획·지연을 검증하기 전까지 운영 성능 수용은 미완이다.
이번 작업에서 운영 요청·프로파일링·빌드·배포·Map/N150·CI 순서·frontend 변경은 없다.
