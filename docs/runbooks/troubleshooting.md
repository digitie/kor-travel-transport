# 트러블슈팅

> 현재 운영은 192.168.1.14의 Docker/PostgreSQL이며 scheduler 계약은 300초,
> 유효 tick은 180초다. 192.168.1.13/ODROID 관련 수치와 SQLite 항목은 historical
> reference로만 읽고, 13번에는 Docker를 실행하지 않는다.

## 프론트에서 `fetch` 에러가 보일 때

먼저 확인:

1. [http://localhost:8000/health](http://localhost:8000/health)
2. [http://localhost:8000/admin/collector-status](http://localhost:8000/admin/collector-status)
3. backend 컨테이너 로그

자주 있는 원인:

- backend 컨테이너가 내려감
- SQLite 파일 접근 오류
- 프론트 이미지는 새 버전인데 backend가 예전 설정으로 떠 있음

## `client_mode=sample`인데 실데이터라고 생각한 경우

원인:

- `DATA_GO_KR_SERVICE_KEY`가 비어 있음
- `USE_SAMPLE_CLIENT_WHEN_NO_KEY=true`
- 컨테이너를 기본 환경 변수로 다시 띄움

확인 포인트:

- `client_mode=live`
- `data_go_kr_service_key_configured=true`

## `scheduler_enabled=false`인데 자동 수집이 안 된다고 느끼는 경우

자동 수집은 `ENABLE_SCHEDULER=true`일 때만 돈다.  
그 외에는 수동으로 아래 API를 호출해야 한다.

```bash
curl -X POST http://localhost:8000/admin/collect
```

## 인천공항 주차장 정보가 수집되지 않을 때

먼저 확인:

1. `GET /v1/admin/collector-status`
2. `.env` 또는 `.env.odroid`의 `ENABLE_INCHEON_COLLECTION`
3. `.env` 또는 `.env.odroid`의 `AIRPORT_CODES_CSV`
4. 최근 `collection_runs`의 `enabled_sources`

반복해서 확인해야 하는 원인:

- `ENABLE_INCHEON_COLLECTION=false`이면 `15095047`을 호출하지 않는다.
- `AIRPORT_CODES_CSV`에 `ICN`이 없으면 인천공항은 수집/표시 대상에서 빠진다.
- `ENABLE_INCHEON_FEE_COLLECTION=false`이면 `15095053` 요금 규칙은 수집하지 않는다.
- 한국공항공사 `15056803` 한도 초과 상태가 인천 전용 API 호출까지 막으면 안 된다.

현재 기준:

- `2026-05-09` 수동 확인에서 `15095047` 인천 주차 정보는 `resultCode=00`, `NORMAL SERVICE.`를 반환했다.
- `2026-05-09` 수동 확인에서 `15095053` 인천 주차요금 정보는 `resultCode=00`을 반환했다.
- 수집 로직은 한국공항공사 주차 API가 한도 초과 상태여도 인천 주차/요금 수집을 계속 시도하도록 분리되어 있다.

주차장 이름 주의:

- 인천 실시간 주차 응답은 `T1 단기주차장지하1층`처럼 층 정보가 붙을 수 있다.
- 요금 규칙은 `T1 단기주차장`, `T2 장기주차장` 같은 접두어 기준으로 연결한다.
- 따라서 화면에서 보이는 세부 주차장명이 요금 규칙명과 완전히 같지 않아도 정상일 수 있다.

## `snapshot_count=0`이라 수집 실패로 오해한 경우

이 값은 실패를 뜻하지 않을 수 있다.

정상 케이스:

- `status=success`
- `raw_response_count>=1`
- 원본 API의 `observed_at`이 직전 실행과 같음

이때는 중복 저장을 방지하느라 `parking_snapshots` 추가 건수가 0으로 보이는 것이다.

## 관측 시각이 이상하거나 오래돼 보일 때

먼저 구분:

- `최근 관측 시각`
- `최근 수집 시각`
- `수집기 마지막 적재`

점검 순서:

1. `GET /v1/parking/current`
2. `GET /v1/admin/collector-status`
3. API는 UTC, 브라우저는 KST 기준인지 확인
4. `client_mode=sample`인지 확인

정상일 수 있는 경우:

- 원본 API가 아직 같은 `observed_at`을 내려준다
- 수집기는 다시 실행됐다
- 중복 저장을 건너뛰어 현재 row의 `collected_at`은 그대로다

즉, `관측 시각이 오래돼 보인다`와 `수집기가 멈췄다`는 같은 뜻이 아니다.

관련 문서:

- [../architecture/collection.md](../architecture/collection.md)

## 프론트 코드를 고쳤는데 화면이 예전인 경우

원인:

- 이미지는 다시 빌드했지만 실행 중인 `frontend` 컨테이너를 재생성하지 않음
- 모바일 브라우저 또는 중간 프록시가 예전 Next.js HTML/JS 번들을 캐시함

조치:

```bash
docker compose build frontend
docker compose up -d frontend
```

운영 기준:

- `/` HTML은 정적 장기 캐시가 붙지 않도록 `force-dynamic`, `revalidate=0`, `Cache-Control: no-store, max-age=0, must-revalidate`를 유지한다.
- `/api/backend/*` 프록시 응답도 `Cache-Control: no-store, max-age=0, must-revalidate`를 유지한다.
- ODROID 배포 후 모바일에서만 백엔드가 안 되는 것처럼 보이면 먼저 아래 헤더를 확인한다.

```bash
curl -I https://pr2.digitie.mywire.org/
curl -fsS -D - -o /dev/null https://pr2.digitie.mywire.org/api/backend/airports
```

정상 기준:

- 두 응답 모두 `Cache-Control: no-store, max-age=0, must-revalidate`를 포함한다.
- 백엔드 로그에 `/api/backend`를 통한 요청이 `200 OK`로 찍히면 백엔드 자체 장애보다 모바일의 이전 번들/캐시 문제를 먼저 의심한다.

## 모바일에서 `데이터를 불러오는 중입니다`에 오래 머무를 때

먼저 확인:

1. `GET /api/backend/parking/current?airport_code=GMP`
2. `GET /api/backend/flights/status?airport_code=GMP`
3. 모바일 브라우저 개발자 도구 또는 서버 로그의 `/api/backend/*` 응답 시간

자주 발생한 원인:

- 주차 현황 API는 정상인데 비행편 API 응답이 10초 이상 지연됨
- 프론트 초기 로딩이 비행편 API까지 한 번에 기다리면서 주차 현황도 같이 늦게 표시됨

현재 기준:

- 비행편 정보는 보조 데이터로 취급한다.
- 초기 로딩은 주차 현황, 시계열, 분석 데이터를 먼저 표시한다.
- 비행편 API는 별도 비동기 요청으로 처리하며 6초 이상 지연되면 지연 안내 상태를 표시한다.
- 따라서 모바일에서 주차 현황 카드와 최근 7일 그래프가 먼저 나오고, 비행편 마커는 늦게 붙거나 일시적으로 비어 있을 수 있다.

재발 점검:

- 프론트 테스트 `shows parking data before delayed flight status finishes`가 통과해야 한다.
- 새 데이터 소스를 초기 대시보드 `Promise.all`에 추가할 때, 보조 데이터라면 주차 현황 로딩을 막지 않도록 별도 요청이나 timeout fallback을 둔다.

## 웹 UI의 `지금 수집` 버튼이 동작하지 않거나 막힐 때

먼저 확인:

1. `GET /v1/admin/collector-status`
2. 마지막 `latest_snapshot_collected_at`
3. 화면의 안내 메시지

정상 차단 조건:

- 마지막 적재 후 제한 시간이 지나지 않음

이 경우는 오류가 아니라 의도된 보호 동작이다.

추가 확인:

- `client_mode=sample`이면 샘플 모드에서 수동 수집이 동작할 수는 있어도 실데이터 갱신은 아니다.
- 백엔드는 프론트와 별도로 수동 수집 제한을 다시 검사한다.
- `지금 수집` 버튼은 토큰 입력 없이 동작해야 한다.
- 브라우저가 공공데이터 API 키나 관리자 토큰을 요구하면 이전 프론트 번들이 남은 것이 아닌지 캐시 헤더와 배포 상태를 먼저 확인한다.

## 실데이터 모드가 다시 샘플로 돌아간 경우

원인:

- `docker compose up -d`를 기본 환경 변수로 다시 실행함

조치:

- `.env`에 실데이터 환경 변수를 넣고 실행
- 또는 같은 환경 변수를 유지한 상태로 재실행

## SQLite 관련 문제

권장:

- Docker named volume 사용

피해야 할 방식:

- OneDrive / Windows 경로 bind mount에 런타임 SQLite를 직접 두는 것

이 방식은 `unable to open database file` 같은 간헐 오류를 만들 수 있다.
## `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 반복될 때

아래 ODROID 수치와 조치 기록은 historical reference다. 현재 n150는
`COLLECT_INTERVAL_SECONDS=300`, `MANUAL_COLLECT_MIN_INTERVAL_SECONDS=300`을 사용한다.

먼저 확인:

1. `GET /v1/admin/collector-status`
2. 최근 `collection_runs` 실패 시작 시각
3. 오늘 성공한 수집 횟수

운영 범위 주의:

- ODROID live 장애를 조사할 때는 사용자가 명시하지 않은 다른 WSL2 프로젝트의 컨테이너와 프로세스를 중지하거나 변경하지 않는다.
- 다만 `parking-radar` 자체 검증은 WSL2를 기준으로 하며, 1차 WSL 테스트와 2차 WSL Docker 테스트를 거친 뒤 ODROID에 배포한다.
- ODROID live 수집 장애의 직접 원인 조사는 ODROID의 실행 상태와 로그를 우선으로 본다.
- ODROID live의 중복 호출 여부는 ODROID의 `docker ps`, `systemctl list-timers`, `systemctl list-unit-files`, `crontab`, `journalctl` 기준으로 확인한다.

현재 운영 메모:

- `15056803` 카탈로그에는 개발계정 `5,000` 트래픽이 보인다.
- 하지만 ODROID 실측에서는 `2026-04-28`에 100회 성공 후 101번째부터 제한 에러가 발생했다.
- 따라서 현재 키/서비스 조합에서는 문서상 5,000/day보다 더 낮은 실효 제한이 걸린 것으로 보고 운영한다.
- `2026-05-01 06:13:53 KST` ODROID에서 앱이 자동 재시도했지만 원 API가 다시 `resultCode=99`를 반환했다.
- 같은 시각 ODROID에서 앱을 거치지 않고 `15056803` 원 API를 직접 호출해도 `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 반환됐다.
- 이 경우 화면의 제한 메시지는 프론트/백엔드 가공 오류가 아니라 원 API의 키 단위 제한 응답이다.
- `2026-05-01` 확인 기준 ODROID에서 활성화된 수집 실행원은 `parking-radar_backend_1`뿐이다. `parking-collector.timer`는 `.disabled` 상태이고 사용자/root cron에서도 추가 수집기는 발견되지 않았다.
- 임시로 ODROID의 다음 원 API 재시도를 `2026-05-06 00:00:00 KST` 이후로 미뤘고, `2026-05-05 06:00:00 KST`에 `parking-radar-restore-backoff.timer`가 backoff 값을 `3600`으로 되돌리도록 예약했다.
- `15056803` 한도 초과 backoff는 한국공항공사 주차/요금 소스에 적용한다. 인천공항 전용 `15095047`, `15095053` 소스가 활성화되어 있으면 같은 수집 실행에서 계속 호출되어야 한다.

판단 기준:

- 5분 주기: 하루 `288`회라서 반복 장애 가능성이 높다.
- 10분 주기: 하루 `144`회라서 여전히 반복될 가능성이 높다.
- 15분 주기: 하루 `96`회지만 수동 수집이나 재기동 여유가 작다.
- 10분 주기: 하루 `144`회로, 모든 공항을 한 번의 응답에서 처리하는 현재 구조에서는 가장 공격적이면서도 현실적인 기본값이다.
- 5분 주기: 하루 `288`회라서 예전에 중복 수집기까지 겹친 상황의 실패 구간과 너무 가까워 기본 운영값으로는 보수적이지 않다.

Historical ODROID 권장 대응:

- ODROID live는 `COLLECT_INTERVAL_SECONDS=600`
- 수동 수집 제한도 `MANUAL_COLLECT_MIN_INTERVAL_SECONDS=600`
- 제한이 걸린 당일에는 주기를 바꿔도 즉시 회복되지 않을 수 있고, 다음 쿼터 리셋 이후부터 효과가 난다.
- `collector-status`에서 `upstream_rate_limited=true`와 `upstream_rate_limited_until`을 확인한다.
- 같은 인증키를 쓰는 다른 live 검증 스택이 떠 있지 않은지 먼저 확인한다.
- 특히 `kor-travel-transport-live` 같은 임시 검증 스택이 짧은 주기로 남아 있으면 쿼터를 빠르게 소진한다.
- 한도 초과가 기록된 뒤에는 수집기가 `UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS` 동안 자동으로 API 호출을 건너뛴다.
- `15056803`은 공식 문서상 개발계정 `5,000/일`이 보이더라도 실제 운영에서 더 이르게 `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 날 수 있다.
- 하루가 끝날 때까지 멈추게 두지 말고, 짧은 backoff 뒤 다시 시도해서 회복 시점을 확인한다.
- ODROID에 `parking-radar` 외 별도 수집기(`airport-parking-monitor`, `parking-collector.timer`)가 함께 살아 있으면 같은 인증키를 중복 사용하게 된다.
- `parking-collector.timer`는 10분마다 `GMP,PUS,CJU,TAE`를 개별 호출하므로 하루 최대 576회를 추가로 사용한다.
- ODROID 운영 시 동일한 인증키를 사용하는 활성 수집기는 하나만 남겨야 한다. 중복 수집기가 보이면 먼저 `systemctl status parking-collector.timer`로 확인하고, 필요 없으면 `sudo systemctl disable --now parking-collector.timer`로 중지한다.
