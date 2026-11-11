# React Doctor 전체 warning gate 진단 — 2026-11-11

명령은 각 frontend의 `npm run doctor`다. 실제0.9.22의 `--scope full --blocking warning`을 사용하며,
아래 경고가 남아 gate는 실패한다. 진단을 숨기는 baseline이나 복잡도 규칙 해제는 추가하지 않았다.
관리자 `public/maplibre/**`만 설치된 maplibre-gl에서 복사한 제3자 생성물이므로 검사 대상에서 제외한다.
소비자 원본과 공통 추출 코드의 검사를 계속 수행한다. 이 문서는 완료·면제 승인 기록이 아니다.

## 공개 frontend

오류 0개, 경고 6개.

| 경로:행 | 규칙 | 진단 |
| --- | --- | --- |
| `src/app/api/backend/[...path]/route.ts:370` | `untrusted-redirect-following` | 서버 fetch의 redirect 처리 진단. 실제 redirect:manual·허용 경로 및 회귀 검증과 대조할 항목이다. |
| `src/components/fee-calculator.tsx:32` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `src/components/history-chart.tsx:231` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `src/components/pages/current-status-view.tsx:111` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `src/components/pages/history-view.tsx:44` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `src/lib/dashboard-context.tsx:132` | `no-loading-flag-reset-outside-finally` | loading 해제 경로 진단. 취소/요청 정체를 검사하는 실제 finally 경계와 대조해야 한다. |

## 관리자 frontend

오류 0개, 경고 48개.

