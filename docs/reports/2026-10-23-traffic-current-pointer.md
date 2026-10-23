# Map T2 교통 current 선행 구현

상태: 구현·검증 중. T2 REST·frozen HTTP snapshot·주차·T3는 아직 없다. `TRANSPORT_MAP_CURRENT_ENABLED=false`가 기본이며 현재 운영 환경을 활성화하지 않는다.

- `highway_traffic_current_states`는 source와 route/conzone 설정 fingerprint별 마지막 완결 집합의 generation/실제 확인 시각/개수를 보존한다. source 저장 성공 transaction에 속하며 별도 commit이 없다.
- `highway_traffic_current`는 identity별 latest snapshot PK와 작은 typed DTO 열을 보존한다. mutable history가 같은 PK에서 나중에 수정되어도 승인된 current를 우회 변경하지 않는다. raw JSON은 복사하지 않는다.
- 400개씩 이번 입력의 `(identity, observed_at)`만 unique lookup하고 같은 batch로 upsert한다. 같은 identity의 여러 시각은 pointer 입력에서 최신 하나로 합친다. 원본 history 저장·정정·새 INSERT 반환 수는 그대로다.
- 데이터 winner는 `(observed_at,collected_at,snapshot_id)`이며 오래된 관측은 최신 point를 되돌리지 않는다. 정상 재수집 INSERT0도 확인 generation을 갱신한다.
- 완결 집합의 순서는 DB CollectionRun ID로 고정한다. 늦게 완료한 옛 run은 새 membership/head를 덮지 못하며 wall clock 역행으로 이후 정상 run이 막히지 않는다. 이는 provider issued-time winner와 별도다.
- 정상 완결 응답에서 빠진 identity는 삭제하지 않고 새 generation membership에서 제외한다. 확인 안 된 빈/급감은 기존 T5 guard가 저장 전에 차단한다. 정상0의 허용 여부도 T5의 명시 완결 재확인 규약을 따른다.
- source raw/성공 상태/history/current/통계는 같은 source transaction으로 commit된다. 뒤의 통계·commit·worker fence 실패면 모두 rollback된다. 다른 source의 실패가 이미 성공한 traffic을 되돌리지 않는다.
- migration0030은 작은 신규 표·index만 만든다. 기존 전국 history의 backfill/rank/전수집계는 하지 않는다. 운영 schema29에서 별도 승인 배포가 필요하며 이번 T1/T4/T5(schema변경0) 배포에 섞지 않는다.

## 검증과 남은 gate

초기 SQLite/PG 집중7 PASS: default OFF·replay/정정/관측역전·같은identity 여러시각·명시empty membership·late old run의 history변경 격리·원자적 rollback·필터분리·805개3lookup/3upsert. migration upgrade/check PASS. 추가 owned worker fence/실제 빈 source guard·Docker·전체 회귀·정확CI·독립2리뷰·비용 실측은 진행 중이다.

805개 batch 문장 수는 구조 검증이며 CPU/RAM 절감 실측이 아니다. 기존 행별 history 저장 비용은 별도 후속이다. 새 current의 추가 WAL/쓰기·동시성/retention 비용을 같은 입력으로 측정한 뒤에만 운영 opt-in을 켠다. 이 표의 존재만으로 페이지 snapshot이나 T2 API 완료를 선언하지 않는다.
