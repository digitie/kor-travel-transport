# 공항 수집 조회 비용 개선 검증 (PR #88)

## 변경과 증명 범위

제품 후보는 e487ca1669e9d2974e2e3c05c7f4d7c26f87876f다.
공항 ORM 객체를 _store_observations 호출 안에서만 재사용한다.
관측마다 이름/영문명/updated_at 갱신, 원천 보존, snapshot unique key와
savepoint, 전체 실패 시 rollback 경계를 유지한다. 다음 저장 호출은 DB를 재조회한다.
API DTO·스키마·UI·제공자 코드는 변경하지 않았다.

집중 Python23개가 통과했다. 신규/기존 공항, 중복 관측의 이름 정정,
실패 후 rollback 재호출, snapshot savepoint 충돌 후 같은 공항의 다음 관측 저장을
포함한다. 최초 전체 pytest는172개 진행 표시 뒤 종료 요약/exit code 없이 프로세스가
사라져 NOT_COMPLETED로 남겼으며 통과로 집계하지 않는다. 이후 root 전체 재실행은
exit0,846 PASS/10 SKIP/6 warnings,1846.29초다. ARM 후보 이미지의 집중 테스트도
23 PASS(12.37초)다. 제품 e487ca16 기준 CI6 SUCCESS/live2 SKIPPED를 확인했다.
조건부 live job의 SKIP는 실제 운영 UI 통과를 대신하지 않는다.

## 국소 실측

WSL SQLite RAM DB의 1,000관측/3공항 기준·후보 각3회 결과는
[WSL 원시 표본](../audits/2026-10-18-airport-helper-ab.json)에 있다.
CPU 중앙값1227.9→543.9ms(55.7% 감소), RSS 중앙값55424→55408KiB다.
양쪽 매 관측 flush를 동일 적용해 다음 lot SELECT의 autoflush를 모사한다.

Odroid ARM64 격리 컨테이너의 같은 fixture 각3회는
[ARM 원시 표본](../audits/2026-10-18-airport-helper-arm-ab.json)에 보존했다.
SQLAlchemy2.1.5, Dagster1.13.24, 소스파일37개 대조 결과가 포함된다.

| 항목 | 기준 중앙값 | 후보 중앙값 |
| --- | ---: | ---: |
| helper CPU | 15.2357초 | 7.7411초 |
| wall | 15.5154초 | 7.8708초 |
| process peak RSS | 51,640 KiB | 51,540 KiB |
| Python allocation peak | 136,465 bytes | 132,479 bytes |
| 공항 SELECT/표본 | 1,000 | 3 |
| 공항 UPDATE/표본 | 1,000 | 1,000 |

CPU 국소 감소율은49.2%다. RSS는 사실상 동일하므로 메모리 개선 완료로 주장하지 않는다.
외부 제공자·네트워크·lot/snapshot·운영 PostgreSQL·전체 job은 측정 범위 밖이다.
서로 다른 환경인 WSL과 ARM의 절대시간 차이도 이번 개선율로 주장하지 않는다.

## ARM 실행 실패 이력

- r1: CPU guard20초에서 exit137, OOM false. 측정 전체 PASS가 아니다.
- r2: 6개 측정은 통과했지만 마지막 runtime guard에서 Docker Mounts 배열 순서 차이로
  실패했다. 실행 전체를 PASS로 취급하지 않으며 원본 로그를 보존했다.
- r3: Mounts 비교의 순서만 정규화하고 CPU guard60초로 실행했다. 6표본과 최종
  guard가 PASS다. 원본 결과는 runtime unchanged, daemon OFF, external network false,
  production database false를 기록한다.

이 guard 변경은 허용 실행 시간을 늘려 벤치가 끝나게 한 것으로, 제품 timeout이나
수집 동시성 설정을 변경한 것이 아니다.

## WSL Docker 전체2차 검증의 실패·재시도 이력

원문은 root의 transport88-docker-full-833a1525-c204-4034-b7cc-bc33117396ca
검증 디렉터리에 실행별로 보존했다. 이 이력은 위 ARM 벤치 실패와 별개다.

- 전체 r1: 20 FAIL/341 PASS/1 SKIP 후 자체 pytest에 SIGINT를 보내 정상 중단했다.
  exit2,381.58초이며 results/pytest.log와 launch.exit.safe.json을 보존했다.
  fixture에 /usr/bin/python3가 없어 PATH를 /usr/bin:/bin으로 제한하는 배포 대역
  테스트가 python3 command not found로 실패했다. 이전 검증 fixture의
  /usr/bin/python3 → /usr/local/bin/python3 연결을 복구했다.
