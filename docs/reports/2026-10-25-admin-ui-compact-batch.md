# 2026-10-25 — 관리자 UI 첫 번째 작은 수정 묶음

## 범위

[조사 기반 설계](../design/2026-10-25-mobility-improvements.md)의 작은 UI 부분을 먼저 적용한다.
기존 관리자 메뉴·API·수집·Common 패키지 버전은 유지한다. PR은
[Transport #131](https://github.com/digitie/kor-travel-transport/pull/131)이다.

- 앱의 navy 팔레트와 공용 `--kt-*` 의미 토큰을 연결했다. 밝은/어두운 표면·선택·초점·상태·팝업의 색을 함께 맞춘다.
  다크 값은 기존 Weather navy 프로필을 따른다. 의미가 있는 주유소/교통 마커 색은 보존한다.
- 삽입 지도 바깥의 테두리를 제거하고 지도/목록의 같은 stage 한 곳에만 테두리를 둔다.
  `70dvh/64dvh`와 기존 캔버스 높이는 이번에 변경하지 않는다.
- 유가 지도의 큰 하단 통계 카드를 상부 요약으로 옮겼다. 유종을 선택하면 해당 서버 집계의 평균·최저·전체 주유소 수·시각을 표시한다.
  나머지 통계·최저가 주유소 주소 링크·집계 설명은 제목 옆 `i`로 연다. 목록 보기에서는 이 요약을 표시하지 않는다.
- 요약과 선택 상세는 같은 stage 안에서 내용 높이대로 쌓는다. 요약의 줄바꿈으로 상세가 덮이지 않고,
  짧은 상세가 남은 지도 높이만큼 불필요하게 커지지 않게 한다. 지도 자체의 크기는 줄이지 않는다.
- 주유소 상세의 주소/출처는 이름 있는 아이콘 팝업으로 모았다. 주소의 같은 지도 이동, 전화,
  유종별 가격·관측 시각·실패/갱신 지연 경고는 유지한다. 상세 header/footer의 출처 반복을 없앴다.
- 유가 통계는 실제 가격·최근 7일 범주 평균 추이·전체 범주 비교를 먼저 보여준다. 기존 차량 운영비 가정 계산은 하단에서 펼친다.

## 보존한 데이터 의미

지도 요약의 수치와 모집단은 기존 `include_fuel_statistics=true` 응답을 그대로 쓴다.
묶음 마커의 수나 클라이언트가 받은 일부 장소로 재계산하지 않는다. 유종 전환은 같은 서버 응답 안에서 선택하며,
재조회 중에는 이전 범위의 가격을 숨기고 조회 중/실패/빈 통계를 구분한다. 통계 반영 대기는 값 가까이에 남긴다.
최근 7일 그래프는 기존 지역·범주 평균이며 **개별 주유소의 가격 이력이 아니다**.

## 로컬 검증

Windows 작업면을 WSL2 Ubuntu-26.04의 `/home/digitie/dev/transport-compact-ui-20261025`에 복사해
Linux Node/npm으로 실행했다. `/mnt/c`의 느린 의존성 설치만 소유 PID를 확인해 중단하고 Linux 파일시스템에서 새로 설치했다.

| 검증 | 결과와 경계 |
|---|---|
| `npm run type-check` | 통과 |
| `npm run test` | 35파일·250개 통과. 유종 선택·모집단 유지·재조회/실패 회귀 포함 |
| `npm run lint` | 통과 |
| Playwright 유가 통계/지도 fixture | Chromium 8개·Firefox 8개 통과 |
| 화면 크기·주요 동작 | 320/375/1440px 지도, 390/1440px 통계. 유종·범주 변경, 가정 계산 접기/펼치기, 목록↔지도, 주소 이동, 팝업 Escape·초점 반환, 가로 넘침·요약/상세 비겹침 확인 |
| 프로젝트 톤 | 밝은/어두운 KT 의미 토큰 일치와 실제 검색 Input의 최종 배경색 확인. CSS 색 전환 완료 후 캡처 |
| 실제 VWorld 타일·운영 API | 미검증. 이 실행은 키 없는 지도 fallback과 주입한 API fixture의 UI 검증이다 |

QA 서버는 후보의 `next.config.ts` 원본으로 `next dev --hostname 127.0.0.1 --port 12351`을 실행한다.
초기 `0.0.0.0` 실행의 dev resource origin 차단은 loopback 호스트 일치로 해소했다.
중간 QA 복제에만 두었던 `allowedDevOrigins` 보완은 최종 검증 전에 제거했으며 저장소에는 추가하지 않았다.
Firefox 실행은 기본 config의 live 타일 제한을 확장한 **QA 복제 전용** `playwright.compact.config.ts`를 사용했다.
주입한 API fixture를 실제 타일·운영 데이터 정상의 증거로 세지 않는다.

스크린샷은 작업면의 `packages/kor-travel-transport-admin/frontend/test-results/compact-batch/`에 있으며,
`compact-fuel-{chromium|firefox}-{320|375|1440}-{light|dark}.png`와 JSON 결과를 보존했다. 생성 파일은 커밋하지 않는다.
운영 이미지 빌드·배포는 사용자 지시에 따라 실행하지 않았다. Docker 2차 검증·CI·독립 리뷰와 최종 SHA는
[PR Checks](https://github.com/digitie/kor-travel-transport/pull/131/checks) 및 PR의 최종 검토 기록을 정본으로 삼는다.

## 다음 묶음

이번 완료는 T-MAP-01의 색상/테두리, T-FUEL-01의 기존 데이터 기반 요약/메타, T-FUEL-04의 배치 일부다.
Common의 실제 가용 높이 계약과 모든 지도 소비자의 수용은 C-MAP-01/T-MAP-01에 남긴다.
지도 접근 위치·모바일 필터 접기, 철도 실제 시간표, 주차 수집/분석 단절, 개별 주유소 7일 이력·브랜드 자산·선호 조건/API는
이번 작은 수정으로 해결됐다고 세지 않는다. [후속 작업](../tasks.md)을 유지한다.
