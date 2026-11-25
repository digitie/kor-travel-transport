# ADR-016: 기준정보의 불변 본문과 HTTP cursor handle 수명을 분리한다

- **상태**: accepted (제품7a5d0c4·운영0042 수용)
- **날짜**: 2026-11-10
- **결정자**: agent + human
- **컨텍스트**: 사용자가 최초 본문12.43초의 분석 뒤 개선을 승인했다. 분석에서 요청 중 전체 조립·저장과
  15~30분 cursor 만료 뒤 같은 본문까지 재생성되는 경로를 확인했다. 데이터 신선도·실패 즉시 반영과
  기존 cursor의 고정 집합/만료 계약은 유지해야 한다.
- **결정**: `reference_export_artifacts/items`에 입력 revision별 불변 본문을 저장하고,
  `reference_export_artifact_heads`가 종류/설정 범위별 현재 본문을 pin한다. `service_export_snapshots.artifact_id`
  FK로 작은 유한 handle을 발급한다. 기존 NULL FK의 handle/항목은 그대로 읽는다. 데이터 revision에는
  실제 source·주소·매핑·release 값을 사용하며 상태 TTL은 늘리지 않는다.
- **근거**: cursor TTL만 늘리면 데이터 본문과 탐색 수명의 결합이 남는다. 매 epoch마다 항목 복사도
  피하려면 불변 본문과 handle을 별도 식별해야 한다. 현재 head와 남아 있는 모든 handle이 참조한 본문은
  삭제하지 않으며, key-share/skip-locked와 FK가 재사용/GC 경합을 보호한다. head는 새 revision에만 바꾼다.
- **결과 (긍정)**: 장기 유휴 뒤에도 같은 본문을 다시 구성하지 않고 새 handle만 발급한다. 기존 수집 후
  준비 op와 예약 없는 내부 준비 job이 HTTP 밖에서 canonical 본문을 생성할 수 있다. JSON 배열의
  `INSERT SELECT`로 재파싱·행별 JSON serializer 반복도 줄인다.
- **결과 (부정)**: migration0042와 파생 본문 보관/GC 관계가 추가된다. 범위는 서버 설정으로 정해지며
  질의별 캐시를 생성하지 않는다. 현재 본문과 남아 있는 handle의 pin은 유지한다. 입력 해시의 전체 값
  확인 비용은 여전히 남고, 아직 준비되지 않은 새 입력은 기존처럼 요청에서 안전하게 구성한다.
- **검증**: 유휴/구 cursor·실패 상태·동시 생성/GC·migration과 Docker PG18 집중41개,
  ARM64 교대 비교·운영 새 이미지/0042·내부 준비/실제 HTTP를 수용했다.
  [수치·실패 이력·남는 비용](../reports/2026-11-10-reference-artifact-improvement.md)을 구분한다.
- **후속**: 전체 CI backend 결과를 정산한다. 조건부304·입력 해시·미준비 구성 비용은 남는다.
  모든 writer를 포괄하는 revision을 입증하기 전에는 입력 해시를 단순 timestamp로 대체하지 않는다.
