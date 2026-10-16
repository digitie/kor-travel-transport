# Transport83 점검 CPU 소스·검증 정산

runtime candidate는 d797163e83602935152418f65a176bd3c63916dc이며 후속 commit은 이 증거 문서만 바꾼다.
PR82 EXISTS를 보존하고 Common37 c485/최종 stdlib 컴파일/API strict HTTP/운영·legacy8역할 interval3배를 적용한다.
CS guard/reaper·업무 주기·리소스·provider 핀은 유지한다. [계약·운영 한계](../runbooks/health-cpu-bytecode.md).

## 독립 리뷰

A의 최초 FULL657과 최종d797 delta, C의 최종FULL11을 독립 원문 그대로 보관했다.
A/C 두 명의 SOURCE_PASS·열린 P0/P1/P2=0이며 저자 시험을 별도 독립 리뷰로 세지 않는다.
A TR83-A-P3-01은 암묵적 compile 가능성과 startup을 제외한 HTTP4초 경계 문구를 정정해 CLOSED다.
A 최초 source에는 없던 legacyDB5→15초를 최종delta에서 확인했다.
C는 Common35/37 저자이므로 그 모듈의 새 독립 승인으로 합산하지 않고 Transport 채택 범위의 독립 검토로 센다.

## 실제 로컬 검증

| 범위 | 결과 | 한계 |
|---|---|---|
| 원657 host backend 전체 |754 PASS/10 SKIP/6warnings,1517.06초|최종d797 exact 전체라고 재표시하지 않음|
| 최종d797 집중 |49 PASS/1 SKIP, Ruff PASS|신규 범위만|
| frontend/admin |130/202 PASS, 각 type/build PASS|UI Docker/운영 별도|
| d797 native amd64 Docker 전체 |**745 PASS/13 SKIP/7 FAIL**/9warnings,1699.44초|기존 전체 FAIL 보존|
| 같은image의 정확7실패 재검증 |**7 PASS**,0.13초|새 전체 PASS로 합산하지 않음|
| d797 GitHub CI |backend2/frontend2/admin2 SUCCESS,live2 SKIPPED|push/PR 중복 job 수를 독립 제품시험 수로 세지 않음|

Docker 전체 실패7개는 test_backup_restore의 upload6/create1이 모두 실제 free<MAX_BACKUP_BYTES(2GiB) 검사에서
먼저 거절된 것이다. 해당 fixture의 /tmp tmpfs 전체가1GiB여서 제품 precondition을 충족할 수 없었다.
원제품 MAX·조건·시험은 변경하지 않았다. 같은 d228dbbfd03ecd8b7f04901733d534aa2503f2d93e23c95db8f002315d53140f 이미지에서
2GiBmemory=swap/1CPU/PIDs256/netnone/readOnly/capdropALL/noNewPriv/noports/noDockerSock를 유지하고
새UUID fixture의 표시tmpfs만3GiB로 조정했다. 시험 전 실제total/free3,221,225,472B/used0과 memory.max2,147,483,648B를
assert한 뒤 정확7개를 실행했다. 기존 컨테이너/이미지/볼륨/DB 변경·prune0, 두 시험 모두 전후 기존CIDset 동일·CLI terminal이다.
의존성 실패라는 근거는 없었다.

기존 Docker fixture는 uv.lock과34버전 차이가 있다. 대신 현재 project+dev26 specifier/marker·providerVCS·SDK1.13.24를
실제 확인한 cached native dependency set이다. Common만 exact c485 wheel을 no-index/no-deps로 교체하고
exactGitarchive를 넣었다. 이 검증을 uv.lock 정확 재현 또는 ARM artifact 검증이라고 표현하지 않는다.

Docker13 SKIP는 host와 공통10(PG전용8/대규모benchmark optinOFF1/기존CSprobe emptyparam NOTSET1)과
DockerCLI없는 이미지의 admin Compose public-origin3params다. original log 상태765개와 같은소스 collect-only765개를
대응했고 host657의764개는 최종에 추가된 legacyDB healthparam1개를 제외해 비교했다.
원시험에 -rs가 없어 이 분류는 원skip reason report가 아닌 source·순서 대조 복원이다.
NOTSET를 실제 gRPC health server 회귀 PASS로 세지 않는다. DockerCLI가 필요한3개는 host 전체에서 실행됐다.

## 실패 이력과 남은 gate

구 소스 신규 회귀10 FAIL/6 PASS, 최초 UI build 외부 node_modules symlink 거절, Docker1GiB 시험 실패는 보존했다.
후속 own복사 UI build 성공과 용량 조건만 보정한7개 성공을 원 실패와 구분한다.
최종 증거 commit의 CI는 별도로 확인한다. [원문 manifest](evidence/2026-10-16-health-bytecode-manifest.md).

ARM mergedsource 이미지·실제 pyc/magic/UID readability·cold health·배포 provenance·live API/UI·CPU 인과 비교는 **NOT_RUN**이다.
네 파일의 main matching만으로 전체 운영 이미지 HEAD를 단정하지 않는다. PR81의 cadence/Common41/Opinet 변경을 포함하지 않는다.
소스리뷰와 로컬검증을 운영 성능 개선·전체 요청 완료·merge 완료로 격상하지 않는다.