| 경로:행 | 규칙 | 진단 |
| --- | --- | --- |
| `app/api-test/page.tsx:11` | `no-fetch-response-used-without-status-check` | API 점검 화면이 HTTP 상태와 오류 본문을 의도적으로 표시하는지 확인해야 한다. |
| `components/airport-details.tsx:21` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/airport-details.tsx:57` | `no-loading-flag-reset-outside-finally` | loading 해제 경로 진단. 취소/요청 정체를 검사하는 실제 finally 경계와 대조해야 한다. |
| `components/airport-parking.tsx:26` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/bus-journey.tsx:15` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/bus-journey.tsx:34` | `no-pass-live-state-to-parent` | 자식의 effect가 부모 상태를 동기화하므로 상태 소유권 분리를 검토해야 한다. |
| `components/bus-journey.tsx:47` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/bus-journey.tsx:64` | `rerender-state-only-in-handlers` | 렌더에 직접 쓰지 않는 재시도 시각을 ref로 이전할 수 있는지 검토해야 한다. |
| `components/bus-journey.tsx:89` | `no-adjust-state-on-prop-change` | props 변경 뒤 effect의 상태 갱신이 추가 렌더를 만든다. 입력 정체와 취소 계약을 보존하며 개선해야 한다. |
| `components/bus-journey.tsx:89` | `no-adjust-state-on-prop-change` | props 변경 뒤 effect의 상태 갱신이 추가 렌더를 만든다. 입력 정체와 취소 계약을 보존하며 개선해야 한다. |
| `components/bus-journey.tsx:89` | `no-adjust-state-on-prop-change` | props 변경 뒤 effect의 상태 갱신이 추가 렌더를 만든다. 입력 정체와 취소 계약을 보존하며 개선해야 한다. |
| `components/bus-journey.tsx:112` | `no-loading-flag-reset-outside-finally` | loading 해제 경로 진단. 취소/요청 정체를 검사하는 실제 finally 경계와 대조해야 한다. |
| `components/collection-status.tsx:11` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/collection-status.tsx:18` | `no-set-state-after-await-in-effect` | 비동기 effect 취소 진단. 각 응답의 AbortSignal 검사와 cleanup을 대조해야 한다. |
| `components/dagster-operations.tsx:9` | `only-export-components` | Fast Refresh를 위해 비컴포넌트 export를 별도 모듈로 분리할지 검토해야 한다. |
| `components/flight-journey.tsx:22` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/fuel-station-history.tsx:70` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/fuel-statistics.tsx:78` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/fuel-statistics.tsx:110` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/fuel-statistics.tsx:164` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/general-rail-guide.tsx:17` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/general-rail-journey.tsx:40` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/highway-journey.tsx:17` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/highway-statistics.tsx:14` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/journey-controls.tsx:62` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/map-overlays.tsx:27` | `only-export-components` | Fast Refresh를 위해 비컴포넌트 export를 별도 모듈로 분리할지 검토해야 한다. |
| `components/map-overlays.tsx:33` | `only-export-components` | Fast Refresh를 위해 비컴포넌트 export를 별도 모듈로 분리할지 검토해야 한다. |
| `components/metro-journey.tsx:14` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/operations-home.tsx:31` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/operations-home.tsx:37` | `no-set-state-after-await-in-effect` | 비동기 effect 취소 진단. 각 응답의 AbortSignal 검사와 cleanup을 대조해야 한다. |
| `components/rail-station-mapping.tsx:22` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/rail-station-mapping.tsx:37` | `no-pass-live-state-to-parent` | 자식의 effect가 부모 상태를 동기화하므로 상태 소유권 분리를 검토해야 한다. |
| `components/rail-station-mapping.tsx:37` | `no-prop-callback-in-effect` | effect의 부모 콜백 호출을 입력/상태 소유권과 함께 정리해야 한다. |
| `components/rail-station-mapping.tsx:108` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/rail-station-mapping.tsx:209` | `no-loading-flag-reset-outside-finally` | loading 해제 경로 진단. 취소/요청 정체를 검사하는 실제 finally 경계와 대조해야 한다. |
| `components/rail-station-mapping.tsx:223` | `no-loading-flag-reset-outside-finally` | loading 해제 경로 진단. 취소/요청 정체를 검사하는 실제 finally 경계와 대조해야 한다. |
| `components/transport-dashboard.tsx:35` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/transport-dashboard.tsx:48` | `no-fetch-in-effect` | effect의 직접 fetch를 기존 조회 계층과 취소/캐시 정책으로 정리해야 한다. |
| `components/transport-dashboard.tsx:57` | `no-fetch-in-effect` | effect의 직접 fetch를 기존 조회 계층과 취소/캐시 정책으로 정리해야 한다. |
| `components/transport-map.test.tsx:17` | `no-array-index-as-key` | 지도 테스트 대역의 index key를 안정된 정체로 바꿔야 한다. |
| `components/transport-map.tsx:89` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/transport-map.tsx:89` | `no-giant-component` | 300행을 넘는 지도 컴포넌트의 책임 분리가 필요하다. |
| `components/transport-map.tsx:140` | `no-adjust-state-on-prop-change` | props 변경 뒤 effect의 상태 갱신이 추가 렌더를 만든다. 입력 정체와 취소 계약을 보존하며 개선해야 한다. |
| `components/transport-map.tsx:237` | `no-adjust-state-on-prop-change` | props 변경 뒤 effect의 상태 갱신이 추가 렌더를 만든다. 입력 정체와 취소 계약을 보존하며 개선해야 한다. |
| `components/transport-reference-list.tsx:12` | `only-export-components` | Fast Refresh를 위해 비컴포넌트 export를 별도 모듈로 분리할지 검토해야 한다. |
| `components/transport-reference-list.tsx:13` | `only-export-components` | Fast Refresh를 위해 비컴포넌트 export를 별도 모듈로 분리할지 검토해야 한다. |
| `components/transport-reference-list.tsx:20` | `no-high-complexity-react-function` | 큰 React 함수의 분기·중첩을 표현 부품/도메인 훅으로 분리해야 한다. |
| `components/transport-reference-list.tsx:55` | `js-set-map-lookups` | 반복문 내부 includes 조회를 Set으로 이전할 수 있다. |

## 검토 방향

큰 컴포넌트 분해 경고는 유지보수 부채로 남아 있다. UI 합성·취소·시각 정합성 테스트를 유지하면서
도메인별 훅/표현 부품으로 나누어야 한다. 렌더 중 상태 변경이나 baseline으로 숫자만 낮추지 않는다.

`finally` 안의 취소·요청 정체 검사와 `redirect: "manual"`을 재지적하는 항목은 실제 코드와 단위 검증을
대조해 오탐인지 독립 리뷰가 확인해야 한다. 검증 없이 일괄 비활성화하지 않았다.

공개 요약·요금 결과·분석 패널 분리, 인스턴스별 요금 상태의 입력 정체 비교, 안정된 목록 key,
날짜 키 고정·포맷터 재사용·실제 observer 정리 등 재현 가능한 개선은 반영했다.
