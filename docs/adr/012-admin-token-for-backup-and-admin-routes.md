# ADR-012: 백업·관리 API는 관리자 토큰으로 닫고 공개 웹 앱에서 백업 UI를 없앤다

- **상태**: accepted
- **날짜**: 2026-10-02
- **결정자**: agent + human (보안 hotfix, `hotfix/public-backup-exposure`)
- **컨텍스트**: ADR-003은 백업 API를 앱 인증 없이 두고 네트워크 경계만 믿었다. 2026-10-02 ~12:40Z
  확인 결과 그 경계가 없었다. `https://pr-api.digitie.mywire.org/v1/admin/backups`(edge → n150 uvicorn
  `0.0.0.0:14001`)에서 목록 200, dump 다운로드(Range 206), 백업 생성 POST가 모두 인증 없이 됐다. 복원은
  scheduler가 켜져 있어 409로만 막혔다. 공개 웹 앱 프록시(`pr.digitie.mywire.org/api/backend/v1/admin/backups*`)도
  allowlist로 같은 경로를 명시적으로 중계했다. 임시 조치로 n150 iptables가 14001의 비-loopback 접근과
  loopback의 `/v1/admin/backups` 문자열을 막고 있다.
- **결정**:
  1. 백엔드: `/v1/admin/collector-status`(공개 대시보드 읽기 전용 상태)를 뺀 모든 `/v1/admin/*` 경로
     (백업 목록·생성·다운로드·복원, 수동 수집)는 `x-transport-admin-token`이 `TRANSPORT_ADMIN_WRITE_TOKEN`
     (32자 이상)과 상수 시간 비교로 일치할 때만 연다. 불일치·미설정은 경로를 숨기는 404다. 라우트 의존성이
     정본이고, 같은 판정을 HTTP 미들웨어가 라우팅 전에 한 번 더 해 인증 전 복원 업로드 본문을 읽지 않는다.
     좌표 보정(`/v1/transport/admin/place-locations*`)도 같은 helper를 쓴다.
  2. 공개 웹 앱(`frontend/`): 프록시 allowlist에서 `admin/backups*`를 모두 지우고, 관리 경로(`admin/backup*`,
     `collector-status` 외 `v1/admin/*`)를 대소문자 무시로 명시 거부한다. 빈·점(`.`/`..`) 세그먼트와 `/`·`\`·`%`·
     제어문자를 품은 세그먼트는 거부하고, 전달 경로는 세그먼트별 `encodeURIComponent`로 다시 만든다. `/backup`
     화면·백업 패널·API 클라이언트 함수·`BACKUP_PROXY_*` 타임아웃을 제거한다.
  3. 관리자 앱(`packages/kor-travel-transport-admin`)은 원래 백업 기능이 없고 그 API gateway(12301)는
     `/admin/backups`를 404로 숨긴다(`test_transport_admin_contract`). 바꾸지 않는다. 운영자 백업은 Manager의
     standalone 백업 또는 호스트에서 토큰 헤더를 붙인 직접 호출로 한다.
- **근거**: 네트워크 경계 하나에 기대는 구조가 실제로 뚫렸으므로 앱에 2차 방어선이 필요하다. 이미 있는
  관리자 토큰(좌표 보정용, 관리자 BFF 전용)을 재사용하면 새 비밀·로그인 흐름 없이 닫을 수 있다. 공개 앱은
  관리 기능을 제공할 이유가 없으므로 UI와 프록시 경로를 모두 지운다.
- **결과 (긍정)**: 14001이나 공개 프록시가 다시 열려도 백업 dump·생성·복원·수동 수집이 토큰 없이 동작하지 않는다.
  공개 프록시는 경로 정규화 변형으로도 관리 경로에 닿지 않는다.
- **결과 (부정)**: 웹에서 바로 하던 백업/복원 UI가 사라진다. `TRANSPORT_ADMIN_WRITE_TOKEN`이 비어 있는 배포에서는
  백업 API가 전부 404다(의도된 fail-closed). `collector-status`는 계속 공개라 최근 수집 실행의
  `error_message`가 노출된다 — 지금은 비어 있지만 provider 예외 문자열(`str(exc)`)이 그대로 저장되는 구조다.
- **후속**: 배포 후 iptables 임시 차단을 풀기 전에 공개 경로 두 곳(`pr-api.../v1/admin/backups`,
  `pr.../api/backend/v1/admin/backups`)이 404인지 확인한다. 14001의 `0.0.0.0` 바인딩은 별도로 재검토한다
  (`docs/journal.md` 2026-10-02 항목). ADR-003은 이 ADR로 대체된다.
