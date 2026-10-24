# 일부 목록 조회 상한 안내

PR127의 지도 공용 UI 전환 뒤 API가 일부 목록만 반환해도 사용자에게 상한을 확인할 수 있는 경로가 사라졌다. `truncated=true`가 있는 현재 선택 종류만 집계하고 목록 모드의 기존 건수 옆 `목록 일부 표시 안내` 버튼으로 종류별 조회 상한을 제공한다. 닫힌 상태에는 긴 문단을 출력하지 않는다.

지도 모드·완전 응답·embedded 목록에는 표시하지 않는다. 일반 목록 상한은 기존 `min(300, floor(900/선택 종류 수))`, 항구·터미널의 이름 검색 상한은 기존5000이다. API 요청·쿼리·생성 DTO·인증/쓰기 기능은 변경하지 않았다.

UI 회귀와 기존 관리자 단위·타입·린트 검증을 진행한다. exact CI·두 독립 적대 리뷰·최종 후보 실제 UI·공식 배포는 별도이며 아직 완료로 표시하지 않는다. 원본 작업 트리와 운영 파일은 수정하지 않는다.


## 최신 main PR126 통합

`fbdcd9853b2d3420b3d5e9d6cacef4a84702f5ff`의 ITS/일반철도·migration0034·SDK 의존성·OpenAPI/생성 타입을 그대로 통합했다. MapViewTabs의 추가 지도/목록 건수, controlled view, 상세 focus와 overlay 동작을 유지하고, 일부 목록의 기존 단일 건수도 `items + listFeatureCount`로 일치시켰다. 이 교차 동작의 DOM 회귀 1건을 추가했다.

frontend package/lock/vendor는 PR126 정본과 다시 대조했다. vworld-map-web1.0.1/core1.0.0/Commondev7의 실제 tarball SHA512가 lock과 일치하며 maplibre6.15.0을 유지한다. 관리자 전체 248건·타입·lint·production build, backend UI 계약 11건 PASS다. 통합 후 정확 CI·두 독립 리뷰·schema0034 운영 반영·새 이미지 실제 UI는 별도 수용한다. 이전3e4의 실제 UI r4는 worker 진단 및 통계 검사 실패로 전체 성공이 아니며, 최신 후보의 성공으로 이월하지 않는다.
