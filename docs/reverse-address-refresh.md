# 6개월 자동 주소 갱신과 Admin 수동 실행

정본 구현 계약은 [Common 구현 가이드](https://github.com/digitie/kor-travel-common/blob/agent/codex-reverse-address-refresh-20261018/docs/reverse-address-refresh.md)를 따른다.
기존 VWorld 우선·Kakao 보조를 유지하며 Geo API나 데이터 토큰에는 의존하지 않는다.

환경변수: VWORLD_API_KEY, KAKAO_REST_API_KEY,
ADDRESS_REFRESH_AUTO_ENABLED(기본 true), ADDRESS_REFRESH_BATCH_SIZE(기본 50),
ADDRESS_REFRESH_TIMEOUT_SECONDS(기본 5).
대상은 좌표가 있는 FuelStation·BusTerminalReference·FerryPort·RailStationReference·
RestAreaReference다. 좌표 없는 원천 행은 역지오코딩 대상이 아니며 기존 정방향 좌표
수집이 먼저 필요하다. 관리자 location_source와 원천 주소·좌표는 보존한다.
Admin 상태 API는 GET /v1/transport/admin/address-refresh다.
소비자 migration은 0025_reverse_addresses다.

Admin의 Dagster 운영 화면에서 전체 주소 수동 갱신을 누른다. 서버에서 고정한
address_refresh_job에 force=true를 예약하며, 큐 등록과 완료를 구별한다.
확인 주소는 별도 파생 결과로 표시하고 원천 주소를 덮어쓰지 않는다.
주소별 마지막 확인일부터 달력 6개월마다 갱신한다. 자동 due 검사는 10분 주기이나
대상이 없을 때 provider를 호출하거나 run을 생성하지 않는다.
실패는 마지막 정상 주소·확인일을 보존하고 재시도한다. 중단은 영속 커서로 재개한다.
자동 갱신을 꺼도 이미 시작한 수동 배치는 계속 이어 처리한다.
Daemon은 기존 중지 상태를 유지하며 이 변경이 운영을 임의로 재개하지 않는다.

## 검증 기록

현재 구현·검증 진행 중이다. 로컬 테스트 결과와 운영 적용은 구분한다.
운영 migration·실제 API 실호출·배포·외부 UI E2E는 아직 완료로 기록하지 않는다.
