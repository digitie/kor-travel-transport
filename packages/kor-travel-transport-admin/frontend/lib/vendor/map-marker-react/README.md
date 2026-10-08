# vendored `@kor-travel-map/map-marker-react`

이 폴더의 `*.ts`는 [`digitie/kor-travel-map`](https://github.com/digitie/kor-travel-map)의
`packages/map-marker-react/src/`를 **수정 없이** 복사한 것이다. transport 교통 지도가 Map과
같은 마커(24px 원형 배지 + maki 글리프 + P-01~P-16 팔레트)를 쓰기 위해서다.

| 항목 | 값 |
| --- | --- |
| 원본 저장소 | `digitie/kor-travel-map` |
| 원본 경로 | `packages/map-marker-react/src/{index,marker,palette,maki,maki.test}.ts` |
| 원본 commit | `bcbd14c24f0cdd49533f3a64ee87cb2c7e69d1a2` (Map PR #1311 머지 commit, 2026-10-09 — `roadblock`·`warning` 글리프 추가) |
| 라이선스 | MIT (`packages/map-marker-react/package.json`의 `license`, Map ADR-029). 전문은 같은 폴더 `LICENSE` |
| 저작권 | Copyright (c) 2026 digitie (패키지 `author`) |

라이선스 주의: Map 저장소 루트는 GPL-3.0이지만 이 패키지는 PinVi(비공개)에서도 쓰도록
`package.json`에 MIT를 따로 선언했다(Map ADR-029). 원본 패키지 폴더에는 별도 LICENSE 파일이 없어
MIT 조건(저작권 표시와 허가 문구 동봉)을 지키려고 `LICENSE`를 이 폴더에 두었다. transport는 GPL-3.0이라
MIT 코드를 포함해도 문제가 없다.

## 왜 vendoring인가

- Map ADR-043에 따라 이 패키지는 npm registry에 게시하지 않는다. transport가 쓰려면
  workspace 공유(다른 저장소라 불가), git dependency, 또는 복사 중 하나다.
- 패키지는 `exports`가 TypeScript 원본(`./src/index.ts`)을 가리키고 `zod`를 peer로
  요구한다(실제로는 쓰지 않는다). git dependency로 받으면 Next `transpilePackages`와 불필요한
  peer 설치가 따라온다. 의존성 없는 순수 DOM factory + lookup table 297줄이라 복사가 가장 단순하다.
- Map HTTP API에 런타임으로 의존하지 않는다. 이 코드는 브라우저에서 DOM 요소만 만든다.

## 갱신 규칙

- 이 폴더의 파일을 직접 고치지 않는다. Map 쪽을 고친 뒤 같은 경로에서 다시 복사하고 위 표의
  commit을 바꾼다.
- transport 고유의 매핑(장소 종류 → maki 이름·팔레트 코드, 가격 라벨)은
  `lib/place-marker-style.ts`에 둔다.
