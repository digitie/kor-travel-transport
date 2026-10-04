# Transport Dagster 중단 복구

Weather PR #72의 개선과 common PR #24 (`090f984`) Python 코어를 채택한다.
공용 가이드: https://github.com/digitie/kor-travel-common/blob/main/docs/runbooks/dagster-adoption.md

## 구조와 호출 보호

각 job은 4시간 실행 상한, step 동시성 1을 유지한다. common의 project/job 태그와
coalescing schedule은 같은 location의 pending/active 실행이 있으면 새 예약을 합친다.
collector pool은 2 connections와 overflow 0으로 제한한다. 한 connection은 기존 session
advisory lease, 다른 하나는 부분 게시 transaction에 필요하다. DB 접속 10초, statement 60초,
lock 5초와 async action 14340초 제한을 적용한다. provider public cancellation 계약을 사용한다.

`0024` migration 뒤 worker는 `CollectionRun`을 외부 호출 전에 commit하여 소유권을 남긴다.
소유 session은 ORM flush와 bulk SQL commit에서 기존 running/owner를 잠그고 heartbeat를
갱신한다. 회수된 worker의 늦은 게시·완료 덮어쓰기는 rollback된다. 부분 저장본은 유지한다.
회수 sensor는 외부 provider 없이 stable ID keyset 100행씩 확인한다. Dagster terminal은
running 수집 기록을 failed로 회수하고, 없는 run은 5시간 grace·heartbeat CAS로 확인한다.
metadata 장애는 회수 사유가 아니다. legacy NULL owner 행은 자동 변경하지 않는다.

공항 일부 실패도 성공분을 commit한 뒤 Dagster FAILURE로 표시한다. 자동 인프라 재시도
1회는 공항·고속도로·휴게소 기준정보만 허용한다. provider 실패·KRIC 마지막 시도 48시간·
버스 성공 72시간·철도 성공 48시간·과금/유가 receipt 보호는 그대로 유지한다.
수동 재실행도 이 보호를 우회하지 않는다. 보호가 끝나면 정기 tick이나 Dagster Re-execute로
누락 범위를 보충한다. 기존 정상 데이터 삭제·전국 재수집은 복구 절차가 아니다.

## 실제 instance와 배포 순서

공용 운영은 Manager instance YAML을 사용한다. 소비자의 `backend/dagster_home/dagster.yaml`
변경은 전용 instance에만 적용된다. shared host에서 monitoring enabled, start/cancel 300초,
job max_runtime tag, run_retries enabled/기본 0/asset-op 실패 false를 확인한다. project transport
limit 3과 common job별 limit 1 및 기존 run_group 제한도 shared coordinator에 적용해야 한다.
Manager 설정·운영 shared daemon의 실제 worker kill/retry child/RSS 검증은 별도 운영 작업이다.

1. 별도 테스트 DB에 `alembic upgrade head`·`alembic check` 실행.
2. provider 보호 상태/최근 관측을 기록하고 새 스케줄 발화를 멈춘 뒤 worker drain.
3. 운영 DB에 추가 migration 적용, code-server 후보 배포, location reload 및 recovery sensor 확인.
4. shared instance 설정을 읽어 위 조건 확인, 스케줄을 복구한다.
5. active 오래된 실행·CollectionRun terminal·다른 location health와 provider receipt를 관찰한다.

## 메모리와 관리자 UI

배편 재사용 조회는 전체 시간표 JSON 대신 날짜·항구·시각·DB JSON 길이만 읽는다.
장소 보강은 100개 ID와 현재 시설 한 행, KRIC는 호출 예산 수만큼 후보를 보유한다.
provider 목록은 100페이지/50,000행을 넘으면 저장 전 실패하여 무한 페이지 누적을 막는다.
이는 Python 구조 상한이며 전체 운영 RSS를 보장하는 실측 값은 아니다.

공통 LoginForm/AppMenu/DagsterOperations와 tokens를 vendored tarball로 사용한다.
최근 30건 밖의 active run도 별도로 조회·중복 제거하고 runtime tag로 정체를 표시한다.
실패 상세는 소유 location+UUID, 1000 event 페이지/최대20페이지/15초/최근3개로 제한한다.
GraphQL proxy는 인증·Origin·허용 작업을 유지하고 요청 4KiB·응답 4MiB·10초 본문 제한을 적용한다.

## 검증 기록

최종 candidate SHA, CI, 두 독립 적대 리뷰, n150 live UI 결과는 이 PR의
`docs/reviews`와 `docs/journal.md`에 기록한다. 운영 shared 제어 평면 적용 여부를 격리 후보
검증과 구분하며, 실행하지 않은 운영 배포 검증을 PASS로 집계하지 않는다.
