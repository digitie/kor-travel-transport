# 공통 UI 통합 기록

## 대상

관리자 `packages/kor-travel-transport-admin/frontend`와 공개 앱 `frontend`,
공유 `@kor-travel/parking-ui`의 표·프리미티브를 함께 이전한다.
기존 공통 LoginForm·AppMenu·DagsterOperations·map-controls 채택은 유지한다.
인증·세션·운영 API와 수집 정책은 변경하지 않는다.

## 구현

모든 데이터 표는 `@kor-travel/ui/virtual-table`의 VirtualTable을 사용한다.
작은 통계·요약 표는 semantic 경로로 렌더하며 서버/기존 순서를 유지한다.
기존 Base UI 구현은 공통 Radix 재export로 대체한다. 다중 필터는 공통
Popover·Checkbox·Input으로 조립하고 명시적인 칩 제거와 최대10개 제한을 유지한다.
자동 매핑 Dialog는 진행 중 닫힘 금지와 알림/트리거 포커스 복귀를 유지한다.
forceMount한 탭은 inactive 상태를 숨겨 이전 방문한 패널의 상태를 보존한다.

관리자 메뉴 열림은 인스턴스별 Zustand store, 역 매핑 근거는 RHF와 Zod로 관리한다.
공개/공유 요금 계산기 시간 입력은 RHF, 필수 입력 검증은 Zod,
요금 결과는 인스턴스별 Zustand store로 이전한다. API와 시각 의미는 보존한다.
Pretendard는 로컬 CSS에서 공급한다.

## 버전 및 검증 정책

버전은 부모 version-targets.json exact를 사용한다. TypeScript는 부모가 확인한
openapi-typescript 및 typescript-eslint peer 호환성 때문에 5.9.3을 유지한다.
Node 실행환경22에 맞춰 @types/node22.20.5를 유지한다.
common UI0.2.0/tokens0.1.1과 지도 core1.0.0/web1.0.3은 부모가 만든 동일tgz를
소비한다. 지도 web은 GitHub 최신main9c46c57과 ES2022 컴파일 수정 후보를 사용한다.
`check:dependencies`를 CI의 npm ci 직후 필수 실행한다.
검증 결과와 미완 항목은 journal에 기록한다.

## 통합 후보 4 및 남은 게이트

2026-11-11 부모 후보4 UI/tokens와 원장을 양쪽에 복사해 명시 재설치했다.
`tokens/radix.css` bridge를 로컬 테마 앞에 추가했고 현재 사용하지 않는 구 vendor tgz는 제거했다.
기존 tgz 이력은 Git에서 확인한다. nested 공유 버전은 PostCSS·undici·Testing Library DOM까지 exact 정렬했다.
Doctor는 `--scope full --blocking warning` 실차단이며 아직 공개6/관리자48 경고로 실패한다.
공통 Tabs의 방향/활성 스타일과 MapTabPanel forceMount 비활성 표시 회귀도 부모 수정이 필요하다.
[검증과 배포 계획](reports/2026-11-11-common-ui-validation.md),
[Doctor 잔여 진단](reports/2026-11-11-react-doctor-findings.md)을 정본으로 삼는다.
이 후보는 최종 릴리스나 운영 배포 완료가 아니다.
