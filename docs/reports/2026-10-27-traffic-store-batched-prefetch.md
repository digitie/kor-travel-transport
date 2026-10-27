# 고속도로 소통 관측의 배치 조회·저장

상태: 최신 main `1f6a970796ad9c5bb54b9b574e2dcfc8735516d1`을 기준으로 작은 성능 후보를 구현했다.
운영 컨테이너·설정·스키마·제공자 호출·API 계약은 바꾸지 않았다. PostgreSQL·CPU/RSS·CI·두 적대 리뷰·live UI 수용 전이다.

## 변경과 보존 경계

`_store_traffic`가 관측마다 기존 행을 조회하던 부분만 최대400개 exact `(identity_key, observed_at)`
pair 조회로 바꿨다. 원 source 조건과 기존 unique key를 유지한다. 묶음마다 ORM 변경을 flush하고
기존 행 참조를 비워 일시 보유량을 제한한다. 전체 입력의 첫 중복 우선, 같은 수집 시각,
기존 PK 정정, 새 행만 세는 반환값, 원 raw/provider 필드는 유지한다.

SQLite의 저장 UTC 시각이 naive로 반환되는 경우는 UTC 기본값으로 정규화한다.
제공자 입력을 KST로 해석하는 경계와 혼용하지 않는다. KST `+09:00`와 같은 instant의 UTC 입력,
배치 경계 양쪽 중복, 파싱 실패의 단일 수집 시각 fallback과 뒤 배치 오류의 전체 rollback을 검증한다.

commit·원 실행 소유권/CAS·고속도로 advisory lock은 기존 호출자가 그대로 담당한다.
current OFF를 활성화하지 않으며 ON일 때는 같은 전체 pair 집합을 기존 current 갱신 함수에 전달한다.
최근2시간 통계 재집계·다른 수집·전역 잠금 구조는 이번 변경에 섞지 않는다.

## SQLite에서 관측한 조회 수와 값 동등성

803개 입력/801개 고유 관측을 같은 고정 시각으로 신규 저장·정정·재확인했다.
각 단계의 전체 행 JSON digest는 원본과 후보가 모두 같았다.

| 단계 | 원본 SELECT | 후보 SELECT | 원본 INSERT/UPDATE 관측 | 후보 INSERT/UPDATE 관측 |
| --- | ---: | ---: | ---: | ---: |
| 신규 | 801 | 3 | INSERT801 | INSERT801 |
| 정정 | 801 | 3 | UPDATE801 | UPDATE3 |
| 재확인 | 801 | 3 | UPDATE801 | UPDATE3 |

수치는 SQLAlchemy `before_cursor_execute` 이벤트 횟수다. `executemany`/`insertmanyvalues`의
행 수와 PostgreSQL 서버의 실제 DML 실행 수·왕복 수는 같지 않다. SQLite 신규 INSERT 감소나
운영 CPU/RSS 절감을 이 자료로 주장하지 않는다. 일시 ORM 객체는 묶음 상한을 가지지만
전체 payload와 중복 판정 set은 기존처럼 수집 입력 크기에 비례한다.

원자료: `transport-traffic-batch-sqlite-baseline-r2.json`
SHA256 `fc7dccbd36dca95ebe766db66e7d5372050bfea3d00442abe7d952bb0811981b`,
후보 `transport-traffic-batch-sqlite-candidate-r2.json`
SHA256 `6ec7e406ede0faa0619b7285cadd558ab8511e91e163820b4498ea476e742021`.
첫 probe는 필수 provider enum 누락으로 준비 단계에서 실패했고, 첫 pytest 호출은 작업 경로 오기로
수집0이었다. 두 실패를 성공으로 세지 않고 fixture·호출 경로만 바로잡았다.

## 남은 수용

Python3.13.14·frozen lock의 새 회귀와 기존 traffic/current/collection 집중85개는
84통과/SQLite에서 실제 PostgreSQL advisory lock1건너뜀(324.52초)이다. 같은 잠금·스키마의 격리
PostgreSQL에서 값/정정/실패 rollback과 쿼리 경계를 다시 확인한다. 정확 lock의 Docker 회귀,
CI·두 독립 적대 리뷰와 live UI·실제 ARM 수집 전후 측정은 별도이며, 완료 전 운영에 배포하지 않는다.
