# Transport 읽기 성능 개선 — 2026-11-18

Map [PR1505](https://github.com/digitie/kor-travel-map/pull/1505)의 §8 `T-READ-TRN-01`~`04`를
Transport main `6f9a947e496b49522bb12a3c4166e0e37af5e922` 위에서 구현·측정했다.
현재 범위는 draft PR이다. 운영 변경·이미지 빌드·배포·DB 스키마 변경은 없다.
Weather 선행 배포 뒤 부모 작업이 Transport 병합·배포 순서를 결정한다.

## 변경

### T-READ-TRN-01 — 요청 비용 관측

- ASGI 미들웨어가 route template·status·`duration_ms`·`sql_count`·`sql_ms`·`cpu_ms`를
  1초 이상 요청의 한 줄 로그로 남긴다. 기본 로그 수준에서도 기록되도록 warning을 쓴다.
- query string·실제 ID·좌표·SQL 본문·bind·인증값은 기록하지 않는다. 미매칭 경로는 `unmatched`다.
- `Server-Timing`은 응답 header를 보내기까지의 app/SQL/CPU 시간과 SQL 수다.
  느린 요청 로그는 streaming 본문 전송 종료까지 포함한다.
- CPU는 `process_time()`의 요청 시작/끝 차이다. 병행 요청·background 작업의 CPU도 섞일 수 있으므로
  단독 A/B 표본에서 비교했다. 요청에 배타적으로 귀속한 CPU 지표로 해석하지 않는다.
- ContextVar로 동시 요청의 SQL 계수를 분리한다. `/metrics` 경로나 gateway allowlist는 추가하지 않는다.

### T-READ-TRN-02 — 다중 종류 장소 조회

PostgreSQL 다중 종류 요청은 7종류의 정확한 COUNT와 제한된 행 투영을 한 UNION ALL 문장으로 받는다.
공항은 검증된 krairport 좌표 번들과 기존 Python 필터를 유지한다. 유가 가격·신선도와 출처 목록도
현재 DB에서 읽는다. 출처 DISTINCT는 선택한 종류의 UNION으로 한 번만 조회한다.

전체 `raw_item_json`을 전송하지 않는다. 철도 시설 5개 원문 키와 항구·터미널의
`_manual_location.revision`만 SQL에서 뽑는다. 현재 pin된 provider parser로 시설을 해석하며,
최종 DTO는 부모 응답에서 한 번 검증한다. 이름·정렬·균등 배분·검색·좌표 범위·출처 필터·정확한
`kind_totals`·`total`·`truncated` 계약을 유지한다. 단일 유가 JSON 경로·저배율 집계는 유지한다.
SQLite 개발 경로는 기존 행 조회를 사용한다.

| 같은 합성 표본, 4회 교대 중앙값 | 기준 main.py | 후보 |
| --- | ---: | ---: |
| SQL 문장 수 | 26 | 6 |
| 요청부터 본문 수신 완료 | 966.5ms | 253.6ms |
| 프로세스 CPU | 697.4ms | 165.9ms |

반환 4,379개 장소와 모든 응답 필드가 동일했다(`generated_at` 제외).
CPU는 76.2%, 응답 시간은 73.8% 감소했다. WSL Python 3.13.14·잠금 의존성,
로컬 PostgreSQL18 Docker(CPU 2개·메모리 1GiB)에서 측정했다. 종류별 800개 합성 기준정보와
유가 5종·큰 미사용 원문이 있는 표본이다. 원시 8표본은
[측정 JSON](../audits/2026-11-18-read-performance.json)에 있다.
기준은 `git show origin/main:backend/app/main.py`를 동일 런타임에서 로드했다.
운영 ARM 지연·실제 이용자 분포·다른 호스트 부하까지 증명하는 수치가 아니다.

재현: 격리 loopback `*_bench` DB를 Alembic head로 준비한 뒤 비공개 환경으로
`TEST_DATABASE_URL`과 `KOR_TRAVEL_TRANSPORT_TEST_DATABASE=1`을 주고 실행한다.

```bash
backend/.venv/bin/python scripts/benchmark-read-performance.py \
  --baseline-ref 6f9a947e496b49522bb12a3c4166e0e37af5e922 \
  --output /tmp/transport-read-performance.json
```

### T-READ-TRN-03 — 싼 조건부 참조 export

불변 본문 digest와 snapshot ID·만료·페이지 offset/limit·최신 상태로 ETag를 계산한다.
artifact/handle 일치·cursor 범위·만료·현재 상태를 확인한 뒤 **페이지 payload SELECT와 DTO 구성 전**
304를 반환한다. 상태 변경·다른 페이지·TTL epoch·새 집합은 무효화한다. 기존 소비자는 첫 요청에서
새 ETag를 받고 이후 동일 규칙으로 조건부 요청할 수 있다. OpenAPI DTO는 바뀌지 않는다.

입력 fingerprint는 engine별 최대 64개를 재사용한다. head generation만 키로 삼으면
수동 수정·주소·매핑처럼 generation/시각이 그대로인 변경을 놓치므로 PostgreSQL의 **완전한 MVCC snapshot
(xmin/xmax/진행 중 XID 목록)**과 head·release·kind도 키로 둔다. 자기 transaction에서 쓰기를 했거나
ORM의 미반영 변경이 있으면 재사용하지 않는다. 다른 테이블의 쓰기도 보수적으로 무효화하므로
지속 쓰기 중 fingerprint가 매 요청 다시 계산될 수 있다. generation당 한 번이라는 느슨한 캐시로
정확성을 희생하지 않는다. 기존 미만료 handle은 FK가 보호하므로 재사용 때 불필요한 key-share 잠금과
XID 발급을 생략한다. 새 handle은 기존 잠금·FK·CAS·GC 경로를 그대로 따른다.

800개 합성 참조의 warm 304 5회 중앙값은 **42.5ms**, SQL 7개, 페이지 읽기 0회였다.
[원시 표본](../audits/2026-11-18-reference-304-local.json).
운영의 기존 4.02초 인용과 직접 비교한 수치가 아니며 운영 300ms 조건은 아직 미검증이다.

### T-READ-TRN-04 — 주차 캐시 재구성 채택 판정 대기

실제 `ParkingHistoryReadCache.refresh_once()`를 로컬 합성 520,000행에서 실행하면서
`/health`와 `/v1/airports`를 같은 API event loop로 조회했다.

| p95 | 재구성 없음 | 재구성 중 | 배율 |
| --- | ---: | ---: | ---: |
| `/health` | 28.1ms | 291.3ms | 10.37배 |
| `/v1/airports` | 31.1ms | 283.9ms | 9.13배 |

[원시 관측](../audits/2026-11-18-parking-rebuild-local.json).
이 표본은 운영 간섭이 존재한다고 확정하지 않는다. **운영 구간의 p95 2배 조건을 확인하기 전에는
캐시 소유 프로세스·신선도 30초·512MB 한도·Dagster 구조를 변경하지 않았다.**
부모가 정상 재구성 시각의 bounded read-only 관측을 조정한다.

```bash
python3 scripts/observe-read-baseline.py \
  --base-url http://127.0.0.1:<Transport_API_포트> \
  --seconds 60 --output /비공개경로/transport-read-baseline.json
```

loopback의 `/health`·`/v1/airports` GET만 0.5초 간격으로 호출한다. 관측창 최대 60초,
마지막 진행 요청의 socket timeout은 5초다. 선택적 `--large-map-samples`는 기본 0이며
명시할 때만 최대 3회 추가한다. 자동 수집/재구성을 강제로 실행하거나 설정·DB를 바꾸지 않는다.
재구성 시작/끝의 별도 운영 로그와 대조해야 한다. 시크릿·본문·query string을 결과에 남기지 않는다.

## 검증과 남은 수용

- 초기 SQLite 회귀: 45 PASS / PG 전용 20 SKIP.
- PostgreSQL 넓은 회귀: 135 PASS / fingerprint 메모 재사용 시험 1 FAIL.
  기존 key-share 잠금이 read-only 요청에 XID를 계속 발급하는 원인을 수정했다.
- 수정 뒤 WSL PostgreSQL 집중 38 PASS, Docker 격리 동일 집중 38 PASS.
  Docker는 기존 `python:3.13` 이미지와 이 작업의 잠금 의존성 venv를 read-only 재사용했다.
  새 제품 이미지 빌드나 GDAL 재컴파일을 뜻하지 않는다.
- 후속 자기 transaction 쓰기·일반 유가 이력 ETag 회귀 44 PASS, OpenAPI 정본 일치.
  전체 MVCC 메모는 RR/serializable에서만 사용하고 READ COMMITTED에서는 비활성이다.
  이 guard 뒤 메모·자기 쓰기 delta는 WSL/Docker 각각 2 PASS.
- 전체 CI·운영 300ms·운영 p95 재구성 판정·배포 후 관측은 부모 순차 작업의 미완 항목이다.
- Map/N150·운영 DB·관리자 계정·기존 GDAL/BuildKit 캐시는 변경하지 않았다.
