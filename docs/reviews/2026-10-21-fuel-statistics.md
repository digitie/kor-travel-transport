# 유가 통계 독립 리뷰와 검증

## 범위

PR #101의 초기 리뷰 후보는 `19f84e0`이다. James(UI/UX/접근성)와 Popper(Backend/PG/운영)가 독립 read-only 리뷰를 했다. 다른 리뷰어의 결과를 사전에 공유하지 않았고 운영·공유 테스트 DB 변경은 금지했다.

## 지적과 수정

- James P1: 범주 선택·비교표 버튼이 로딩 중 DOM에서 사라져 키보드 포커스가 유실됐다. 지연 응답 Playwright 테스트로 먼저 실패를 재현했다. 같은 범위·유종의 선택 UI·비교표를 유지하고 지표·추이만 로딩한다. 수정 후 범주 select와 표 버튼의 포커스 유지 검증이 통과했다.
- James P2: 기록이 없는 날짜도 같은 간격으로 그려 시간축이 왜곡됐다. 실제 KST 날짜 차이를 x좌표로 사용하고 결측 구간의 선을 끊었다. 1일/5일 간격과 선 개수 테스트가 통과했다.
- James P2: 원본 수집 성공·통계 발행 실패 시 지도에 통계 지연 안내가 없었다. 지도 DTO의 `fuel_statistics[].update_pending`을 추가하고 매 요청 원본 성공 시각과 비교한다. 캐시된 지표는 변경하지 않는다. UI와 API에서 반영 대기를 검증했다.
- Popper P2: 현재 집계 조회와 이력 조회 사이 새 발행이 커밋되면 당일 추이가 사라졌다. 두 읽기 사이 발행을 끼워 넣어 이력2건 중1건만 나오는 실패를 먼저 재현했다. 현재·선택 범주의 7일 이력을 단일 SQL snapshot으로 읽어 세대를 일치시켰다. SQLite와 PostgreSQL 회귀 테스트가 통과했다.

## 검증 상태

- 최종 `2c2474d` 전체 WSL/Docker backend 각각940 PASS·14 조건부 SKIP.
- 리뷰 수정 후 PostgreSQL 통계 API/보관/실패격리/발행 경합4 PASS.
- admin WSL/Docker 각각225 PASS, production build 통과.
- 실제 로컬 PG/API/BFF/로그인 UI1 + 격리 UI5 = 브라우저6 PASS. 390/1440px, 실패/재시도, 범주/유종, 포커스, 지도 전체 통계가 포함된다.
- VWorld 키가 없는 로컬 캡처는 실제 지도 카메라 동작 증거가 아니다. 운영 배포 후 `E2E_FUEL_MAP_CAMERA=true`로 실제 확대2회·키보드 이동·bbox 통계를 검증해 PASS했다.
- 최종 GitHub push/PR CI의 backend·frontend·transport-admin 6개가 모두 SUCCESS다. 자동 live-e2e 2개는 명시적 실행 대상이라 SKIP이며, 위 실제 브라우저 실행을 별도로 수행했다.
- James/Popper가 `2c2474d`를 독립 재리뷰해 기존 지적 해결 및 추가 P0/P1/P2 없음으로 확인했다. Popper는 독립 SQLite 발행/결측/경합/캐시 불변 검사도 통과했다.
- PR #101은 main/runtime `86398267fc32c8558f8fa2f2ae40310fd46e5c00`으로 머지·Odroid 배포했다. 현재 통계 초기화·원본 대조·운영 UI1 PASS·내부/공개 속도 실측을 완료했다. [운영 결과와 한계](../reports/2026-10-21-fuel-statistics-live.md).
