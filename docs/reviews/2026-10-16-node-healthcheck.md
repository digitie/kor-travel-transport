# 2026-10-16 — Node UI healthcheck의 BusyBox GET 전환

## 문제와 변경

부하 중 기존 Node healthcheck가 Docker timeout을 자주 넘겨 UI가 응답해도 unhealthy가 됐다.
공개 frontend와 독립 관리자 transport-admin-web의 healthcheck만 기존 이미지의
/usr/bin/wget으로 바꾼다. API·code-server·gateway probe와 수집/복구/서비스 동시성은 바꾸지 않는다.
공개 frontend는 docker-compose.shared.yml, 관리자는 docker-compose.transport-admin.yml이 정본이다.
기본 bridge 개발 스택 docker-compose.yml의 Node probe는 이번 범위에 포함하지 않는다.

두 probe는 CMD exec 형식의 /usr/bin/wget -q -T5 -O/dev/null URL이다.
원래 loopback GET endpoint(/와 /login), 환경변수 포트 보간, Docker timeout5초,
interval10/15초, retries10/5, start_period20초를 유지한다.
BusyBox1.37 help에는 -t/--tries가 없어 지원하지 않는 retry flag를 추가하지 않는다.
로컬 실패 응답·stall 모델에서 각 endpoint를 한 번만 요청하고 실패했음을 확인했다.

## 판정과 한계

wget은 GET 본문을 /dev/null로 읽고 404/503/304·연결 거절·읽기 지연에서 nonzero를 반환한다.
정상200/204 및302→200은 성공하고302→404는 실패한다. HEAD/--spider로 바꾸지 않는다.
Node fetch처럼 redirect를 따라가지만 구현과 redirect 상한/HTTP 헤더는 같다고 보장하지 않는다.
redirect에는 추가 GET이 발생한다. 현재 두 endpoint는 직접200을 반환하므로,
배포 전 동일 URL의 기대 응답과 인증 redirect 유무를 다시 확인한다.

-T5는 전체 요청 deadline이 아니라 network read timeout이다. 느린 body/redirect가
시간을 더 쓸 수 있어 전체 실행 상한은 기존 Docker timeout5초가 담당한다.
exec 형식으로 interpreter/중간 셸을 제거하지만 Docker runtime의 timeout 회수 정책을
이 회귀로 새로 증명한 것은 아니다. 이미지 내 BusyBox 옵션/경로는 재구축 시 확인한다.
unhealthy만으로 Docker가 서비스를 재시작한다고 가정하지 않는다.

## 관측과 검증

운영에서 root가 승인한 두 원 URL wget 단일 표본은 각각 elapsed0.38/0.58초,
RSS740/776KiB였고 time의 표시 CPU는0.00초였다. 앞선 계측 Node 표본은
self CPU3.237/1.172초, RSS65400/45756KiB였다. 서로 다른 시각/계측 방법의 비통제
단일 표본이며0.00은 표시 해상도 이하이지 CPU가 정확히0이라는 뜻이 아니다.
평균·절감률·전체 timeout 원인 규명으로 표현하지 않는다.
이 작업의 소스 변경 후 운영 서비스 변경/재측정은 아직 하지 않았다.

- 기존 fb52 probe를 대상으로 새 계약4건은 RED, 변경 뒤 관련 계약47 PASS·1 SKIP.
  SKIP은 기존 Dagster 단순 gRPC probe의 빈 parameter 집합이며 새 UI 계약4건은 모두 실행됐다.
- 실제 Compose config4경우(공개/관리자 × 기본/override 포트)에서 endpoint/argv/timeout 일치.
  기존 두 test 필드만 치환하면 이전 Compose YAML 전체와 동일함을 대조했다.
- 기존 소유 ARM UI 이미지의 BusyBox1.37을 networknone/1CPU/2GiB/read-only인
  독립 컨테이너에서 실행했다. 200/204/404/503/304/정상·불량redirect/headers·body stall/
  closed port 총10경우 판정 PASS. 실제 운영 장치 실행과 구분한다.
- 초기 ext4 bind mount 방식의 MODULE_NOT_FOUND 로컬 harness 실패는 원문 보존했다.
  원인은 확정하지 않았다. stdin 전달로 바꿔 검증했고 제품 실패로 합산하지 않는다.
  static config harness의 required-variable regex 오류도 설정 렌더 전에 거절돼 수정 후 따로 보존했다.
- 전체 Python/UI suite 반복 대신 영향 계약과 CI를 사용한다. 새 HEAD CI/두 독립 narrow 리뷰/
  새 ARM artifact parity 및 운영 적용은 별도다. fb52 ARM681200128B 증거를 새 HEAD 이미지로 부르지 않는다.

원본 운영 표본·실행 로그·이미지 식별자·SHA는 private 인계 원문에 보존한다.
