# Transport 관리 화면 디자인

## 기준과 범위

사용자 요청에 따라 로컬 kor-travel-map의 feature 지도/목록/선택 inspector와
kor-travel-weather의 운영 화면을 기준으로 한다. 새 테마를 만들지 않는다.
교통 이용자가 장소와 운항을 비교하는 실용적인 화면이며 운영 상태는 별도 메뉴로 분리한다.
기존 parking-radar의 화면과 스타일은 변경하지 않는다.

## 공통 구조

- 장르: modern-minimal, 앱 구조: Workbench, 탐색: N3 사이드 레일.
- 검색·필터 → 지도/목록 전환 → 선택 항목 inspector 순서다.
- 모바일에서는 inspector를 검색 바로 아래로 배치하고 목록보다 먼저 읽는다.
- 기존 transport의 청록색, 한글 sans 글꼴을 유지하고 weather의 얇은 경계/6px 입력/8px 패널을 따른다.
- 의미 없는 장식·진입 애니메이션·가짜 통계는 사용하지 않는다.
- 가격에는 유종·단위·관측 시각을, 시간표에는 출발/도착·운항일·배/등급·요금을 붙인다.
- 좌표 없음, 시간표 미수집, 수집 완료지만 운항 없음은 각각 다른 상태다.
- 지도 축척 막대 최대 100px가 30km 이하이면 클러스터를 해제한다.
- 검색과 선택만으로 외부 provider를 호출하지 않는다. 저장 데이터 조회와 명시적 보충을 분리한다.

## 토큰·상태

app/tokens.css는 기존 색상의 별칭과 간격·폰트·형태를 제공한다.
포커스 표시, 선택 상태, 로딩, 빈 결과, 오류, 재시도, disabled 설명을 제공한다.
320/375/414/768px와 데스크톱에서 검증한다. 장식 모션은 없으며 reduced-motion을 따른다.

## 실제 화면 검증

Hallmark의 정보 위계·빈 상태 구분·키보드 포커스·반응형 기준을 적용했다.
2026-09-27 n150에서 실제 유가 마커, 소청도 운항 카드, 공항 저장 주차 현황,
고속도로 돌발·소통, 16개 수집 영역을 확인했다. 긴 장소명의 select가 상세 패널을
밀어내는 문제는 실제 화면에서 발견해 최소 폭과 줄바꿈으로 고쳤다. 가격을
overflow로 숨기지 않고 패널 자체의 가로 넘침을 1440/375px에서 검사한다.
사용자가 기존 map/weather 복제를 요청했으므로 새 브랜드·레이아웃 변주는 적용하지 않는다.

## 다른 프로젝트로 옮길 때의 토큰

CSS 정본은 `app/tokens.css`이며 기존 transport 색상을 별칭으로 참조한다.
다음은 선택적 복사 예시이며 현재 앱에 Tailwind나 shadcn을 설치하지 않는다.

```css
/* CSS 정본 역할의 별칭 */
:root { --color-paper: var(--paper); --color-ink: var(--ink); --color-accent: var(--accent); }
/* Tailwind v4를 사용하는 소비 앱 */
@theme inline { --color-background: var(--color-paper); --color-foreground: var(--color-ink); --color-primary: var(--color-accent); --spacing-control: .75rem; }
```

```json
{
  "color": {
    "paper": { "$type": "color", "$value": "#f7f7f2" },
    "ink": { "$type": "color", "$value": "#182022" },
    "accent": { "$type": "color", "$value": "#0f766e" }
  },
  "space": { "control": { "$type": "dimension", "$value": "0.75rem" } }
}
```

```css
/* 완전한 CSS 색상 값을 소비하는 shadcn 역할 매핑 */
:root { --background: var(--color-paper); --foreground: var(--color-ink); --primary: var(--color-accent); --primary-foreground: var(--color-accent-ink); --ring: var(--color-focus); --radius: 6px; }
```
