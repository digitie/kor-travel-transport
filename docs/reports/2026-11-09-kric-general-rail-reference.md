# KRIC 일반철도·KTX 역 보강 및 서비스 복구

## 최종 실제 수용

KRIC 일반철도323행·KTX74행을 공식 연결 식별자로 합친358건을 운영 DB에 저장했다.
공식 c56323f9-d496-49ac-8360-31eded6b8a33과 앱8603이 SUCCESS/success이며,
`kric-general` head339a214b의 complete397행/358member·error없음을 검산했다.
기존 도시철도1108행의 지문 f859b24b55cfa18f24880747a6d10d32와 head76bbe2ab는 같다.
실제 Map n150 peer에서1466건(1000/466)·고유identity1466·source_status ok·조건부304를 확인했다.
전주0045·순천0051·익산0030·안동0526의 DB/API 좌표가 같다. 코레일 코드를 KRIC 도시철도 코드로 대입하지 않았다.
신규358건 중 좌표198건, 미제공160건이며 기존13건까지 전체null173건이다.
이는 source별 기준정보 수량이며 서로 다른 source의 물리적 동일 역을 이름으로 합친 수량이 아니다.

세 서비스와 공유18개 컨테이너 복구·Manager3개 healthy·보호된 키/환경·PG18/schema0041·원20상태,
신규API3123a377/CS5d8a50fc와 기존16CID/이미지/마운트 보존을 수용했다.
모든 빌드/배포/제출/우선순위 부모의 실제 첫Invocation 종료·Main0·CG부재를 확인했다.
Native job의 공식SUCCESS와 저장을 수용했으며 별도 run-health RPC 미지원/접근 실패는 그대로 보존했다.
자식 종료가 불명확한 것을 이유로 다른 정상worker를 중단하지 않았다.
최종 원장 `transport-kric-general-20261109/final-acceptance.json` SHA fc65259987e37a0f5a1179497effceb466b90168ef21acafd1d3958769b39ecc.
Map 적재·주간 예약은 담당 후속이며 이번 작업에서 변경하지 않았다. 백업/복원은 사용자 선택으로 생략했다.


최신 사용자 지시로 미배포 TAGO 후보를 KRIC 기준으로 대체한다. KRIC 공개 일반323행·KTX74행의 모든 페이지를 검산하고 공식 상세 링크의 코레일 stationSeq로358역을 식별한다. 좌표198역이며 전주·순천·익산·안동은 공식 연결 좌표가 있다. 미제공160역은 추정하지 않는다.

`python-kric-api`의 KricGeneralStationClient가 요청·파싱·페이지/총수·연결 검증을 소유한다. Transport는 typed 결과를 `kric_general_portal` source와 `kric-general` head로48시간마다 원자 게시한다. 도시철도 `nationwide` head/행/코드와 기존 cursor를 보존하고 새로운 source를 T3 rail export에 합친다. 일반철도 권역 라벨은 열차 운행 노선·순서가 아니다. station_number의 공식 코레일 코드와 KRIC 도시철도 station_code는 별개다.

제공자 WSL/Docker Python3.12 각각291개, mypy12파일과 실제 공개 조회를 통과했다. 소비자의 원자 실패·기존cursor·NULL/좌표·소유권 terminal/회수 검증과 운영 수용은 정본 plan.json에 기록한다. migration·키 추가·UI 변경은 없다.

04:45UTC Docker 재시작 뒤 공유 DB·Dagster·Weather/Transport/Geo 등 기존18개 컨테이너 중지가 관측됐다. 원인·주체는 미확인이다. 사용자는 새 이미지 적용 뒤 서비스 복구를 명시했다. 중지된 정확 기존CID/image/환경/마운트를 동결하고 Transport API/CS만 새 이미지를 적용한 뒤 기존 DB/스토리지→앱→공용Dagster 순서로 복구한다. 과거 one-shot/init/migrate는 시작하지 않는다. 원 두 TAGO 빌드 실패·미배포/미수집 이력은 보존한다.

