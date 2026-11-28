# ADR-018: 데이터는 공용 PostgreSQL에 두고 수집은 Manager 공용 Dagster plane의 code location으로 실행한다

- **상태**: accepted
- **날짜**: 2026-11-28 (사후 기록. 원 결정: 공용 DB·Dagster 분리 2026-09-21~22 PR [#32](https://github.com/digitie/kor-travel-transport/pull/32),
  공용 Dagster 제어 평면 합류 2026-10-02~03 PR [#64](https://github.com/digitie/kor-travel-transport/pull/64)·Manager ADR-54)
- **결정자**: agent + human (사후 기록)
- **보완**: [ADR-001](001-postgresql-as-primary-db.md)을 좁힌다 — PostgreSQL 채택은 그대로이고, 운영 DB의 위치(앱 compose의
  전용 컨테이너 → Manager 공용 instance)와 버전 관리 주체(Manager), 버전(ADR-001의 "PostgreSQL 16" 고정 → Manager가 정하고 현재 값은 [세부 문서](../architecture/shared-db-dagster.md))이 바뀐다.
- **컨텍스트**: 초기 운영은 앱 compose 안의 전용 PostgreSQL(ADR-001)과 FastAPI 프로세스 안의 in-process scheduler였다.
  2026-09 수집 대상이 고속도로·유가·철도·여객선 등으로 늘었다. 문서에 남은 목적은 "고속도로·유가처럼 짧은 주기의 데이터와
  열차·여객선처럼 변동이 적은 기준정보를 같은 운영 기준으로 다루기 위한 것"이다([공용 DB와 Dagster 운영 경계](../architecture/shared-db-dagster.md) §목적).
  같은 호스트의 형제 프로젝트(Weather 등)는 `kor-travel-docker-manager`(Manager)가 관리하는 공용 PostgreSQL·RustFS를 이미
  쓰고 있었고, Weather·PinVi·Geo·Map은 2026-09-30~10-01에 Manager의 공용 Dagster 제어 평면에 합류했다.
- **결정**:
  1. 애플리케이션 데이터는 Manager가 운영하는 공용 PostgreSQL instance의 전용 DB `kor_travel_transport`와 전용 비특권
     role에 둔다. 이 저장소의 compose는 superuser 권한을 받거나 DB/role을 만들지 않는다 — DB·role·RustFS bucket 준비는
     Manager bootstrap이 한다. 스키마는 이 저장소의 Alembic이 소유한다.
  2. 운영 수집은 FastAPI web process가 아니라 Dagster가 맡는다(`SCHEDULER_MODE=dagster`). 이 저장소에는 code-server
     하나(location `kor-travel-transport`)만 남고, schedule·queue·run monitoring·UI·run metadata instance는 Manager의
     공용 제어 평면이 맡는다. 동시 실행·실행 상한 같은 값은 Manager 공용 설정과 job tag가 갖는다.
  3. code-server의 dagster 버전은 공용 plane과 같게 고정하고 배포 때 대조한다.
  4. 공용 plane 합류의 되돌리기는 지원하지 않는다(소유자 결정, 2026-10-02). 옛 전용 Dagster 서비스(`legacy-dagster`
     profile)는 compose에 남아 있지만 평소 띄우지 않으며, 그것으로 되돌리는 것은 보장 없는 수동 best-effort다. 옛 metadata
     DB는 odroid에 만들지 않는다(ADR-014).
  → 세부: [공용 DB와 Dagster 운영 경계](../architecture/shared-db-dagster.md)(서비스 표·DB/DSN·엔진 버전·job 일정·공용 plane
  계약과 상한 값·전환 절차), [Dagster 중단 복구](../runbooks/dagster-recovery.md)(실행 상한·회수 sensor·pool 값)
- **근거**: 이 저장소에 남은 이유는 위 목적과 "Manager의 Weather 정본과 같은 역할 분리·host-network 구조를 따른다"는 것,
  그리고 Manager 쪽 결정(ADR-54)이다(`docs/journal.md` 2026-09-21·2026-10-02). 자체 DB·scheduler를 계속 두는 대안과 비교한
  비용·자원 근거는 이 저장소에 기록돼 있지 않다. 장기 배치를 web process에서 떼어 낸 것은
  [ADR-009](009-durable-transport-collection-reservations.md)의 예약·트랜잭션 분리와 맞물린다.
- **결과 (긍정)**: DB 백업·버전·자원 관리를 Manager가 한 곳에서 한다. 장기 배치(유가 브라우저 수집, odroid 실측 약 1.7시간)와
  5분 수집이 web process 재시작·배포와 분리되고, run 이력·schedule 상태·실패가 공용 UI와 관리자 콘솔에 남는다. 다른
  프로젝트와 같은 healthcheck·복구 계약을 공유한다.
- **결과 (부정)**: Transport 배포가 Manager release·공용 plane 버전에 묶인다(버전 불일치 시 배포 거부). 공용 instance의
  부하와 공용 Dagster 설정 변경이 테넌트끼리 서로 영향을 준다. DB 엔진 버전을 Manager가 정하므로 운영과 CI의 PostgreSQL
  major가 다를 수 있다(현재 값은 세부 문서). 공용 plane 합류는 자동 되돌리기가 없다. 옛 metadata DSN은 compose 필수 보간
  때문에 값만 남아 있다.
- **후속**: 운영 전용 동작(EXPLAIN·설정)은 운영 instance에서 확인한다. Manager가 공용 probe·Dagster 설정·dagster 버전을
  바꾸면 이 저장소의 계약 시험(`test_shared_dagster_plane_contract.py`, `test_dagster_healthcheck_contract.py`)과 compose를
  맞춘다. 운영 호스트는 [ADR-014](014-odroid-host-and-deploy-host-flag.md)를 따른다.
