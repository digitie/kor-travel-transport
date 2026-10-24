# 기존 API 호환 UI 선행 배포

사용자가 ITS 작업과 병행해 순수 UI를 먼저 완료·배포하도록 지시했다. `codex/ui-first-release`는 공용 지도 UI 후보 `e84e66d`를 기반으로 UI만 선별한다. backend·DB·수집기·Dagster·gateway 변경은 없다.

## 호환 범위

운영 API는 `e01f8e9`다. 운영 홈, 공통 필터/보기 탭/좌표·줌/상세 오버레이, 모바일 접는 메뉴, 제목 옆 i 안내, 고속도로·유가 지표, 노선·역 검색과 큰 지도, 전화·주소·Dagster 링크, 공항 주차·이후 항공편을 적용한다. 버스는 이름 검색 전 무용한 기본 목록을 표시하지 않는다.

일반철도 새 API, 버스 저장 연결, 주차 outlook, ITS 선형 지도는 backend 후속과 함께 반영한다. 운영에 없는 API를 UI에서 호출하지 않는다. 철도 페이지는 현재 저장 역의 위치·연락처 검색을 제공하며 간선열차 시간표를 제공한다고 주장하지 않는다.

MapLibre 6 worker와 shared 파일은 Map 원본 복사 스크립트로 준비하고 runner의 public 복사까지 검증한다. 래스터 타일만 정상인 상태를 GeoJSON 성공으로 판단하지 않는다.

## 검증·배포 상태

WSL 단위233 PASS 및 typecheck PASS. 최종 lint·후보 build·Docker 단위·브라우저 반응형·CI·독립 두 리뷰와 운영 적용은 진행 중이다. 운영의 별도 사전 빌드가 release lock을 보유하고 있어 변경을 겹치지 않는다. 운영 대상은 Manager `transport=odroid`, 앱과 staging은 NVMe다.
