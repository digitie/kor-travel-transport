# VWorld React 패키지 고정 정보

이 폴더의 tarball은 [`digitie/maplibre-vworld-react`](https://github.com/digitie/maplibre-vworld-react)
submodule의 `69abf9c21c0a00afda2f1b50e35cd3bd9dbf4663` revision에서 만들었다. source는
`third_party/maplibre-vworld-react`로 함께 고정하고, Docker는 아래 tarball만 설치한다.

| 파일 | SHA-256 |
| --- | --- |
| `vworld-map-core-1.0.0.tgz` | `6b407720141121168e43ac0611ce87938228df0d9977547c0fa23c135b83278f` |
| `vworld-map-web-1.0.0.tgz` | `b819ce1f0f05d703879e3216bbecc56eb4946196f185128d6531642b0535bd56` |

재생성할 때는 source revision을 먼저 확인하고 `npm run build` 뒤 각 workspace에 대해
`npm pack --workspace=vworld-map-core`와 `npm pack --workspace=vworld-map-web`을 실행한다.
새 tarball을 이 폴더에 놓은 뒤 `npm install --force --ignore-scripts`로 lockfile integrity를
갱신하고, clean Docker build를 통과시킨다.
