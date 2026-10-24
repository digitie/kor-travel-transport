# 공용 지도 UI 채택 후보 — 2026-10-24

## 변경

Map Feature 작업면을 `kor-travel-common@e79816afb3c19b1b1e2fc1486b809c2ee3d34d6e`에서
공용화했다([Common PR45](https://github.com/digitie/kor-travel-common/pull/45)).
Transport는 종류 아이콘·30px 필터·176px 검색/출처·PC 한 줄·Map 보기 탭·건수와 실제 좌표/줌·
지도 위 상세 패널을 같은 컴포넌트로 소비한다. 다중 출처/유종의 검색·해제는 보존한다.
사용자 6번의 좌표 안내·돌발 관측 안내·일부 표시 안내 문단을 삭제했다.

소비 산출물은 `kor-travel-ui-0.1.0-dev.7.tgz`, SHA256
`4445c694013bd19fb57d3655cfc25d86e99a6733d655524718be3bf769ba7422`다.
Map과 Weather도 같은 파일과 lock 무결성을 고정한다.

## 검증

- Transport WSL 타입 검사 및 기존225 테스트 PASS.
- Common clean WSL 내부 디스크 npm ci 후 UI54·타입·패키지 고지 PASS, SPDX138 오류0.
- Transport Chromium375/1440px: 30px/176px·PC 한 줄·실제 좌표·필터 선택·상세 absolute 배치·
  Escape/포커스 반환·가로 overflow2 PASS.
- Weather frontend250·종류 PostgreSQL12·375/1440px UI2 PASS를 확보했고 최종 보강을 별도 검증한다.
- Map 타입 검사 PASS. 전체395 중 mirror에 빠뜨린 Python enum 파일로3 실패가 있었고,
  동일 파일을 복사한 뒤 해당6 테스트 PASS. 나머지392 테스트는 최초 실행에서 PASS했다.
- James 최종 읽기 전용 리뷰 PASS. Popper의 Weather 강수 우선순위 지적은 소비자에서 보강한다.

NTFS의 worker 시작 timeout과 오래 실행한 개발 서버의 이전 모듈 캐시는 성공 근거에 포함하지 않는다.
최종 UI 확인은 동일 소스·고정 lock의 WSL 내부 디스크 격리 개발 서버에서 수행한다.

## 통합 경계

사용자는 다른 에이전트가 Transport 개선을 합쳐 빌드·배포한다고 지시했다.
이 작업은 배포용 빌드·운영 배포를 중단한 상태를 유지한다.
Weather의 새 종류 필터는 해당 API와 UI를 함께 반영해야 한다.
6~11번 후속 범위는 [이용 목적 개선 원장](../transport-user-journeys-2026-10-24.md)을 따른다.
