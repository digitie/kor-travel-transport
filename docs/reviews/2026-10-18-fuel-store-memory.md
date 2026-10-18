# 유가 저장 중간 버퍼 메모리 개선

기준은 PR #88이 머지된 a8ff6caa6064e3bab0ccd724f685e6913006d221이다.
주유소 upsert 이후 저장용 사전과 마지막 DB 결과 참조를 해제하고, 주유소·유가
묶음 목록은 요청하는 묶음만 만든다. 원본 snapshot과 재시도용 참조는 보존한다.

전역 키 중복 제거, 마지막 값 우선과 최초 삽입 순서, 원본 JSON, first_seen_at,
collection_run_id, 최신 가격 테이블 갱신과 트랜잭션 경계는 바꾸지 않는다.
주소 갱신 원천 필드와 파생 주소 테이블도 변경하지 않는다.

검증은 진행 중이다. WSL의 독립 프로세스에서 같은 합성 snapshot으로 전체
_store_fuel_snapshot과 DB 작업을 측정한다. 과거 운영 행 수 11,885개 주유소와
약 5만~6만 가격 행을 참고하되, 합성 raw의 실제 바이트를 별도로 기록한다.
실제 provider/browser 수집, 전체 job, 운영 RSS 및 idle 감소를 주장하지 않는다.
초기 구현 기록 당시에는 배포·머지·운영 실행 전이었다. 현재 배포·UI 수용은 아래 최종 절을 따른다.

## 로컬 측정 및 회귀

PostgreSQL16 전용 컨테이너에 공식 Alembic0025를 적용하고 동일 합성 snapshot을
독립 Python 프로세스 6개(기준·후보 각3회)에서 저장했다. 기준과 후보 DB는 매번
비운다. 원본 UTF8 8,713,255bytes(주유소당 평균733.13bytes)는 합성 크기다.
실제 운영 응답 크기로 해석하지 않는다.

| 전체 저장+commit 중앙값 | 기준 | 후보 |
|---|---:|---:|
| 앱 CPU초 |1.15344|1.11460|
| 경과초 |4.41472|4.46875|
| 앱 최대 RSS KiB |173920|165556|
| DB 문장 수 |60|60|

최대 RSS는8,364KiB(4.81%) 감소했다. CPU는3.37% 차이지만 경과 시간은1.22%
증가했으므로 처리속도 향상을 주장하지 않는다. 메모리는 DB digest·재수집 검증
**이전**에 기록했다. Python import와 이미 만든 snapshot은 포함하고 provider/browser
수집은 제외한다. DB 대기 시간은 포함하지만 DB 서버 CPU/RSS는 별도 미측정이다.
DB 문장 수60과 DBwall에는 준비용 CollectionRun INSERT1개가 포함된다. 저장 자체는59개다.
기존 대량 이력이 없는 빈 DB 표본이며 전체 운영 job·idle 절감 증명이 아니다.

6회 모두 주유소·가격·최신가격의 전체 열 DB digest가 일치했고 같은 snapshot
재저장 삽입 수는0/0이었다. 원문은 [측정 JSON](../audits/2026-10-18-fuel-memory-ab.json).
기존 집중54 PASS/2 SKIP와 실제 가격 INSERT 뒤 timeout→rollback→동일 snapshot
재시도1 PASS를 확인했다. 재시도에서 provider는 한 번만 호출한다.
최초 사용한 보조 venv에는 datagokr가 없어 pytest 테스트 모음을 불러오는 단계에서 실패했고, 전체
의존성이 설치된 공식 WSL venv로 재실행했다. 이 실패를 제품 실패로 숨기지 않는다.

## 전체 회귀 게이트

제품·테스트 후보 a0b789df0e3f6eab2fab48e7ec58ab995d0e33dd에서:

- WSL 전체:852 PASS/10 SKIP/8warnings,968.24초,exit0.
- WSL Docker 전체:852 PASS/10 SKIP/11warnings,1090.81초,exit0/OOMfalse.
- PostgreSQL16 bulk 집중:11 PASS/1 SKIP,111.91초.
- 추가 빈 snapshot·실제 가격 INSERT 후 rollback/동일 원본 재시도:2 PASS.
- frontend/admin 및 backend CI6개 SUCCESS. live2 SKIP는 통과가 아니다.

Docker는610개 후보 파일의 manifest와 실제 import 경로·설치 의존성 Git pin을 검증했다.
네트워크/Docker socket 없이 read-only 소스와 충분한 공간의 별도 임시 디렉터리를 썼다.
Ruff 별도 검사에서 기존 main 진단은 남아 있다. 같은 config의 기준19/후보18건,
코드·메시지 기준 새 진단0건이다. 무관한 기존 코드는 이번 변경에 섞어 수정하지 않았다.
[검증 증거](../audits/2026-10-18-fuel-memory-verification.json)를 참고한다.

ARM 격리 실측 6회와 아래 배포·live UI 수용을 완료했다.
전체 provider 수집·장시간 안정성 수용까지 완료한 것으로 표시하지 않는다.

ARM 최초 controller r1은 DockerRootDir 문자열이 `/mnt/media`로 시작해야 한다는
하니스 조건에서 중단됐다. 실제 `/var/lib/docker`는 NVMe bind mount였고, 컨테이너를
만들기 전 실패했다. 원문을 보존하고 r2에서 findmnt의 NVMe 장치, DockerRootDir과
`/mnt/media`의 동일 device 및 root filesystem과 다른 device를 검사하도록 수정했다.
제품 코드는 변경하지 않았다. daemon OFF와 외부 runtime 불변 조건도 유지한다.


