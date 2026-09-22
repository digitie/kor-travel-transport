# VWorld React 패키지 고정 정보

이 폴더의 tarball은 [`digitie/maplibre-vworld-react`](https://github.com/digitie/maplibre-vworld-react)
submodule의 `cfdc64f5ced4bacae926f2a8fa3178779b42c4ad` revision에서 만들었다. source는
`third_party/maplibre-vworld-react`로 함께 고정하고, Docker는 아래 tarball만 설치한다.

| 파일 | SHA-256 |
| --- | --- |
| `vworld-map-core-1.0.0.tgz` | `29c3f325d417a0bbccc953ed526e54595ecb12048822cfaa4b4baed343c1a800` |
| `vworld-map-web-1.0.0.tgz` | `ef068e8ed5b5f5acce1244e0f9e39e8bcbd528858002ef962955b275d920695c` |

재생성할 때는 source revision을 먼저 확인하고 `npm run build` 뒤 각 workspace에 대해
`npm pack --workspace=vworld-map-core`와 `npm pack --workspace=vworld-map-web`을 실행한다.
새 tarball을 이 폴더에 놓은 뒤 `npm install --force --ignore-scripts`로 lockfile integrity를
갱신하고, clean Docker build를 통과시킨다.
