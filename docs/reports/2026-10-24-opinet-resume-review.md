# 오피넷 수집·저장·재개 상세 점검

## 확인한 장애

운영 원장의 run1645는 2026-10-23 18:05 KST 시작 후 약3시간의 브라우저 수집을
마쳤지만 21:14 KST 최신 가격 INSERT의 서버 `statement_timeout`으로 실패했다.
`fuel_latest_prices` 갱신이 `collected_at`으로 전체 이력을 다시 검색·정렬하는 단일
문장이었고, 실패 뒤 원본·최신 가격·성공 시각은 함께 롤백됐다. 마지막 성공은
2026-10-21T00:49:20Z였다. 이후 run1730은 실제로 `skipped`였지만 Dagster는
SUCCESS를 표시했다. 오래된 참조에 대한 export503은 데이터 보호 동작이다.

Dagster run의 큐 대기는48초, op 실행은3시간8분52초였다. 3시간은 큐 대기가 아니다.
전국 약230개 시군구 기준 두 탭의 조회만460회이며 이전 구현은 시군구 수집에도
읍면동 목록을 탐색했다. 기본 화면 조작 대기만으로3시간을 설명할 수는 없다.
2026-10-24 08:10 KST 표본에서4코어 CPU99.92%, load32.02였으나 해당 과거 실행의
지연 기여율로 단정하지 않는다. CPU throttle·OOM 증거는 없었다.

진행 INFO는 수집기에 있었지만 운영 Dagster의 `python_log_level=WARNING`에서
제거됐다. 해당 run의15개 event와 compute log에 지역·탭별 시간 정보가 없어
지연을 단계별로 소급 분해할 수 없다. 새 계측으로 다음 실제 실행에서 확인한다.

## 변경과 실패 경계

### 추가 요청 — 랜덤성을 유지하며30분 목표로 단축

Provider PR25는 조작별 대기를 기존0.25~1.25초에서0.05~0.15초의 독립 무작위
대기로 줄인다. 평균 대기는0.75초에서0.10초로 줄지만 요청 상한·응답 완료·지역
선택값 검증은 유지한다. 지연만 줄여3시간이30분이 된다고 가정하지 않는다.
이는 초기 후보다. 사용자 최종 요청에 따라150~850ms(평균500ms)로 조정한다.

초기 후보 b2af98e는 WSL293 PASS와 CI green 뒤에도 두 독립 리뷰에서 혼합
server/load 결과의 부분 완료와 지연된 하위 목록 경쟁이 재현됐다. 아직 운영에
적용하지 않은 조기 HTML 파싱 경로는 제거하고 문서 완료 확인을 유지한다.
가격 파싱에 쓰지 않는 image/font/media 요청만 제외하고 스크립트·CSS·XHR·fetch와
DOM의 alt 속성은 유지한다. 후속 캐시 보완은 아래 별도 검증을 따른다.

이후 실제 기본 Chromium의 정상 초기 진입으로 공개 화면과 handler를 확인했다.
시군구 선택은 이미 결과 문서 POST를 보내므로 시군구 모드에서 main-frame·지역·
검색 모드·탭·빈 상호/주소 필터·빈 읍면동을 검증해 같은 응답을 재사용한다.
조회 버튼의 중복 POST를 줄이며, 코드에서 form을 직접 제출하지 않는다. 활성 탭은
anchor뿐 아니라 부모 li.sel·BTN_DIV·LPG_YN도 확인한다. 공개 sigunguGisAjax의
result 배열 SIGUNGU_NM과 실제 옵션의 값·이름·순서를 대조해 짧은 pause 뒤
이전 목록을 읽지 않는다. 정상 빈 목록은 본문 증거와 대조한다.

기존 약230개 시군구의 문서 조회 모델은 탐색230+선택460+버튼460≈1150회이며,
탐색 생략·자동 결과 재사용 뒤 약460회다. 요청량60% 감소 모델을 시간83% 감소로
해석하지 않는다. 최종 지연으로 조작1150회를 가정하면 무작위 대기는 평균575초이며
시작·탐색120초를 제외한 지역 선택·응답·파싱은 검색당 평균 약2.4초 이하가 필요하다.
이는 시간 예산이며 실제 전국30분 완료는 아직 미검증이다. 자동 선택
조회의 시간은 selection 로그에 포함한다. 최종 provider166dc6d는 WSL340 PASS/4 live SKIP,
coverage93.86%·mypy20파일 PASS이며 실제 Chromium26개를 포함한다. 혼합·동적·빈 결과,
잘못된 지역/탭, 지연 옵션 교체, 자동 POST 재사용과 필터·동일 지역 fallback을 검증했다.
CI5개가 통과한 뒤 James/Popper 공식 독립 재검토에서 P0/P1 없음, Popper P2는
예산이 탭별 지역 조회 시도이며 전체 HTTP 상한이 아니라는 문서 명시로 해소했다.
문서 전용 c422283 delta도 두 리뷰를 마쳤다. 이후 작성자 경합과 캐시 보존 보완을
포함한f58a879를 앱에 고정하며, 최종 앱 CI·독립 리뷰는 아직 진행 중이다.

