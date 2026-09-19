# 시각과 수집기 기준

## 통합 교통정보 수집

이 저장소의 목적은 공항 주차만 보여주는 데 있지 않다. 국내 여행 중 필요한 고속도로,
유가, 이후 추가될 열차·도시철도·항구·배편 데이터를 주기적으로 수집해 PostgreSQL에
보존하고, 저장된 값은 외부 OpenAPI와 내부 통계 API가 즉시 읽도록 하는 것이다.

현재 구현 범위:

- `python-krex-api`: 고속도로 실시간 소통과 돌발을 transport scheduler 기본 주기로 저장
- `python-opinet-api`: 최신 Playwright 지역별 화면 수집기로 주유소/유종 가격/편의정보를
  저장. 현재 pin된 provider의 기본 전체 실행은 8시간이며 허용 범위는 8~12시간,
  24시간 내 최대 3회다. 매 scheduler tick마다 재실행하지 않는다.
- `/v1/transport/highways/traffic`, `/v1/transport/highways/incidents`,
  `/v1/transport/fuel/stations`: PostgreSQL 최신/기간 데이터 조회
- `/v1/transport/statistics`: 저장 데이터에서 평균 속도, 돌발 건수, 유종별 가격 통계 계산
- `/v1/transport/collector-status`: 소스별 수집 상태와 마지막 실행 결과/오류 확인

통합 수집 실행은 기존 주차 수집과 별도 `CollectionRun.trigger=transport_scheduler`를
사용한다. 따라서 기존 주차 dashboard의 최근 실행/신선도 집계에 섞이지 않는다. 소스별
실행 상태는 `transport_collection_states`로 기록하며 실패 시 원본 오류도
`raw_api_responses`에 남긴다. API는 외부 원본을 매 요청마다 호출하지 않는다.
실행 transaction이 DB flush 단계에서 rollback되더라도 실패한
`CollectionRun(trigger LIKE 'transport_%')`을 별도 transaction으로 보존한다.
`collector-status.last_run`은 이 durable 실행 결과와 안정적인 `collection_failed`
오류 코드만 외부에 노출해, 이전 성공 상태를 현재 성공으로 오인하지 않게 한다.

운영 live E2E는 수집·scheduler 활성화와 `client_mode=live`, 세 소스 모두의 최근 완료를
요구한다. `last_success_at >= last_started_at`과 오류 없음으로 각 소스의 최신 시작이
실제 저장 성공으로 끝났는지 확인한 뒤 API·통계를 새로 읽는다. 소통은 15분, 유가는
13시간 이내 성공이어야 하며 소통 행·유효 유가·통계가 비어 있으면 통과하지 않는다.
비활성/샘플/부분 성공은 운영 승인으로 취급하지 않는다. 정상 돌발 0건과 변하지 않은
돌발의 중복 저장 생략은 가능하므로 돌발은 행 수 대신 소스별 최근 저장 완료를 검사한다.
결과 저장은 소스별 transaction으로 분리해, 뒤의 돌발/유가 저장 실패가 먼저 성공한
소통정보를 rollback하지 않도록 한다.

### 공급자 관측 지연 주의

2026-09-19 20:22 KST의 별도 새 연결 조회에서도 KREX 0405 응답 8,370행의 최신
관측 시각은 19:52 KST였다. 운영 저장 원본도 같은 시각을 반복 반환했다. 따라서
`last_success_at`은 조회·저장 성공이지 새로운 관측의 도착을 보장하지 않는다.
소비자는 `observed_at`/통계의 `latest_observed_at`도 확인해야 한다. 이미 저장된 같은
관측을 새 관측처럼 복제하거나 E2E 신선도 기준을 완화해 정상 상태로 표시하지 않는다.
이 값은 해당 시점의 실측이며 공급자의 공식 갱신 주기/SLA로 해석하지 않는다.

## 목적

`parking-radar`에서 보이는 시각이 왜 다른지, 어떤 시각이 무엇을 뜻하는지, 웹 UI의 강제 수집 버튼이 어떤 규칙으로 동작하는지 정리한다.

운영 수집기는 `192.168.1.14`의 PostgreSQL-backed backend에서만 실행한다. `192.168.1.13`은
cutover 동안 HTTP read-only source로 유지하며 Docker를 조작하지 않는다.

## 주기와 중복 방지

- n150 운영 기본 주기: `COLLECT_INTERVAL_SECONDS=300` (5분)
- 수동 수집 제한: `MANUAL_COLLECT_MIN_INTERVAL_SECONDS=300` (5분)
- scheduler는 collection duration을 포함해 다음 시작 시각을 monotonic deadline으로 계산한다. 수집이 5분을 넘으면 지연을 숨기지 않고 즉시 다음 tick을 시작하며, 운영 verifier가 freshness를 별도로 gate한다.
- 외부 API가 같은 `observed_at`을 반복하면 unique key에 의해 새 snapshot이 생기지
  않을 수 있다. 따라서 row 수와 함께 `observed_at`, `collected_at`, `last_run`을 확인한다.