백업·복원은 사용자 선택으로 생략하며 자동rollback·prune·Map 적재/예약 변경은 하지 않는다. 최종 배포·공식job·Map full paging/304·기존자료 보존과 부모 실제종료는 실제 결과로 마감한다.

## 실제 서비스 복구 완료

API3123a377·수집기5d8a50fc에 제품36dd849를 반영했다. 두 역할은 기존 의존성 집합을 그대로 보존하며 provider c006c8b를 소비한다. PG18/schema0041·원래 Transport20 일정·키/다른 환경·기존 도시철도1108행의 지문 f859b24b55cfa18f24880747a6d10d32와 head76bbe2ab를 보존했다. 기존16개 역할은 CID·이미지·환경·마운트가 같다.

중지됐던18개 컨테이너를 복구했으며 Weather/Geo/Transport 모두 Manager healthy다. Transport 웹/관리자와 Weather/Geo 로그인 HTML은200이다. Weather의 비HTML 무인증 요청401은 기존 인증 경계다. Geo에 수동 가정한 /health404는 실제 지정 probe와 다르며 지정된 native probe는0으로 통과했다.

첫KRIC빌드는 Docker API 자식0 뒤 SDK의 CRLF/LF byte 차이를 검사에서 거절했다. 동일 API 이미지3123a377과 별도 R2의 CS 빌드를 native 검증했고, 줄바꿈을 정규화한 기존 SDK의 나머지 구현·배포 package/version 집합은 같다. 첫복구는 새이미지·기존15역할 시작 뒤 실제 Dagster 등록명을 잘못 가정해 실패했다. 첫 부모1/모든자식종료/CG부재를 보존하고, 실제 kortravelweather_dagster.definitions·kortravelgeo_dagster.definitions·kor-travel-transport를 고정한 R2에서 재생성 없이 남은3역할과 metadata만 마감했다. R2 첫 Invocation245a419f08174abe967907b28b1b455e는 done/Main0/CG부재다.

서비스 수용 원장은 service-recovery-acceptance.json SHA3162bfa06091914aa6cae1f67a396c37265e7869d6ba6d0b2b05e76486f65fa7이다. 공식 rail_reference_collection_job c56323f9-d496-49ac-8360-31eded6b8a33 한 건을 기존 native tag로 제출했다. 제출부모0과 job 완료를 구분하며 당시 정기 수집 뒤 QUEUED였으며 최종 저장·Map 수용은 위 정산이 우선한다.

## 동시 중단의 직접 원인 추가 관측

후속 journald 판독에서 /usr/bin/dockerd PID1640이04:45:32UTC에 `runtime error: invalid memory address or nil pointer dereference`로 panic한 것을 확인했다. 04:45:33 main process 종료·실패,04:45:35 systemd 재시작 예약·기동,04:46:08 기동 완료가 이어졌다. 세 앱의 동시 중지는 정상 배포 상태가 아니었다. panic을 촉발한 구체적인 내부 경로·명령은 아직 확정하지 않았다. Docker 업그레이드나 재시작을 추가로 실행하지 않았다. 원문은 키/argv 없이 daemon-fatal-process.json의 분류·프로세스·시각만 보존했다.

## 대기1건 우선순위의 명시 승인

사용자가 “이 대기 건만 우선 실행”을 선택했다. 정상G→TransportR에서 기존 c56323f9의 `dagster/priority`만0→10으로 변경하고 나머지 태그·run ID·기존 worker·공용 동시 실행5·reference 그룹1을 보존했다. native `DagsterInstance.add_run_tags` 한 번의 부모 first52c6d824a0f541a381f7a56fc11f16fb는 done/Main0/CG부재다. 실행 중인 같은 그룹의 KRIC 시간표6bc835b6은 자연 종료를 기다린다. 이 승인은 추가수집·다른run 취소·한도 우회가 아니다.