### 후속 — 캐시를 유지하는 시각 자원 차단

Playwright 요청 라우팅은 이미지 URL 패턴만 좁혀도 HTTP 캐시를 비활성화한다.
로컬 HTTP 서버·실제 Chromium의 초기 GET·동일 페이지 form POST2회에서 기존 방식은
JS·CSS를 매회 다운로드하고, CDP Fetch의 Image·Font·Media 한정 차단은 각각 최초1회만
다운로드하는 것을 재현했다. PR27 ce801cd는 이 CDP 방식으로 바꾸고 비동기 차단 작업을
정리한다. 스크립트·스타일·가격 fetch·문서 완료와 기존 지역·탭 검증은 유지한다.
열린 페이지의 차단 오류는 숨기지 않고, 페이지 종료와 차단 응답의 경합은 미처리 task
예외를 남기지 않는다. 기존 Chromium26개에 캐시2개·종료 경합1개를 추가해 실제29개,
WSL전체346 PASS/4 live SKIP·coverage93.93%·mypy20파일 PASS다. 최종 지연은 사용자 요청의
150~850ms로 변경하며 전체 검증을 다시 진행한다. 운영 CPU·전국30분 달성으로 확대
해석하지 않는다. Popper 독립 리뷰에서 CDP failRequest·disable·detach가 멈추면 취소 뒤에도
종료가 대기하는P1을 재현했다. 정리5초 상한과 남은 작업 취소·회수를 추가했다.
수정 전3 FAIL·수정 후 정리/랜덤 지연7 PASS다. 최종 CI 뒤 두 리뷰를 다시 확인한다.
사용자 최종 지연과5초 상한을 포함한 provider95b6eec의 전체349 PASS/4 live SKIP·
coverage93.94%·mypy PASS를 확인했다. 앱의 실제 collector 기본값도150~850ms인지 검증한다.
후속 독립 재리뷰에서 정리 timeout이 원래 취소·인증 오류를 덮는P1도 재현됐다.
원래 BaseException이 있으면 정리 실패가 이를 대체하지 않게 보완했다. 수정 전6 FAIL·
수정 후 해당 집중10 PASS이며, 실제 run_forever의 취소 뒤 오류callback0·cancelled=true
검증3개도 추가했다. f58a879의 전체355 PASS/4 live SKIP·coverage93.96%·mypy20파일·
CI5개 PASS다. 최종 두 독립 재리뷰 뒤에만 이 버전을 운영 후보로 확정한다.
f58a879의 최종 James/Popper 공식 독립 재리뷰는 P0/P1/P2 없음이다. Popper의 별도9개
probe도 취소·인증·요청 제한 오류를3개의 무응답 정리 경로에서 보존하는 것을 확인했다.
PR27을 머지했고 같은 provider의 앱 집중 PostgreSQL128 PASS·uv lock check PASS다.

### 저장·재개 보완

- Provider는 실제 조회 단위의 지역 목록·완료 지역·요청 전 차감 예산을 영속 SQLite에
  확정한다. 단일 작성자 잠금은 프로세스 종료 시 해제된다. 완료한 지역을 다시 읽지
  않고 미완료부터 재개하며, 완료 결과는 원래 수집 시각으로 브라우저 없이 재전달한다.
- 체크포인트 기본 유효기간은 시작부터12시간이다. 만료·범위 변경·소비 완료는 새
  수집을 시작하고, 손상·디스크 실패·미완료는 정상 완결로 처리하지 않는다.
- Transport는 완료 체크포인트의 **저장만** 재개할 때 기존 외부 요청 예약을 유지한다.
  저장 실패 직후에도 완료 결과만 읽을 수 있으며 외부 요청 유예를 우회하지 않는다.
- 유가 원본 upsert의 RETURNING으로 실제 원본 id와 값을 받아 최신 가격을 최대2000행씩
  갱신한다. 수집 경로에서 전체 유가 이력을 다시 검색하지 않는다. 같은 수집 시각의
  여러 관측은 원본 id 순서를 유지하고, 더 오래된 최신 가격을 덮어쓰지 않는다.
