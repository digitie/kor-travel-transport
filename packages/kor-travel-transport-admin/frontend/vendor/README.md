# 고정 패키지 정보

## Firefox 타일 protocol 수정 (2026-10-24)

현재 web은 `maplibre-vworld-react@3c09359fa3dea4f65ec14b9db3814cfd410bc104`의
`vworld-map-web-1.0.1.tgz`다. SHA-256:
`f3686f762938cd4489ab66cbe5188a47ba89253f0adb18d0f0acf526206ccf43`.
비표준 scheme을 파싱 전에 HTTPS로 바꾸며 내부 fallback 인자는 실제 요청에서 제거한다.
core와 아래 과거 패키지는 그대로 보존한다. [검증 기록](../../../../docs/reports/2026-10-24-firefox-vworld-tiles.md).

## VWorld React 패키지 고정 정보 (2026-10-09 복원)

소유자 결정(2026-10-09): 교통 지도는 [`digitie/maplibre-vworld-react`](https://github.com/digitie/maplibre-vworld-react)
위에 만든다. #70(2026-10-08)이 걷었던 두 tarball을 #70 이전과 같은 byte로 되살렸다. 라이브러리는 npm에
발행하지 않으며(라이브러리 README "설치" — tarball pin 또는 submodule/vendoring), source는
`third_party/maplibre-vworld-react` submodule로 함께 고정한다. Docker는 아래 tarball만 설치한다.

tarball은 submodule PR #29 병합 `fb754755871ca8318907327c9a7d096dd96b1278`과 같은 web 소스에서 만들었다
(core는 `69abf9c` 그대로다). web dist에는 VWorld 제공 영역 밖 `200 application/xml` ExceptionReport를 대체 이미지로
바꾸는 #28 수정과 최초 묶음 마커 누락을 고친 #29 수정이 들어 있다. `fb75475`는 2026-10-09 현재 라이브러리
`origin/main` HEAD다.

| 파일 | SHA-256 |
| --- | --- |
| `vworld-map-core-1.0.0.tgz` | `6b407720141121168e43ac0611ce87938228df0d9977547c0fa23c135b83278f` |
| `vworld-map-web-1.0.0.tgz` | `88af30c972ab1b79954a57ceb8b2d79cd17895267e0382a4645a009f1a5c9767` |

재생성할 때는 source revision을 먼저 확인하고 `npm run build` 뒤 각 workspace에 대해
`npm pack --workspace=vworld-map-core`와 `npm pack --workspace=vworld-map-web`을 실행한다.
새 tarball을 이 폴더에 놓은 뒤 `npm install --force --ignore-scripts`로 lockfile integrity를
갱신하고, clean Docker build를 통과시킨다.

마커 겉모양은 #70의 Map 공용 마커 패키지 소스(`lib/vendor/map-marker-react/`, MIT)를 그대로 쓴다.


## 공용 UI·토큰 후보 고정 (2026-10-15)

UI는 Common `091d4fe1dda8eacf43b453ad39b4f2e42e9e80fc`에서 `npm pack`으로 만들었다.
UI 소스는 main `efcd671207d7f9e2fb01251bab6854a8d543279a`와 동일하다.
UI는 `0.1.0-dev.6`, tokens는 기존 `9da1889`의 변경 없는 `0.1.0`이며 정식 registry 배포가 아니다.
실행 검색·상태 필터·50행 페이지·상세를 공유하며 인증과 API는 소비 앱이 소유한다.
각 tarball은 GPL-3.0-or-later `LICENSE`·`NOTICE`·`THIRD_PARTY_NOTICES.md`를 포함한다.
Python 복구 코어는 `backend/pyproject.toml`과 `backend/uv.lock`에서 common
`430a9e9cd5429204579792b1d4f8e399366dcb2f`로 별도 고정한다. 위 UI tarball의 source commit과 구분한다.

| 파일 | SHA-256 |
| --- | --- |
| `kor-travel-tokens-0.1.0.tgz` | `22b7613085e55885987ce05720a178b65ac649b097763db650b8c7b8b4acaa84` |
| `kor-travel-ui-0.1.0-dev.6.tgz` | `e4945d01d9eb89ed505a95b551899fd0ecf41be66c9ee6b76246701350447e6d` |

## 공용 지도 작업면 후보 (2026-10-24)

Common source: e79816afb3c19b1b1e2fc1486b809c2ee3d34d6e. UI dev.7은 지도 종류·필터·탭·좌표/줌·오버레이를 추가한다. kor-travel-ui-0.1.0-dev.7.tgz의 SHA256은 4445c694013bd19fb57d3655cfc25d86e99a6733d655524718be3bf769ba7422다. Map/Weather와 동일한 산출물이며 이전 dev.6 후보를 삭제하지 않는다. [검증과 통합 경계](../../../../docs/reports/2026-10-24-shared-map-ui.md).

UI dev.8은 Common `a74ac808752fd6d6062e529909fd0dd656724f08`의 추가 작업면·모바일 필터 접기·상세 슬롯·명시 확장 계약을 소비한다.
`kor-travel-ui-0.1.0-dev.8.tgz` SHA256은 `71d9f6ce8c178e3c66a47593a70a7fd9274938587ef9d96c1c7023673370059f`이다.
고정 Git archive에서 재생성해 원본 파일 모드를 정규화했다. 초기 후보의 제한/보완과 소비자 검증은 [작업 기록](../../../../docs/reports/2026-10-25-map-workspace-layout.md)에 남긴다.
이전 후보는 보존한다. 패키지 자체 빌드와 운영 이미지 빌드를 구분하며 이 작업은 운영 빌드·배포를 수행하지 않는다.
