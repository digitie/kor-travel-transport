# 테스트 전략

> 현재 운영 대상은 `192.168.1.14`다. 아래의 13번/ODROID 경로는 기존 시스템의 관찰·rollback 기록이며, 13번에서는 Docker를 실행하거나 중지하지 않는다. 현재 배포는 [`migration.md`](migration.md)와 `scripts/deploy-server14.sh`를 사용한다.

## 목표

- 백엔드와 프론트엔드 변경을 함께 검증한다.
- Windows 로컬 테스트는 지양하고, WSL2를 기준으로 검증한다.
- 1차 테스트는 WSL2 셸에서 로컬 런타임으로 실행한다.
- 2차 테스트는 WSL2 Docker 컨테이너 안에서 실제로 실행한다.
- 반응형 UI와 실데이터 수집 흐름을 함께 확인한다.

## 기본 검증 순서

변경 후 검증 순서는 아래를 기본값으로 한다.

1. `WSL2` 셸에서 1차 테스트
2. `WSL2 + Docker`에서 2차 테스트
3. 192.168.1.14 배포
4. 192.168.1.14 스모크 체크

Windows PowerShell에서 실행한 테스트는 참고용으로만 본다. 배포 스크립트 실행, 압축, SSH 상태 확인처럼 Windows 도구가 필요한 작업에는 PowerShell을 사용할 수 있지만, 테스트 통과 기준으로 삼지 않는다.

## WSL 1차 테스트

백엔드:

```bash
python -m pytest backend/tests -q
```

프론트엔드:

```bash
cd frontend
npm run test -- --run
npm run build
```

1차 테스트는 빠른 피드백을 위한 단계다. 여기서 실패하면 Docker 테스트나 n150 배포로 넘어가지 않는다.

## 백엔드 테스트

주요 범위:

- 파서
- 수집 서비스
- 분석 로직
- 요금 계산
- FastAPI API

주요 확인 항목:

- `timeseries` 7일 x 10분 버킷 계산
- `timeseries` 기본 미래 축 없음
- `timeseries` 명시적 `future_hours` 요청 시 미래 구간 `lot_observations=0` 처리
- `threshold-events` 임계치 진입 / 회복 계산
- `by-weekday-hour` 요일 x 시간 상세 집계
- `holiday-patterns` 최근 공휴일/토요일/일요일 날짜별 시간대 집계
- `holidays/summary` 공휴일 문장과 기간 조회
- `admin/collector-status` 응답
- `sample` / `live` 클라이언트 선택 규칙
- 인천 주차 응답의 실시간 `datetm` 파싱
- 인천 요금 API 응답의 단기/장기/예약 규칙 변환
- 한국공항공사 한도 초과 상태에서도 인천 주차/요금 수집을 계속하는지 확인
- `/v1/flights/status` 샘플 응답과 접근 오류 정규화
- 한국공항공사 `15113771` ODCloud 비행편 응답 정규화
- 인천공항 도착/출발 비행편 응답 정규화

2차 Docker 실행:

```bash
docker compose run --rm --no-deps -e DATABASE_URL=sqlite+aiosqlite:///:memory: -e PARKING_RADAR_TEST_SQLITE_TEMP=1 backend pytest -q
```