- 집중 r2: 16 FAIL/27 PASS(focused-r2.log). Docker의 /tmp tmpfs가 기본 noexec여서
  테스트가 생성한 git/ssh 대역을 실행하지 못했고, 실제 git으로 넘어가
  not a git repository가 발생했다. 로컬 fixture의 /tmp만 exec,nosuid,nodev로
  지정했다. network none/socket 미마운트/read-only 소스는 유지했다.
- 집중 r3: 같은 host guard43개가3.01초에 PASS했다(focused-r3.log).
- 전체 r3: 839 PASS/7 FAIL/10 SKIP,1045.02초,exit1로 완주했다.
  results-r3/pytest.log·junit.xml·result.safe.json을 보존했다. 7개 실패 모두
  backup_restore의 디스크 여유 공간 검사였다. 제품 MAX_BACKUP_BYTES는2GiB인데
  검증 /tmp tmpfs를1GiB로 제한해 의도한 upload/timeout/용량 테스트 이전에 거절됐다.
- 집중 r4: /tmp를 검증 디렉터리 안의 새 소유 임시 디렉터리로 bind했다
  (실측 여유147,803,631,616bytes). backup_restore 전체9개와 host guard43개,
  합계52개가3.37초에 PASS(exit0)했다. focused-r4.log와
  results-r3/focused-r4.xml을 보존했다. JUnit ID 대조로 원래 실패7개 모두
  이 재검증 PASS에 포함됨을 확인했다.

[최종 범위 대조 증거](../audits/2026-10-18-airport-docker-verification.json)는
동일 image ID, e487 소스605개 hash, 설치 의존성 pin과 환경값 유지,
선택한 시험 범위, 임시 파일시스템과 실행 병렬성의 차이를 기록한다.
전체 r3는 pytest-xdist -n2 --dist loadfile이며 r4는 xdist 없는 직렬 실행이다.
따라서 r4는 실패 원인에 대한 재검증이며 동시성 재검증은 아니다.
Docker가 환경변수 배열 순서는 다르게 반환했지만 중복 key0/이름별 값은 동일했다.
전체 r3 실패를 지우거나 두 실행을 단일 전체 PASS로 합산하지 않는다.
새 임시 파일시스템에서 전체 suite 한 번의 재실행은 하지 않았다.

제품·테스트·배포 PATH guard를 수정하거나 기대값을 완화하지 않았다.
변경은 검증 fixture의 인터프리터 위치, 대역 실행용 tmpfs 옵션과 임시 저장공간뿐이다.
저장소 규칙상 배포 전에 완료해야 할 WSL Docker 전체2차 게이트가 이번에는 배포
뒤에 수행됐다. 이 순서 차이를 보존한다. James/Popper가 소스와 최종 검증을
독립 검토했고 미해소 P0/P1/P2는 0건이다. 두 검토에서 전체 재실행을 필수로
만들 구체적 잔여 위험은 발견되지 않아 실패군 전체 재검증으로 수용했다.

## 배포와 최종 수용

전체 Python·ARM 집중 테스트와 CI 결과는 위와 같다. root의 API/CS 운영 전환
attempt297a1d36은 PASS다. UI/Admin 이미지는 이번 변경에서 재배포하지 않았다.
배포 후 공개 UI는 WSL Chromium1243에서34/34 PASS다. 로그인·메뉴·지도 요청 완료,
교통 화면, Dagster 상태·실패 상세·검색·503/네트워크 오류 복구,
320/375/414/768/1440px 화면, 로그아웃 등을 확인했다.
공개 UI 원문 SHA256은91e026dd31e8b3a6951d3dc6ce59555299a34887a3846685257ecc89bbdfc9ee다.

WSL Docker 전체2차 검증은 e487 Git archive605개를 read-only로 고정한 새 격리
fixture에서 완주했고 위 실패7개를 범위 재검증으로 해소했다. 설치된 모든 Git 의존성
pin을 direct_url로 대조했고 Common89291f36 pin 및 pip check 통과를 확인했다.
network none, 운영 socket 없음, 임시 SQLite, CPU3/RAM3GiB,
전체 pytest-xdist2/loadfile 조건이다. 이 수용 기록을 PR #88에 포함한다.
단일 전체 Docker PASS와 전체 수집 RSS·idle 개선을 주장하지 않는다.
Dagster daemon OFF를 유지하며 자동 수집 실행을 이 시험으로 대신하지 않는다.
