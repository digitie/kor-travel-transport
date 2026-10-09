# 고정 패키지 정보

## VWorld 지도 (2026-10-08 교체)

교통 지도는 더 이상 `digitie/maplibre-vworld-react`의 `vworld-map-core`·`vworld-map-web`
tarball을 쓰지 않는다. kor-travel-map과 같은 look-and-feel을 위해 Map의 in-repo VWorld style
builder(`lib/vworld-style.ts` 사본)와 MapLibre 셸(`components/vworld-map.tsx`), Map 공용 마커
패키지 소스(`lib/vendor/map-marker-react/`, MIT)를 쓴다. 두 tarball은 이 폴더에서 지웠다.
쓰지 않던 `third_party/maplibre-vworld-react` submodule도 지웠다(git 이력에만 남는다).


## 공용 UI·토큰 후보 고정 (2026-10-04)

common 후보 commit `9da1889`의 `npm run build` 뒤 `npm pack` 산출물이다.
UI는 `0.1.0-dev.2`, tokens는 변경 없는 `0.1.0`이며 정식 registry 배포가 아니다.
각 tarball은 GPL-3.0-or-later `LICENSE`·`NOTICE`·`THIRD_PARTY_NOTICES.md`를 포함한다.
Python 복구 코어는 `backend/pyproject.toml`과 `backend/uv.lock`에서 common
`430a9e9cd5429204579792b1d4f8e399366dcb2f`로 별도 고정한다. 위 UI tarball의 source commit과 구분한다.

| 파일 | SHA-256 |
| --- | --- |
| `kor-travel-tokens-0.1.0.tgz` | `22b7613085e55885987ce05720a178b65ac649b097763db650b8c7b8b4acaa84` |
| `kor-travel-ui-0.1.0-dev.2.tgz` | `5c7bb61dce3245bf175795c39a9310782557ce65948ddc161452faa7c0cfca4b` |