- **사실 갱신(2026-11-24, 결정 불변)**: 준비 경로를 보강했다 — 종류별 격리(Map이 읽는 철도역·여객선 먼저, 한
  종류 실패가 다른 종류와 수집 run을 막지 않음), 경합은 `busy`(연속 3회면 실패로 올림), 준비 전체에 예산 하나(전용
  job·배포 직후 120초, 수집 job 꼬리 60초, 남은 종류는 `deferred`), 오프라인 문장·잠금 상한(60초·5초, HTTP는
  15·10·2초 그대로), 준비 뒤 제한 정리(만료 handle → 미사용 본문, 50개·10초), HTTP 경로 정리의 savepoint 격리,
  배포가 끝난 뒤 운영자가 부르는 code-server 안 직접 준비(API와 code-server의 `RELEASE_SHA`가 같을 때만).
  입력 revision의 `release_sha`는 그대로이며 code fingerprint로의 교체는 후속이다.
  [성능 문서](../architecture/performance.md#기준정보-본문-오프라인-준비의-격리상한정리2026-11-24)·
  [배포 런북](../runbooks/deployment.md#배포-직후-best-effort-warm기준정보-본문-준비loopback-export-확인-2026-11-24).
- **결정 갱신(2026-11-25)**: 입력 revision namespace의 배포 식별자를 `release_sha`에서 **본문 코드 지문**
  (`export_references.REFERENCE_PAYLOAD_FINGERPRINT`)으로 바꾼다. 위 "결정"의 "release 값"과 2026-11-24 사실 갱신의
  "code fingerprint로의 교체는 후속"을 이 항목이 대체한다.
  - **무엇을 해시하나**: import 때 한 번, sha256으로(`app/services/reference_payload_fingerprint.py`) — bus·ferry·rail·
    parking payload builder 함수 소스, `export_addresses` 모듈(`export_admin_addresses`), 철도 매핑 읽기
    helper(`persisted_mapping_context`·`persisted_station_links`·`mapping_revision`), artifact 저장(`reference_artifacts`)과
    입력 revision(`reference_export_revision`) 모듈 소스, `export_references` 모듈의 단순 상수(source 이름·batch 크기 등,
    dunder 제외), 네 page model(`BusTerminalExportPage`·`FerryPortExportPage`·`RailStationExportPage`·
    `ParkingCurrentExportPage`)의 `model_json_schema()`, `kor-travel-common`·`python-krairport-api`의 설치 버전과 VCS
    commit(`importlib.metadata`·`direct_url.json`). 소스는 `inspect.getsource`(universal newline)로 읽어 설치 경로·줄바꿈·
    hash seed와 무관하다. namespace 표지는 `reference-input-v2`다.
  - **효과**: 본문 코드·schema·형제 라이브러리가 그대로인 배포는 artifact를 재사용한다(배포마다 rail·ferry·bus·parking
    전체 재구성이 없어진다). API와 code-server의 `RELEASE_SHA`가 달라도(한쪽만 `unknown`, compose build 등) 코드가 같으면
    같은 namespace라 head가 서로 뒤집히지 않는다. `RELEASE_SHA` 없이 띄운 컨테이너도 artifact 경로·기동 warmup·준비를
    쓴다(전에는 `unsupported_revision`).
  - **유지**: 읽을 때 `spec.page_model`로 다시 검증한다. 지문을 만들 수 없으면(소스 없는 배포) `None`이고 artifact 없는
    완전 구성 경로로 간다(느리지만 정확, 준비는 `unsupported_revision`). 같은 DB 입력·같은 지문만 재사용한다.
  - **배포 직후 준비의 대조**: `/health`에 `reference_payload_fingerprint`를 싣고, `scripts/post-deploy-warm.sh`는 그 값을
    `app.deploy.prepare_references --expect-payload-fingerprint`로 넘긴다. code-server의 지문이 다르면(한쪽만 롤백 등)
    준비하지 않는다(exit 4 `fingerprint_mismatch`). `RELEASE_SHA` 대조는 없앴다.
  - **이전(1회)**: 이 변경이 처음 배포되면 namespace 값이 한 번 바뀌어 모든 본문이 한 번 다시 만들어진다(배포 직후
    준비 또는 다음 공항 수집 준비·첫 Map 페이지). 옛 artifact는 남은 handle이 만료된 뒤 기존 GC가 지운다. 이후로는
    본문 코드가 바뀐 배포에서만 다시 만든다. 지문에 넣지 않은 코드(조회 경로 ETag·cursor, 다른 모듈의 helper)가 본문
    값을 바꾸게 되면 지문 입력에 추가하거나 `FINGERPRINT_SCHEME`을 올린다.
  - **검증**: `tests/test_reference_payload_fingerprint.py`(builder·schema·의존성 버전/commit·상수 변경 → 지문 변경,
    다른 프로세스·hash seed·`RELEASE_SHA`에서 같은 값, 지문이 다르면 artifact 재사용 안 함, 같은 지문이면 `RELEASE_SHA`가
    달라도 재사용).
