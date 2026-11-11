# React Doctor 개선·전체 warning gate — 2026-11-11

공개6·관리자48개 경고를 기존 baseline이라는 이유로 남기지 않고 도메인 코드에서 개선했다.
최신 실제 Doctor0.9.22 결과는 공개56파일·관리자198파일 모두 오류0/경고0,
`complete=true`, `skippedChecks=[]`다. 명령은 각 앱의 `npm run doctor`이며
`--scope full --blocking warning --yes --no-telemetry --no-supply-chain --no-parallel`을 사용한다.
공급망 원격 전송만 제외하고 React·유지보수 검사는 실행한다.
관리자 `public/maplibre/**`의 제3자 생성물 제외 외 광역 ignore나 baseline은 추가하지 않았다.

## 실제 코드 개선

- 공개 요금 계산의 선택·RHF 폼과 요청 정체·취소·Zustand 결과 수명을 나누고 입력 변경 뒤 늦은 견적을 버린다.
  과거 조회는 자료 요청·날짜 선택·달력·제스처·SVG 표현으로 나눴고 요약 지표는 순수 모델에서 계산한다.
- 버스 터미널 검색 모델을 부모가 소유해 목록 수를 같은 렌더에서 계산한다. 자식 effect의 부모 통지는 제거했다.
  요청 보호 시각은 ref, 시간표는 날짜·출발·도착 scope로 도출하여 날짜 전환 시 옛 결과·로딩을 숨기고 요청을 취소한다.
- 역 매핑의 초안을 부모가 소유하여 dirty를 서버 기준과 직접 비교한다. 자식 effect로 dirty를 되밀지 않는다.
  RHF의 실제 근거 입력과 Zod 검증, 저장·충돌·자동 미리보기 보호는 유지했다.
- 관리자 지도·공항·철도·도로·유가·수집 화면은 조회/선택 수명과 필터·상세·결과 표현을 의미 단위로 나눴다.
  비컴포넌트 export는 vworld-presentation/dagster-snapshot/reference-places 순수 모듈로 옮겼다.
- 지도 URL 카메라는 최초 상태에서 복원하고 겹침 팝업은 필터 정체로 도출한다. API 점검은 HTTP 실패 본문을
  명시적으로 처리하며 대시보드 직접 fetch는 기존 transportGet 계층과 AbortController를 사용한다.
- 수집/운영 요약의 두 조회는 독립적으로 먼저 표시하되 각 await 뒤 취소를 검사한다.
  처음 분리한 구현이 느린 Dagster를 기다리는 회귀를 새 테스트2건으로 재현하고 수정했다.
- 브라우저에서 상세 컴포넌트의 빈 React element가 모바일 검색을 가리는 회귀를 재현했다.
  버스/도시철도/일반철도/도로 호출부와 MapStage 경계에 원래의 ‘상세 없음은 undefined/null’ 계약을 복구했다.
  공통 소스나 CSS를 앱별로 우회하지 않았다.

## 좁은 오탐 예외

아래7개 위치에만 규칙 단위 `react-doctor-disable-next-line`과 근거 주석이 있다.
복잡도·상태 소유권·접근성 진단을 해제한 예외는 없다.

| 위치 | 근거 |
| --- | --- |
| 공개 backend proxy | 허용 경로 검증과 명시적 redirect:manual을 이미 사용한다. proxy19회귀를 유지한다. |
| 공개 dashboard-context | 실제 finally 안에서 현재 요청/마운트 여부를 검사한 뒤 loading을 해제한다. |
| 관리자 airport-details | 실제 finally의 AbortSignal 가드로 교체/취소된 요청의 loading 해제를 막는다. |
| 관리자 rail-station-mapping 2곳 | 저장/미리보기 finally에서 AbortSignal·요청 sequence를 검사한다. 자동 매핑20회귀를 유지한다. |
| 관리자 collection-status / operations-home | 각 중첩 async의 await 뒤 signal 가드와 cleanup abort가 있으나0.9.22가 공유 signal 경계를 추적하지 못한다. 새 독립 응답/취소 회귀2건을 추가했다. |

## 증거와 남은 통합 경계

로그는 저장소 `validation/transport-*`에 둔다. 공개 Doctor는 `transport-public-doctor-c6.json`,
관리자는 `transport-admin-doctor-overlay-fix.json`이 최신이다. 단위는 공개164/관리자356이며,
버스4개·독립 응답2개의 새 회귀와 기존 요금·과거조회·역 매핑·지도 포커스 회귀를 포함한다.
공개/관리자 각각 같은 현재 소스를 포함한 격리 Docker unit도164/356 통과했다.
관리자 최신 c6 이미지 Chromium은16개 통과했다. 공개 단독 앱도375/1440px 현재 표·요금·과거 차트/달력/초점4개를 통과했다.

Doctor 통과는 전체 릴리스 완료가 아니다. backend 전체 WSL/Docker는 아직 진행 중이다.
설치한 c6 원장과 새 canonical c7 원장이 달라 최신 canonical guard는 UI/tokens 해시에서 차단된다.
root/artifacts가 아직 c6이므로 섞어 설치하지 않는다. 부모 pack 이후 같은 파일로 재동기화해야 한다.
독립 Transport 리뷰2건·foundation 병합 뒤 원격CI·PRmerge·부모go와 실제 이미지 배포도 남는다.
