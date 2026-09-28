# ODROID M1S 배포 파일

이 디렉터리는 과거 ODROID 배포 기록을 보관한다. 현재 운영 배포는
[`scripts/deploy-server14.sh`](../../scripts/deploy-server14.sh)만 사용하며, Docker/PostgreSQL은
`192.168.1.14`에서만 실행한다. 이 디렉터리의 legacy 배포 스크립트는 의도적으로 종료된다.

## 파일 설명

- [remote-deploy.sh](remote-deploy.sh)
  - legacy 경로 차단용 스크립트다. Docker 명령을 실행하지 않는다.
- [bootstrap-docker.sh](bootstrap-docker.sh)
  - Ubuntu 24.04 기준 Docker와 Compose plugin을 설치하는 1회성 스크립트다.
  - 실제 실행은 설치가 필요할 때만 한다.

## 로컬 설정 파일

- 루트의 [.env.odroid](../../.env.odroid)
  - 로컬에서는 배포 대상 IP, 사용자, 앱 디렉터리, 포트 같은 배포 연결 정보를 저장한다.
  - 운영 공공데이터 인증키의 기준 파일은 ODROID의 `/home/digitie/apps/parking-radar/.env.odroid`다.
  - 비밀번호는 저장하지 않는다.
  - 현재 ODROID 기준 API 공개 포트는 `18000`이다.
    - `8000` 포트는 Portainer가 사용 중이라 충돌을 피한다.
  - 외부 서비스 주소는 `https://pr.digitie.mywire.org/`이다.
  - 프론트는 기본적으로 `/api/backend`를 호출하고, Next.js 서버가 `BACKEND_INTERNAL_URL=http://backend:8000`으로 프록시한다.
  - 운영에서는 `ENABLE_API_DOCS=false`, 제한된 `CORS_ORIGINS_CSV`, 제한된 `TRUSTED_HOSTS_CSV`를 사용한다.

## 로컬 실행 스크립트

- [scripts/deploy-odroid.ps1](../../scripts/deploy-odroid.ps1)
  - legacy 경로 차단용으로 유지하며 실행하지 않는다.
- [scripts/odroid-status.ps1](../../scripts/odroid-status.ps1)
  - 배포 후 웹/API 상태와 최근 수집 상태를 요약해서 보여준다.

## 운영 호환성 메모

- 원격 서버의 Docker Compose 구현은 환경마다 다를 수 있다.
- `parking-radar` 배포 스크립트는 `docker compose`와 `docker-compose`를 모두 지원해야 한다.
- 원격 서버에서 `.env.odroid`를 먼저 로드하므로 Compose CLI의 `--env-file` 지원 유무에 의존하지 않는 구성을 유지한다.
- 배포 후 컨테이너는 서버에 저장된 `.env.odroid`의 `DATA_GO_KR_SERVICE_KEY`로 동작해야 한다.
- 과거 Compose 호환성 메모는 기록으로만 보존한다. 현재 배포 스크립트는 Compose를 내리지 않으며,
  운영 배포는 14번의 `scripts/deploy-server14.sh`만 사용한다.
- 백엔드가 healthy가 된 뒤 프론트를 올리는 순서를 사용해 초기 healthcheck 경합을 줄인다.