## Odroid ARM 초기 저장 실측

제품 후보 a0b789df와 기존 운영 이미지의 기준 소스를 기준·후보 교대로 각3회 측정했다.
각 실행은 공식 Alembic0025를 적용한 새로운 전용 PostgreSQL16 DB를 사용한다.
기준/후보 app Python37파일 전체 해시를 각각 확인하며 변경 파일은
services/transport_collection.py 하나다. 실제 데이터 호출 없이 WSL과 같은 합성
11885개 주유소·59425개 가격, raw UTF8 8,713,255bytes를 사용했다.

| ARM 중앙값 | 기준 | 후보 | 변화 |
|---|---:|---:|---:|
| 앱 CPU초 |19.94450|19.82618|-0.59%|
| 전용 PG CPU초 |71.06854|70.78397|-0.40%|
| 앱+PG CPU초 |90.98612|90.56236|-0.47%|
| 초기 저장+commit 경과초 |153.86737|153.28544|-0.38%|
| 프로세스 최대 RSS KiB |171520|163072|-4.93%|
| worker cgroup memory.peak bytes |164491264|154791936|-5.90%|

앱+PG CPU 행은 실행별 합계를 먼저 구한 뒤 중앙값을 구한다. 각 열 중앙값의 합과
일치할 필요가 없다. CPU·wall 차이는 작아 처리속도 향상을 주장하지 않는다.
메모리는 commit 직후, digest/재저장 검증 전에 기록하며 import·schema 준비·이미
만든 snapshot을 포함하는 해당 프로세스 생애 최대치다. 저장 직전 RSS/HWM/cgroup
값도 원문에 남겼다. PG CPU는 저장+commit 직전/직후 전용 PG cgroup usage_usec의
차이이며 그 시간대 PG background 활동을 포함한다. 앱/PG counter 읽기는 순차적이며
원자적 동시 표본은 아니다. PG 초기화·schema 준비·CollectionRun 사전 INSERT·후속
검증은 CPU 측정 구간 밖이다. DB 문장 수60에는 사전 INSERT1개가 포함된다.

6회 모두 source37·raw hash·3개 테이블 전체 열 digest가 같고 재저장 삽입 수0/0이다.
각 표본의 worker/PG/socket3개가 정상 정리됐고, 전체 종료 exit0/OOMfalse,
외부 runtime 불변 및 daemon 존재/OFF를 확인했다. 새 이미지 설치 검증이나
운영 배포/UI 검증을 대신하지 않는다. 전체 provider job·idle·PG 메모리 감소는 미입증이다.

원문과 개별 case 경로·반복 값·검증 결과는
[ARM 6회 증거](../audits/2026-10-18-fuel-memory-arm.json)에 포함한다.
로컬 원문 JSONL SHA256은 ARM 증거의 raw_log_sha256 필드가 정본이다.
최초 r1의 사전 경로 판정 실패와 r2의 성공을 합쳐 단일 무실패 실행으로 표시하지 않는다.

## 2026-10-19 배포·live UI 수용

제품 a0b789df0e3f6eab2fab48e7ec58ab995d0e33dd로 ARM64 native 이미지를 빌드했다.
이미지는 sha256:5942696b548fad24eeae2943925c84387ff216fdcc46f31c536a8a4a865feb47이며,
별도 network-none/read-only 임시 실행에서 설치 app 소스37파일 전체 및 import origin을
검증했다. 이미지 revision도 같은 제품 SHA다. 설치 검증 자원은 정리하고 외부 runtime과
daemon OFF를 유지했다.

운영 전환 e3d795ce-798a-42d0-9d05-56430b00093a에서 backend와
dagster-code-server를 새 이미지로 전환했다. rollout exit0/PASS이며 기존 큐를 보존하고
daemon OFF를 유지했다. 배포 receipt의 새 CID/PID/start ticks가 UI 검사 시점과 일치한다.
admin/frontend 이미지는 이번 제품 변경 대상이 아니다.

배포 후 WSL Chromium1243 live UI34개가 모두 PASS했다. 로그인·권한·메뉴·지도 요청
완료·Dagster 실제 상태·선택 후 실패 상세·외부 링크·503/네트워크 오류 복구·
320/375/414/768/1440px·로그아웃·지도 요청 취소 신호 등을 확인했다.
검사 중 Transport 네 역할의 실행 상태와 daemon OFF는 유지됐다.
[빌드·설치 소스·배포·UI 원문 요약](../audits/2026-10-19-fuel-memory-deployment.json)에
34개 case와 원문 SHA256을 보관한다.

이 수용 기록을 PR #89에 포함한다. 기존 NOT_RUN은 당시 단계의 이력이며 현재 상태는
위 결과를 따른다. 합성 초기 저장 성능을 실제 provider 전체 job·호스트 idle·
PG 메모리·24시간 OOM/swap 개선으로 일반화하지 않는다. daemon 자동 재개나
Track1/2의 다른 미검증 운영 수용 완료를 뜻하지 않는다.

최종 배포·UI·문서는 concierge_closure_review_a와 concierge_closure_review_b가 독립 검토했으며 미해소 P0/P1/P2는 각각0건이다. 기존 제품 소스 리뷰와 별도의 최종 수용 검토다.