- 고속도로 소통은 provider가 준 관측 시각과 `identity_key`를 이용해 같은 규칙으로
  중복을 막는다. 유가는 provider 갱신 시각을 우선 관측 시각으로 쓰고, 갱신 시각이 없으면
  collector 실행 시각을 사용한다. 유가 API의 기간 필터와 최신 판정은 실제 응답을 받은
  `collected_at`을 기준으로 하므로 provider 갱신 시각이 오래되어도 최신 수집 결과를
  숨기지 않는다.
- 돌발은 provider 발생시각이 아니라 수집시각을 `observed_at`으로 사용한다. 같은
  `series_no`의 처리상태 변경을 새 스냅샷으로 보존하기 위해서다.
- Playwright 수집기는 공개 화면 자동화가 공식 API가 아니라는 위험이 있으므로, 화면
  구조가 바뀌거나 자동화 차단이 발생하면 실패를 기록하고 임의의 빈 성공 데이터로
  덮어쓰지 않는다.

## 시각 기준

- 백엔드 저장 기준: UTC
- 백엔드 API 응답 기준: UTC ISO 8601
- 프론트엔드 표시 기준: KST

즉, DB와 API는 UTC를 기준으로 일관되게 다루고, 브라우저 화면에서는 항상 KST로 변환해서 보여준다.

## 화면에 보이는 시각의 의미

현재 UI는 사용자가 해석해야 하는 시각을 하나로 단순화한다.

- `데이터 기준 시각`
  - 사용자가 가장 먼저 봐야 하는 시각
  - 현재 화면에 보이는 주차 상태가 실제로 언제 관측된 값인지 뜻한다.
- 수집기 동기화 시각은 `GET /v1/admin/collector-status`와 운영 로그에서만 확인한다.

### 데이터 기준 시각

- 각 주차장 상태의 `observed_at`
- 원본 데이터가 실제로 관측된 시각
- 사용자가 가장 먼저 봐야 하는 핵심 시각

예시:
- API가 `2026-04-26T11:30:00Z`를 반환하면 UI에는 `04.26 20:30 KST`로 보인다.

### 저장 시각(`collected_at`)

- 각 row의 `collected_at`은 여전히 DB와 API에 남아 있다.
- 다만 사용자에게는 해석 부담이 커서 메인 화면에서는 직접 노출하지 않는다.
- 운영 디버깅이 필요할 때만 API나 백엔드 로그에서 확인한다.

## 왜 관측 시각과 수집 시각이 다를 수 있는가

다음 경우는 정상 동작이다.

1. 원본 제공기관이 아직 같은 관측시각을 계속 내려준다.
2. 수집기는 다시 실행된다.
3. 하지만 `observed_at`이 같아서 중복 저장을 건너뛴다.
4. 이 경우 현재 주차장 row의 `collected_at`은 그대로일 수 있다.
5. 대신 수집기 상태 API나 다른 주차장의 최신 적재 시각은 더 최근일 수 있다.

따라서 화면 해석은 아래처럼 하는 것이 맞다.

- 사용자가 확인해야 하는 기준 시각: `데이터 기준 시각`
- 수집기 동작 점검용 시각: `latest_snapshot_collected_at` (API/로그 전용)

## 강제 수집 버튼 (로컬 개발 전용)

로컬 개발 profile에서 `ENABLE_MANUAL_COLLECT=true`일 때만 웹 UI의 `지금 수집` 버튼이
`POST /v1/admin/collect`를 호출한다. public n150 profile에서는 `ENABLE_MANUAL_COLLECT=false`로
버튼과 endpoint가 모두 비활성화되고, 웹 proxy에도 노출되지 않는다.

동작 규칙:

- 수동 수집 제한은 `manual_collect_min_interval_seconds`를 따른다.
- 프론트엔드는 먼저 `GET /v1/admin/collector-status`를 보고 사용자에게 즉시 안내한다.
- 백엔드도 동일한 제한을 강제한다.
- 즉, 프론트 우회 호출을 하더라도 백엔드에서 다시 막는다.

### 사용자 메시지

제한 시간 이내 재실행 시 UI는 아래와 같은 에러를 보여준다.

- `마지막 업데이트 후 10분이 지나지 않았습니다. 04.26 20:49 KST 이후 다시 시도해 주세요.`

### 성공 시 메시지

- `즉시 수집을 완료했습니다. 신규 스냅샷 10건을 저장했습니다.`

## 검증 방법

### API 검증

1. `GET /v1/parking/current`
2. `GET /v1/admin/collector-status`
3. `observed_at`, `collected_at`, `latest_snapshot_collected_at`이 UTC ISO 문자열인지 확인
4. 브라우저에서는 같은 값이 KST로 보이는지 확인

### 브라우저 검증

1. `http://localhost:3000` 접속
2. `데이터 기준 시각` 확인
3. `지금 수집` 1회 실행
4. 성공 메시지와 `다음 수동 수집 가능` 시각 확인
5. 바로 다시 눌러 제한 에러 메시지 확인

## 이번 기준에서 확인된 사실

- 현재 localhost 스택이 sample 모드여도 UTC 저장과 KST 표시는 정상 동작한다.
- UI의 `데이터 기준 시각` 표기와 API의 UTC 시각 변환은 일치한다.
- 강제 수집 버튼은 정상 동작하고, 제한 시간 이내 재실행은 UI와 백엔드 양쪽에서 차단된다.
