# 백업·복원

## 계약

모든 경로는 `x-transport-admin-token: $TRANSPORT_ADMIN_WRITE_TOKEN`(32자 이상) 헤더가 있어야 열린다.
불일치·미설정은 404다([ADR-012](../adr/012-admin-token-for-backup-and-admin-routes.md)). 공개 웹 앱은 이 경로를
중계하지 않고 백업 화면도 없다. 관리자 앱 gateway도 `/admin/backups`를 숨긴다.

- `GET /v1/admin/backups` — `/app/backups`의 PostgreSQL custom-format `.dump` 목록
- `POST /v1/admin/backups` — `pg_dump --format=custom --no-owner --no-acl` 실행
- `GET /v1/admin/backups/{filename}` — 안전한 파일명만 다운로드
- `POST /v1/admin/backups/restore` — `.dump` 업로드 후 자동 사전 백업을 만든 다음 `pg_restore --clean --if-exists --exit-on-error` 실행

보존 개수는 `BACKUP_RETENTION_COUNT`로 제한한다. DB URL 비밀번호는 명령행에 직접 넘기지 않고 `PGPASSWORD` 환경으로만 PostgreSQL CLI에 전달한다.

복원 요청은 먼저 pre-restore dump를 만든 뒤 업로드와 `pg_restore`를 순서대로 실행한다. 운영 기본 제한은
명령별 `BACKUP_COMMAND_TIMEOUT_SECONDS=120`, 업로드 `BACKUP_UPLOAD_TIMEOUT_SECONDS=600`이다. 업로드는
시간 제한을 넘기면 임시 파일을 삭제하고 실패하며, 임시 파일은 다음 백업 목록/생성/업로드 시에도 정리한다.

수집 scheduler가 켜진 운영 profile에서는 복원을 `409`로 거부한다. 복원은 현재 PostgreSQL을 덮어쓰므로,
5분 freshness를 깨뜨리지 않도록 scheduler를 중지한 명시적 유지보수 창에서만 실행한다.

## 자동 백업 (Manager로 이관)

2026-09 운영 식별자 개명([ADR-010](../adr/010-deploy-identity-rename-transport.md))부터 이 저장소는
자체 백업 cron을 두지 않는다. 주기 백업은 `kor-travel-docker-manager`의 standalone backup으로
옮긴다(소유자 결정). 개명 cutover의 `finish` 단계가 n150 digitie crontab의 옛 줄을 지우고,
`scripts/n150-backup-cron.sh`는 저장소에서 삭제했다.

옛 줄은 `0 18 */3 * * /home/digitie/apps/kor-travel-airport/scripts/n150-backup-cron.sh >>
/home/digitie/apps/kor-travel-airport/backups/cron.log 2>&1`이었다. `backups/`가 `root:root 755`라
digitie의 `>>` redirect가 스크립트 실행 전에 실패했고, 2026-09-05 뒤로는 dump를 만들지 못했다
(syslog에는 실행 기록만 남았다). 1 GB가 넘은 공용 DB dump는 기본 `BACKUP_COMMAND_TIMEOUT_SECONDS=120`
안에 끝나지 않는 것도 확인됐다(수동 dump 약 9분).

Manager의 transport 백업 역할이 설치되기 전까지는 주기 백업이 없다. 그 사이의 복원 지점은 개명
cutover `restore-point` 단계가 만든 두 DB(`kor_travel_transport`, `kor_travel_transport_dagster`)의
직접 `pg_dump -Fc`다(`pg_restore --list`로 확인). `POST /v1/admin/backups` API는 관리자 토큰 뒤에
남고, 공개 웹 앱의 백업 UI는 ADR-012로 제거했다.

## 운영 주의

이 API는 관리자 토큰으로 닫혀 있다(ADR-012, ADR-003 대체). 2026-10-02까지는 인증이 없었고 공개 경로로 노출됐다.
호스트에서 직접 호출할 때는 토큰을 명령행에 남기지 않도록 `curl -H @-`로 표준 입력에서 헤더를 넘긴다
(`scripts/deploy-transport-admin-server14.sh`의 capability 확인과 같은 방식). 복원은 현재 데이터를 덮어쓰므로 자동 사전 백업을 둔다. 복원 후 backend를 재기동하거나 화면을 새로고침해 analytics cache와 현재 상태를 재확인한다.

## 수동 확인

```bash
docker compose --project-name kor-travel-transport --env-file .env.server14 -f docker-compose.yml -f docker-compose.shared.yml exec backend ls -lh /app/backups
docker compose --project-name kor-travel-transport --env-file .env.server14 -f docker-compose.yml -f docker-compose.shared.yml exec backend pg_dump --version
```

백업 파일은 Git에 넣지 않는다. `backups/`는 호스트 bind mount이며 `.gitignore`에서 제외한다.