이 명령은 로컬 Docker 또는 n150의 `kor-travel-airport` Compose project에서만 실행한다. 13번에는 보내지 않는다.
테스트 fixture는 운영 `DATABASE_URL`을 읽지 않으며, 위 명령은 테스트별 임시 SQLite를 강제한다.
PostgreSQL 통합 검증이 꼭 필요할 때만 전용 DB DSN과 안전 표지를 모두 명시한다. 운영 DB DSN을
`TEST_DATABASE_URL`에 넣는 행위는 금지한다.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://.../kor_travel_transport_test \
PARKING_RADAR_TEST_DATABASE=1 \
docker compose run --rm --no-deps backend pytest -q
```

## 프론트엔드 테스트

주요 범위:

- API 클라이언트 URL 생성
- 대시보드 렌더링
- 모바일 / 데스크톱 분기
- 마지막으로 본 공항 / 주차장 복원
- 시계열 툴팁
- 시계열 계단형 라인과 X축 라벨 레이아웃
- 시계열 공휴일/토요일/일요일 배경과 이름 표시
- 하루 흐름 오버레이 차트의 0~24시 7일 겹침 표시
- 하루 흐름 오버레이 차트의 날짜별 선 숨김 / 다시 표시
- 하루 흐름 오버레이 차트의 출발편 / 도착편 마커 개별 토글
- 하루 흐름 오버레이 차트의 공휴일/토요일/일요일 선/마커 구분 표시
- 하루 흐름 오버레이 차트의 비행편 마커와 편명/출도착 정보 표시
- 하루 흐름 오버레이 차트의 비행편 마커 hover / click 강조
- 비행편 API 응답이 지연되거나 끝나지 않아도 주차 현황 로딩이 먼저 완료되는지 확인
- 모바일 stale cache 방지를 위한 `/` 및 `/api/backend/*` no-store 응답 헤더
- 모바일에서 보조 정보가 접힘 섹션으로 내려가고, 주차 현황과 최근 흐름이 먼저 보이는지 확인
- 모바일 시간대 히트맵에서 가로 스크롤 시 첫 열이 고정되어 요일/공휴일 기준을 읽을 수 있는지 확인
- 요일 x 시간 히트맵
- 공휴일 시간대 패턴 히트맵
- 요일 x 시간 히트맵의 최고/최저 혼잡 시간 요약
- 요일별 임계 달성 시간 / 날짜별 임계 달성 시간
- 요금 계산기

2차 Docker 실행:

```bash
docker compose run --rm --no-deps frontend npm run test -- --run
```

## 반응형 검증

배포 origin을 지정한 live E2E는 브라우저 설치 후 실행한다. 현재 승인 기준은 반드시
`https://pr.digitie.mywire.org`이며, n150 직접 주소는 앱 자체 검증용 보조 경로다.

```bash
cd frontend
npm run e2e:install
E2E_BASE_URL=https://pr.digitie.mywire.org npm run test:e2e
E2E_BASE_URL=http://192.168.1.14:14002 npm run test:e2e  # 보조 검증 (T-032 이후 web 포트)
```

GitHub Actions의 `live-e2e` job은 항상 정확한 `https://pr.digitie.mywire.org`를 사용한다.
외부 라우팅이 Home Assistant나 다른 서비스로 향하면 이 job과 운영 승인 모두 실패로
취급한다.

공유 n150를 매 push/PR마다 변경하지 않도록 CI는 백업 목록·경고·레이아웃을 검증하고
실제 dump 생성은 기본적으로 실행하지 않는다. 백업 UI까지 한 번 실제로 확인할 때만 아래
환경 변수를 명시한다. 이 실행은 DB 백업을 만들므로 동시 CI가 없는 시점에 수행한다.

```bash
EXERCISE_LIVE_BACKUP=true \
E2E_BASE_URL=https://pr.digitie.mywire.org \
EXPECTED_RELEASE_SHA="$(git rev-parse HEAD)" \
npm run test:e2e
```

데스크톱:

- 현재 주차 현황 표 렌더링
- 시계열 차트 렌더링
- 요일 x 시간 히트맵 렌더링
- 요일 x 시간 히트맵과 최고/최저 혼잡 시간 요약 렌더링
- 임계 달성 시간 표 렌더링

모바일:

- 현재 주차 현황 카드 렌더링
- 패널이 세로 흐름으로 배치되는지 확인
- 차트 툴팁이 터치로 동작하는지 확인

## 시각과 수동 수집 검증

API 확인:

- `GET /v1/parking/current`
- `GET /v1/admin/collector-status`

확인 포인트:

- `observed_at`이 UTC ISO 8601인지 확인
- `collected_at`이 UTC ISO 8601인지 확인
- `latest_snapshot_collected_at`이 UTC ISO 8601인지 확인
- 브라우저에서는 같은 값이 KST로 보이는지 확인

UI 확인 (로컬 profile에서 `ENABLE_MANUAL_COLLECT=true`일 때만):

- `데이터 기준 시각`
- `지금 수집` 버튼

동작 확인:

1. `지금 수집` 1회 실행
2. 성공 메시지 확인
3. 즉시 다시 실행
4. 수동 수집 제한 에러 메시지 확인

## 실데이터 수집 검증

권장 절차:

1. 실데이터용 백엔드를 별도 포트로 띄운다.
2. `ENABLE_SCHEDULER=true`
3. `USE_SAMPLE_CLIENT_WHEN_NO_KEY=false`
4. `DATA_GO_KR_SERVICE_KEY` 설정
5. 빠른 검증이 필요하면 임시로 `COLLECT_INTERVAL_SECONDS=15`로 줄인다.
6. `GET /v1/admin/collector-status`에서 최근 실행 이력을 본다.
7. 검증이 끝나면 live 검증 스택을 즉시 내린다.

정상 신호:

- `scheduler_enabled=true`
- `client_mode=live`
- `status=success`
- `raw_response_count>=1`
- 인천 수집을 검증할 때는 `enabled_sources`에 `incheon_parking` 또는 `incheon_fee`가 포함되는지 확인
- 인천공항까지 운영 대상이면 `AIRPORT_CODES_CSV`에 `ICN`이 포함되는지 확인

추가 해석:

- 첫 실행에서 `snapshot_count>0`
- 이후 실행에서 `snapshot_count=0`일 수 있음
  - 원본 `observed_at`이 그대로면 중복 저장을 건너뛰기 때문
- `upstream_rate_limited=true`이면 이미 외부 API 쿼터를 소진한 상태다.
- 단, 한국공항공사 `15056803`의 한도 초과는 인천공항 전용 `15095047`, `15095053` 수집을 막지 않아야 한다.
- 같은 인증키를 쓰는 live 수집기는 한 번에 하나만 유지한다.

종료 명령:

```bash
docker compose -f docker-compose.live.yml --project-name kor-travel-airport-live down
```

## 브라우저 검증

in-app browser 또는 브라우저에서 다음을 확인한다.

- 로컬 확인은 [http://localhost:3000](http://localhost:3000)와
  [http://localhost:8000/docs](http://localhost:8000/docs)를 사용한다.
- n150 운영 직접 확인은 웹 `http://192.168.1.14:14002`, API
  `http://192.168.1.14:14001`을 사용한다(T-032 이후 포트, DB는 `14000`으로 별도
  컨테이너·loopback 전용).
- KST 기준 시각 표시
- 시계열 툴팁 표시
- 시계열 X축 라벨이 겹치지 않고 6시간 단위로 표시되는지 확인
- 최근 7일 주차 시계열에는 비행편 마커가 섞이지 않는지 확인
- 하루 흐름 오버레이 차트에서 비행편 마커가 0~24시 X축 시간 위치에 표시되고, 편명과 출발/도착 공항 정보가 보이는지 확인
- 하루 흐름 오버레이 차트에서 원하는 날짜의 선을 숨기고 다시 표시할 수 있는지 확인
- 하루 흐름 오버레이 차트에서 출발편/도착편 마커를 각각 켜고 끌 수 있고, 둘 다 끄면 모두 숨겨지는지 확인
- 하루 흐름 오버레이 차트에서 공휴일/토요일/일요일 날짜의 선이나 마커가 일반일과 다르게 보이는지 확인
- 하루 흐름 오버레이 차트에서 X축 4배 옵션을 켰을 때 0~24시 축이 넓게 펼쳐지는지 확인
- 인천공항을 선택했을 때 `15112968` 기준 도착/출발편이 같은 차트에 표시되는지 확인
- 같은 시간/출발지/도착지의 공동운항편이 하나의 마커로 묶이는지 확인
- 최근 7일 범위 안 공휴일/토요일/일요일 날짜의 배경과 이름이 표시되는지 확인
- 공항 이름 옆에 지난주/이번주/다음주 공휴일 문장이 표시되는지 확인
- 공휴일/토/일요일 패턴 패널에 최근 8개 특수일이 날짜별로 표시되는지 확인
- 6시간 단위 X축 라벨 표시
- 요일 x 시간 히트맵 표시
- 요일 x 시간 히트맵과 최고/최저 혼잡 시간 요약 표시
- 요일별 임계 달성 시간 / 날짜별 임계 달성 시간 표시
- `지금 수집` 성공 / 쿨다운 메시지 표시
- 브라우저 콘솔 `error` / `warn` 없음
- live E2E는 `frontend/e2e/live-dashboard.spec.ts`를 n150에서 실행한다.

```bash
cd frontend
E2E_BASE_URL=https://pr.digitie.mywire.org npm run test:e2e
```

CI에서는 여기에 `EXPECTED_RELEASE_SHA=${{ github.event.pull_request.head.sha || github.sha }}`를 추가해 n150에 실제 배포된
candidate와 테스트 대상 PR head가 같은지 health 응답으로 확인한다. 로컬에서 공개 n150
배포본만 재확인할 때는 `EXPECTED_RELEASE_SHA`를 생략할 수 있지만, merge 증적에는 반드시
candidate SHA와 함께 기록한다.

Playwright 결과 JSON은 `frontend/test-results/live-e2e.json`에 남긴다. 320/375/414/768px에서 page-level overflow가 1px 이하인지와 backup/restore 경고가 보이는지를 함께 확인한다.
- `https://pr.digitie.mywire.org/`와 GET 방식의 `/api/backend/airports` 응답 헤더가 `Cache-Control: no-store, max-age=0, must-revalidate`인지 확인
- `https://pr-api.digitie.mywire.org/health`가 200을 반환하는지 확인

## 192.168.1.14 배포 스모크 체크

배포 후에는 최소한 아래를 확인한다.

- `http://192.168.1.14:14002` 응답 (T-032 이후 web 포트)
- `https://pr.digitie.mywire.org/` 응답
- `http://192.168.1.14:14002/api/backend/health` 응답
- `https://pr.digitie.mywire.org/api/backend/health` 응답
- `https://pr-api.digitie.mywire.org/health` 응답
- `http://192.168.1.14:14001/health` 응답 (T-032 이후 API 포트)
- `http://192.168.1.14:14001/v1/admin/collector-status`에서
  - `client_mode=live`
  - `scheduler_enabled=true`
  - `upstream_rate_limited=false`
- public n150에서 `POST /v1/admin/collect`가 `404`로 비활성화되고, backup/restore UI는
  별도 app auth 없이 private gateway 경계 안에서 동작하는지 확인
- 웹 UI에서 (로컬 profile):
  - 현재 시각 표시가 KST 기준인지 확인
  - `지금 수집` 버튼이 노출되는지 확인

관련 문서:

- [current-state.md](</F:/dev/kor-travel-airport/docs/current-state.md>)
- [../architecture/collection.md](../architecture/collection.md)

## Docker 프론트 테스트 메모

- Docker 안의 `Vitest`는 `testTimeout=15000` 기준으로 실행한다.
- 반응형 대시보드와 폼 상호작용 테스트가 컨테이너 환경에서 느려질 수 있어 기본 5초 제한 대신 여유를 둔다.

## WSL 테스트 기준

- 모든 테스트의 기준 환경은 `WSL2`이다.
- Windows 로컬 테스트는 지양한다.
- 1차 기준은 `WSL2` 셸에서 실행한 로컬 테스트 결과다.
- 2차 최종 기준은 `WSL2` 안에서 실행한 Docker 테스트 결과다.
- 192.168.1.14 배포는 1차/2차 테스트가 모두 통과한 뒤 진행한다.
- Windows PowerShell은 배포, 압축, 원격 실행 보조 용도로 사용할 수 있지만 테스트 기준 환경으로 보지 않는다.

## WSL Node 런타임 주의

- WSL 1차 프론트 테스트는 WSL 내부에 설치된 `node`와 `npm`으로 실행해야 한다.
- WSL의 `PATH`가 Windows 쪽 `C:\Program Files\nodejs\npm`만 가리키고 WSL 내부 `node`가 없으면 `WSL 1 is not supported. Could not determine Node.js install directory` 오류가 난다.
- 이 오류는 프론트 코드 실패가 아니라 WSL 런타임 구성 문제다.
- 이 경우 WSL 내부 Node 설치를 보완한 뒤 1차 테스트를 다시 실행한다.
- 당장 검증을 이어가야 할 때는 WSL Docker의 `docker compose build frontend`와 `docker compose run --rm --no-deps frontend npm run test -- --run`으로 2차 검증을 수행하고, 1차 프론트 테스트 미실행 사유를 작업 기록에 남긴다.
