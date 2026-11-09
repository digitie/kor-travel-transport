# KRIC 일반철도·KTX 역 보강 및 서비스 복구

최신 사용자 지시로 미배포 TAGO 후보를 KRIC 기준으로 대체한다. KRIC 공개 일반323행·KTX74행의 모든 페이지를 검산하고 공식 상세 링크의 코레일 stationSeq로358역을 식별한다. 좌표198역이며 전주·순천·익산·안동은 공식 연결 좌표가 있다. 미제공160역은 추정하지 않는다.

`python-kric-api`의 KricGeneralStationClient가 요청·파싱·페이지/총수·연결 검증을 소유한다. Transport는 typed 결과를 `kric_general_portal` source와 `kric-general` head로48시간마다 원자 게시한다. 도시철도 `nationwide` head/행/코드와 기존 cursor를 보존하고 새로운 source를 T3 rail export에 합친다. 일반철도 권역 라벨은 열차 운행 노선·순서가 아니다. station_number의 공식 코레일 코드와 KRIC 도시철도 station_code는 별개다.

제공자 WSL/Docker Python3.12 각각291개, mypy12파일과 실제 공개 조회를 통과했다. 소비자의 원자 실패·기존cursor·NULL/좌표·소유권 terminal/회수 검증과 운영 수용은 정본 plan.json에 기록한다. migration·키 추가·UI 변경은 없다.

04:45UTC Docker 재시작 뒤 공유 DB·Dagster·Weather/Transport/Geo 등 기존18개 컨테이너 중지가 관측됐다. 원인·주체는 미확인이다. 사용자는 새 이미지 적용 뒤 서비스 복구를 명시했다. 중지된 정확 기존CID/image/환경/마운트를 동결하고 Transport API/CS만 새 이미지를 적용한 뒤 기존 DB/스토리지→앱→공용Dagster 순서로 복구한다. 과거 one-shot/init/migrate는 시작하지 않는다. 원 두 TAGO 빌드 실패·미배포/미수집 이력은 보존한다.

백업·복원은 사용자 선택으로 생략하며 자동rollback·prune·Map 적재/예약 변경은 하지 않는다. 최종 배포·공식job·Map full paging/304·기존자료 보존과 부모 실제종료는 실제 결과로 마감한다.