- 원본·최신 가격·소스 성공 상태는 같은 transaction으로 확정한다. 실패 중간 결과는
  공개하지 않는다. DB commit 이후에만 체크포인트 소비 완료를 기록한다. 그 사이
  프로세스 종료는 동일 스냅샷의 멱등 저장으로 복구한다.
- 완료 결과를 여러 실행이 읽어도 저장 transaction의 소스 잠금 뒤 마지막 성공을 다시
  읽는다. 이미 저장되거나 더 새 자료로 교체된 결과는 주유소·원본·최신·상태를 다시
  쓰지 않는다. 저장 오류 rollback 뒤와 후행 취소의 오류 게시도 같은 경계를 재확인한다.
- 서버 statement/lock timeout·직렬화 실패·교착·연결 끊김은 같은 메모리/체크포인트
  결과로 저장만1회 재시도한다. 제약 위반은 반복하지 않는다.
- 실패 완료 시각에서8시간을 다시 더하지 않고 외부 조회 전 확정한 시작 기준 예약을
  유지한다. 정상 다음 tick을 건너뛰지 않는다. 이미 저장된 과거 예약을 임의 수정하지 않는다.
  정상 실패에도15분 tick 여유를 적용하며 in-process는 여유를 되돌려8시간 간격을 지킨다.
- 오래되거나 실패 상태인 원천을 수집하지 않은 `skipped`는 Dagster SUCCESS로 숨기지
  않는다. 정상 유예는 `status=skipped`·건수·다음 예정 metadata와 경고를 남긴다.
- 진행 로그는 유가 op 안에서만 INFO를 허용하고 원래 수준·propagation을 복구한다.
  원문 root 중복 전달을 막고 가린 메시지만 전송한다. Provider는 지역 선택·응답·결과
  준비 누적 시간을 기록한다. 공용 Dagster 설정은 변경하지 않는다.

## 운영 설치

`OPINET_CHECKPOINT_PATH=/app/collector-state/opinet.sqlite3`이며 backend와 code-server는
같은 `opinet-checkpoints` named volume을 사용한다. Docker root와 volume 실제 경로가
승인된 NVMe인지 배포 전 확인한다. 영속 파일은 Git·이미지·원본 DB에 넣지 않는다.
기존 실패 run의 이미 롤백되고 메모리에서 사라진 스냅샷은 새 체크포인트로 복원할 수 없다.

## 검증 상태

Provider 최종 WSL 전체282 PASS/4 live SKIP, coverage93.73%, 실제 Chromium1 PASS, mypy PASS 및 PR24 CI의
Python3.11/3.12/3.13·typecheck PASS를 확인했다. 프로세스 강제 종료 뒤 잠금 해제와
요청 예산 보존, 미완료 지역 재개, 완료 결과의 브라우저 없는 재전달, checksum 손상
거절을 검증했다. James/Popper 두 독립 재검토 뒤 PR24를 c9c9181로 머지했다.
Transport 사전 리뷰의 미기록 파일 오류·빠른 다음 tick·오래된 동시 재개의 역행을 재현해
수정했다. 취소/지연/저장 오류3경로 회귀를 포함한 집중58 PASS, 전체 최종 검증은 진행 중이다.
통합 `scope=all`의 고속도로 조회 중 취소도 이미 확보한 pending 시각으로 유가 상태를
보호하도록 후속 보완했다. 해당 회귀를 포함한 체크포인트12 PASS를 확인했다.
이전 후보의 전체 검증은 최종 수정으로 중단했으며 통과로 세지 않는다. NTFS의 npm/파일
지연을 피해 동일 tracked source를 WSL ext4로 복사해 hash 대조 후 다시 검증한다.
재사용 Docker 검증 이미지의 같은 버전 provider가 남는 문제는 VCS commit 검증·강제 설치로
해소하며 제품의 깨끗한 이미지 빌드와 구분한다. 운영 수용은 아직 미완이다.
새 코드의 실제 전국 수집 시간과 최신 export200 회복 전에는 운영 해결 완료로 세지 않는다.
2026-10-24 10:38 KST 읽기 전용 확인에서 기존 운영 run1885가08:04:24~10:31:46,
2시간27분22초 뒤 success였다. last_success_at은10:27:19 KST이고 last_error는 없다.
앱 running·Dagster 활성 Transport run·code-server 실행 worker는 모두0이다.
이는 새 후보 적용 전의 회복이며 export 응답과 새 후보 전국 실행 시간은 별도 확인한다.
10:40 KST 실제 TCP loopback12302의 fuel-stations?limit=1은HTTP200·items1이며
failed/stale/last_attempt_failed=false였다. 실제 소비자 경로 E2E와 새 후보 검증은 별도다.
Manager transport 대상은odroid192.168.1.13, Docker root는NVMe로 확인했다.
현재 운영 API/CS의 체크포인트 설정·마운트·named volume은 없으므로 새 배포에서 확인한다.

