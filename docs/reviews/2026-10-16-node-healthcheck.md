# 2026-10-16 — 두 Node UI healthcheck의 core HTTP GET

## 문제와 최종 변경

기존 Node fetch healthcheck는 부하 중 시작 비용으로 Docker timeout을 자주 넘겼다.
shared frontend와 독립 transport-admin-web의 원 loopback GET만 Node core http.get으로 바꾼다.
API·code-server·gateway·개발 bridge probe와 수집/복구/서비스 동시성은 바꾸지 않는다.
공개 probe는 docker-compose.shared.yml, 관리자는 docker-compose.transport-admin.yml이 정본이다.

양쪽 모두 CMD node -e의 같은 템플릿을 쓰고 원URL(/·/login)/환경변수 포트 보간만 다르다.
2xx 응답 헤더만 성공, 나머지 status·연결 오류·4초 전체 요청 timer는 실패한다.
응답/실패 때 단일 Node 프로세스가 종료하며, 응답 body는 destroy하고 읽지 않는다.
별도 셸/wget/헤더 파서/하위 프로세스는 없다.
Docker timeout5초·interval10/15초·retries10/5·start_period20초는 유지한다.
4초 timer는 스크립트의 요청 시작 직후 설정되며 Node bootstrap 전까지 포함하는 시계가 아니다.
전체 health 실행 상한은 기존 Docker timeout5초가 담당한다.

## Redirect와 판정 계약

core http.get은 redirect를 자동 추적하지 않는다. 302에 Location이 있거나 없어도 실패다.
기존 fetch의 유효 redirect 추적과 차이가 있으며 fail-closed를 의도했다.
현재 두 원 endpoint의 직접200 관측에 근거한다. 배포 전 정확 원URL이 인증 redirect 없이
2xx를 반환하는지 다시 확인하고, 이후 로그인 정책 변경도 health 계약 변경으로 취급한다.
전체 body 완료를 보장하지 않는 헤더 기반 reachability 검사이며 provider/DB 건전성 검사가 아니다.
HTTP304/404/503·응답 헤더 stall·연결 거절은 nonzero다.
원 public frontend의 fetch처럼 응답 성공 뒤 연결이 남는 대신 destroy/exit로 끝낸다.

## 초기 wget 후보의 거짓 양성과 폐기

초기 wget 단일 원URL 표본은 elapsed0.38/0.58초·RSS740/776KiB로 가벼웠다.
하지만 독립 리뷰가 제시한302/Location없음/Content-Length0를 본인 ARM BusyBox1.37에서도
exit0로 재현했다. 기존 fetch r.ok=false와 다른 거짓 양성이므로 그 후보를 채택하지 않는다.
초기 static47 PASS/기존1SKIP, wget loopback10경우 통과만으로 strict 2xx를 증명하지 못했다.
반례·초기 b4e9fdb 산출물·fb52 산출물/원문을 지우거나 최종 결과로 덮지 않는다.
BusyBox timeout도 지정 PID만 종료하는 계약이라 셸/파서의 process-group 회수를 새로 조립하지 않았다.

## 실제 관측과 검증 경계

root는 최종 exact 템플릿에 resource exit 계측 hook만 붙여 두 원URL을 각1회 실행했다.
frontend CPU0.534921초/RSS34216KiB/CLI1.912624초,
admin CPU0.558437초/RSS39588KiB/CLI2.456487초로 모두 exit0였다.
전후 CID/mainPID/restart/fullConfig/HostConfig 동일, 기존 health 설정 변경0이었다.
이전 fetch 표본 CPU3.237/1.172초·RSS65400/45756KiB와는 시각/부하가 다르다.
비통제 단일 표본·계측hook 포함·서버/Docker CPU 제외이며 평균·절감률로 표현하지 않는다.

- 실제 exact template SHA256 747ceccd05e66de829d045b544ac5e86cfac27012c081478e259a60ce3d353ef.
- 자체 기존 ARM UI 이미지의 networknone/1CPU/2GiB/read-only 컨테이너에서
  core GET10경우:200/204/200 body드립 성공,304/404/503/302 두 형태/헤더stall/closedport 실패.
  timer stall은 Node startup 포함4.72초였다. 실제 운영 장치 실행과 구분한다.
- 초기 bind MODULE_NOT_FOUND의 원인은 확정하지 않았고 stdin 전달로 하네스를 고쳤다.
  static config required-variable regex 실패도 설정 렌더 전에 거절돼 원문을 보존했다.
- 영향 계약·실제 Compose 기본/override·새HEAD ARM parity·CI·두 독립 narrow 리뷰가 각각 필요하다.
  이전 full PG/native·fb52 artifact 증거를 최종HEAD 통과로 합산하지 않는다.
- source 적용 뒤 서비스 재구성/live UI/health 상태 개선율 측정은 아직 하지 않았다.
