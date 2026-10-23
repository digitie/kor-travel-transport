# Transport T1/T4/T5 운영 배포와 T2 선행 구현 수용

## 배포 범위

PR108 빈/급감 응답 보호, PR109 현재좌표 일치 admin 블록, PR110 가격이력의 운영 소스는
e01f8e9c12929d226872ac4b44996a89d603e9f7이다. API/CS 정확 이미지·API release·healthy,
schema29 유지, gRPC12306/Manager location 재로드, 원래12개 schedule·5개 sensor 상태
복원, 공용daemonRUNNING과 관련8개 containerID 보존을 확인했다. 다른 project는 중단하지 않았다.
원래 공항·고속도로 run은 자연SUCCESS 후 교체했으며 강제종료하지 않았다.
tracked transport.override.yml을 공식 stage/deploy 경로로 설치했고 API/CS와 공개관리UI/gateway도 healthy다.

빌드·앱·이미지/증거는 NVMe를 사용했다. bounded builder는0.75CPU/1.5GiB로 실행하고 완료후
stop하여 idle부하를 제거했다. build중5초표본은 단일core기준71.65%, peak약1.5GiB/oom0이다.
이는 빌드 부하이며 수집/호스트CPU 저감 실측이 아니다. 실제 설치된 모듈의
FUEL_FETCH_TIMEOUT_SECONDS=12600을 확인했다(환경 Settings 필드가 아닌 코드상수다).

## 실제 운영 수용과 남은 원천 문제

- API 계약7개: 주유소 오래된참조503 방어, 휴게소2행/admin2개, 주유소가격이력2행/stale/gzip,
  ETag304, 다음페이지2행, 휴게소이력501, limit5001→422 PASS.
- **전체 fresh-reference readiness는 false다.** OpiNet 마지막성공은2026-10-21T00:49:20Z로
  오래되어 fuel-stations200/admin 정상자료 수용이 남았다. 503을 빈집합/삭제로 바꾸면 안 된다.
  가격이력은 계약대로 이전 성공자료를 stale로 제공한다. 휴게소·교통 최근성공과 구분한다.
- 공개HTTPS 관리UI16케이스PASS: 통계/서비스BFF 무권한차단·실로그인·6통계scope·390/1440차트·
  실제지도조회/확대2회/이동. JS/HTTP오류0·VWorld tile51성공/0실패. 실제 지도·차트를 확인했다.
  통계6조회는284~954ms의 단일표본이며 p95/성능개선율로 쓰지 않는다. 화면의 유가갱신지연 안내도 유지한다.
- 정규 fuel_collection_job을1회 큐에 넣었다(run b0d1e117-ff0d-4bb4-acf4-33c09286cc2b).
  기존job tags/4시간run상한/재시도0/소유권·동시성·호출유예를 유지하고 force수집하지 않았다.
  이 문서는 큐 등록을 수집성공/최신성 회복으로 집계하지 않는다. 실제 원천시각·집합 갱신과
  새3.5시간 수집상한 완주/오류복구·CPU/RAM은 후속 실측이다.

운영 증거는 rollout/runtime/live-api-with-readiness JSON과 실제UI report/screenshot이다.
최신 주유소 참조 미준비를 포함한 API report의 pass=false와 contract_checks_passed=true를
함께 보존한다. 배포 성공과 원천 데이터 수용 완료는 서로 다르다.

## 머지와 후속

PR112의 current pointer는 정확9da49c58 기준2리뷰·CI·새PG전체1041/2skip·격리API10/UI9 후
main1a62c748에 머지했다. [세부 검증과 baseline 구분](2026-10-23-traffic-current-pointer.md).
이번 운영배포에는 schema30/PR112를 포함하지 않았으며 기본OFF다.

T2 traffic/parking REST·T3 참조·실제 불변DTO snapshot/status/cursor·비용/GC는 남았다.
refs의 주소/좌표/매핑은 source 수집과 별도writer이므로 source성공시각만으로 페이지를 고정하지 않는다.
[작은 PR 순서](../design/map-current-reference-exports.md)를 따른다.
원래API/이력/통계·기본수집을 보존하며 CPU/RAM 저감이나 Track1/2 전체 완료를 선언하지 않는다.