f0d1621 사전 적대 리뷰의 추가 경계도 재현했다. James는 fixture/disabled의 fuel_ready
누락으로 미수집이 Dagster SUCCESS가 되는P1을 재현했다. 모든 fuel 요약에 준비 여부와
비활성 원인을 명시하고 skipped는 명시적인 fuel_ready=true일 때만 정상 유예로 인정한다.
Popper는 fresh 실행보다 pending 저장이 먼저 끝나면 최초8시간 예약이 정규화되지 않는P1을
재현했다. 새 claim부터 동일 last_started_at 기준의15분 tick 여유를 확정해 저장 순서에
의존하지 않는다. 기존 예약의 재개는 그대로 보존하며 in-process는 여유를 되돌린다.
만료 예약의 저장 재개가 계속 실패해1초 반복하던P2는 fuel in-process 실패 대기에
기본 transport 간격 이상의 backoff를 적용했다. 변경 전 경합2 FAIL, backoff2 FAIL/2 PASS,
변경 후 실제 service/Dagster·경합·backoff·가림 집중20 PASS를 확인했다. 최종 전체검증은 재실행한다.
추가 독립 재현에서 작성자 잠금이 잡힌 체크포인트를 읽은 별도 실행이 기존 원천의
last_error를 게시해 공개 stale·last_attempt_failed를 오염시켰다. 참조 주유소 export는
성공 시각 기준이므로 이 경합만으로503이 된다고 해석하지 않는다. Provider e160068의
OpinetCheckpointBusyError는 실제 SQLite BUSY/LOCKED(확장 코드 포함)만 구분한다.
앱은 해당 경합에서 브라우저를 열거나 기존 원천 성공·오류·예약을 쓰지 않고 건너뛴다.
기존 실패와 미수집 원천은 준비된 상태로 숨기지 않는다. 같은 문구의 일반 오류·I/O·손상은
여전히 실패로 남긴다. Provider349 PASS/4 live SKIP·coverage93.87%·Chromium26 PASS·mypy PASS,
실제 파일 잠금과 PostgreSQL의 fresh/failed/missing×fuel/all 회귀 포함 앱125 PASS를 확인했다.
같은 문구의 일반 서버 오류와 실제 Dagster collector_busy metadata를 더해 WSL127 PASS·
Docker PG127 PASS를 확인했다. ce801cd 최종 provider pin으로 재검증·CI를 진행한다.
격리 PostgreSQL의 합성10000주유소·4유종40000행은 실제 service.collect 저장13.531초,
동일 완료 스냅샷의 저장 재개0.026초였다. 원본/최신40000행과 provider 호출1회를 확인했다.
이는 외부 수집 없는 저장 경로 검증이며 운영 속도 수용을 대신하지 않는다.
Transport ea51470 CI는1107 PASS/2 SKIP 뒤 fixture에서 유가 소스를 제외한 변경과
충돌한 scheduler 종료 테스트1건이 실패했다. 해당 테스트에 실제 유가 지원 fake를
명시하고 WSL 회귀1 PASS로 확인했다(cac391a). 전체 CI는 다시 실행 중이다.
Frontend WSL130 PASS·build PASS, Docker130 PASS를 확인했다. WSL 전체의 백업
업로드7건 실패는 `/tmp`가 ext4가 아닌15GiB tmpfs이고 여유 공간이2GiB보다 적어
발생했다. 테스트 임시 경로를 여유 있는 `/var/tmp`로 지정한 백업 회귀9 PASS를
확인했다. 다른 프로젝트 파일은 건드리지 않고 이 작업의 완료된 frontend 캐시만
같은 로컬 ext4로 옮겼다. 6abfc6f 전체 WSL은1099 PASS/2 SKIP/8 FAIL로, 위 백업7건과
수정한 scheduler1건이다. 같은 이전 후보 Docker는1103 PASS/5 SKIP/1 FAIL로 scheduler
1건이다. 최종 후보 전체 통과로 합산하지 않으며, 최종 pin·앱 회귀·CI를 별도로 확인한다.
