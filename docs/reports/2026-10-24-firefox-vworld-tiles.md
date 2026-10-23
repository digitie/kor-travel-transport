# Firefox VWorld 타일 긴급 수정

## 원인과 변경

Firefox의 운영 교통 지도에서 실제 이미지 타일 수신 0건을 재현했다.
`maplibre-vworld-react`의 사용자 protocol handler가 `URL.protocol = "https:"`로
비표준 `vworld:` scheme을 바꾸려 했으나 URL 표준상 이 전환은 무시된다.
파싱 전에 scheme을 HTTPS로 바꾸도록 라이브러리 원본을 수정했다.
키·provider 경로·취소 signal·제공 영역 밖 XML 대체 동작은 보존한다.

소스는 `maplibre-vworld-react@3c09359fa3dea4f65ec14b9db3814cfd410bc104`,
소비 tarball은 `vworld-map-web-1.0.1.tgz`다. SHA-256은
`f3686f762938cd4489ab66cbe5188a47ba89253f0adb18d0f0acf526206ccf43`다.
동일 이름의 예전 tarball을 덮으면 npm 캐시·lock과 엇갈릴 수 있어 patch 버전을 올렸다.

## 검증과 운영 경계

- 라이브러리 URL 변환 회귀 2 PASS, 교통 지도 부품 15 PASS.
- WSL Firefox: 수정 전 운영 0타일로 FAIL, 수정 후 로컬 교통·유가 실제 이미지 수신·확대 1 PASS.
- James/Popper 독립 리뷰의 lock 불일치와 Firefox 설치 누락을 수정했고 확대 후 새 이미지 수신·렌더 완료까지 기다리도록 보강했다.
- 전체 관리자 단위·Docker 빌드/단위·운영 Firefox 재검증은 진행 중이다.
- 사용자는 이번 긴급 수정에 한해 현재 운영 호스트의 관리자 웹 컨테이너 교체를 명시 승인했다.
  API·수집기·DB·Dagster·gateway는 배포 대상이 아니다. 기존 UI 이미지는 복구용으로 보존한다.

공통 필터·배치·상세 오버레이 작업은 별도 브랜치에서 계속한다.
