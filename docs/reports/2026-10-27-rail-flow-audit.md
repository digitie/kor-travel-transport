# 철도 시간표 연결의 남은 문제

2026-10-27 코드 읽기 조사다. `3691a07ab5bca36060173294c7d02c7399b76e4c` 기준이며,
이번 조사에서 운영·API·provider 요청, 시험 실행과 기능 수정은 하지 않았다.
시간표 기능 전체가 없다는 판단과 현재 운영에서 실제 이용 흐름이 정상이라는 판단 모두 피한다.

## 이미 있는 조회 경로

- 일반철도: [시간표 화면](../../packages/kor-travel-transport-admin/frontend/components/general-rail-journey.tsx)의
  도시/차종 목록→도시별 역→출발·도착·날짜·차종 조회가
  [일반철도 API](../../backend/app/general_rail_routes.py)와 기존 `datagokr` SDK의
  `client.train.timetable_list()`로 이어진다. 성공 결과 저장·15분 캐시·KST 현재 이후 필터도 있다.
- 도시철도: [역 선택](../../packages/kor-travel-transport-admin/frontend/components/metro-journey.tsx)에서
  [시간표](../../packages/kor-travel-transport-admin/frontend/components/rail-timetables.tsx)와
  [저장 시간표 서비스](../../backend/app/services/rail_timetable.py)로 이어진다.
  공식 코드 연결·운행일 달력·요일별 저장본·48시간 신선도가 필요하며, UI 새로고침은 수집 실행이 아니다.
- [서울→부산89편 기록](2026-10-24-transport-user-journeys.md)은 당시 SDK→새 로컬 API→DB→브라우저의
  성공 증거다. 오늘의 운영 성공 증거로 대신하지 않는다.

## 재현할 두 연결 단절

1. **차가운 DB의 숨은 참조 준비 의존.** 일반철도 API는 도시 catalog가 없으면 정상 도시11의
   역 요청도422, 저장된 역이 없으면 `NAT010000`→`NAT014445` 시간표도404로 provider 전에 막는다.
   ID 검증 자체는 의도된 안전장치지만 외부 API에는 별도 준비 상태 계약이 없다.
   [기존 API 회귀](../../backend/tests/test_general_rail_api.py)는 catalog/stations를 먼저 호출해 이 경우를 덮지 않는다.
   검증을 지우지 말고, 제한된 참조 준비 또는 명시적 준비 상태 계약 중 실제 소비자가 쓸 수 있는 방식을 검증해야 한다.
   provider 전체 조회를 무제한 자동 실행하는 해결로 바꾸지 않는다.
2. **지도 역 선택이 시간표 입력에 전달되지 않음.**
   [역 안내](../../packages/kor-travel-transport-admin/frontend/components/general-rail-guide.tsx)의 시간표 링크는
   앵커 이동이고 Journey의 출발·도착 상태와 분리돼 있다. 지역/역 재검색을 줄이는 연결이 필요하다.
   코레일 공개 `station_sequence/station_code`와 TAGO `station_id`는 다른 식별자이므로 이름만으로 자동 확정하지 않는다.

## 다음 검증과 완료 범위

새 테스트 DB에서 선행 호출 없는 도시11 역 요청·서울/부산 시간표를 provider fixture와 함께 재현하고,
동일 ID의 준비된 상태·잘못된 ID·권한/일시 장애와 구분한다. 도시철도는 실제 저장본의 연결·달력·요일·신선도를
읽기 전용으로 나눠 확인해야 한다. 현재 조사만으로 T-RAIL-01/02/03을 완료로 바꾸지 않는다.

[일반철도 live spec](../../packages/kor-travel-transport-admin/frontend/e2e/general-rail.live.spec.ts)은
현재 존재하지 않는 `철도 역 검색 결과` 선택자를 먼저 최신 UI에 맞춰야 한다.
이 검사가 로컬 QA API 중계라는 점도 실제 공개 운영 API/UI 검증과 분리한다.
