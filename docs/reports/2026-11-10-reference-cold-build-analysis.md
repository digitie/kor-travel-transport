# 새 기준정보 본문 최초 구성 지연 상세 분석

## 결론과 반영 범위

사용자는 새 본문의 최초 구성12.43초에 대해 추가 수정 전에 상세 원인 분석을 요청했다.
제품d0c9010/API5bee4f97을 기준으로 분석했다. 이 작업에서 제품 코드·환경·스키마·운영 이미지·
일정·수집 상태는 변경하지 않았다. 운영 데이터는 읽기 전용으로만 조회했고, 쓰기 측정은 같은
Odroid의 전용 PostgreSQL 복제 fixture에서 수행한 뒤 정확 소유 CID/label을 확인해 제거했다.

주요 원인은 HTTP 첫 페이지를 보내기 전에 전체1466건의 주소·매핑·JSON·저장까지 동기로 끝내는
구조다. 지난 개선은 같은/인접15분 구간의 반복 조회 비용을 줄였지만, 최초·장기 유휴 뒤의 전체 구성은
그대로 남았다. 입력 지문도 상수 시간의 revision 조회가 아니라 실제 값 전체의 JSON/해시 집계다.

## 측정 방법과 한계

- 운영과 같은 API 이미지·Python/SQLAlchemy2.0.52·PostgreSQL18.6 ARM64·NVMe에서 측정했다.
- 같은 RR에서 철도1466행, 코드1108행, registry1행, source head2행, 주소1293행을 읽었다.
- 생산 DB 연결은 `transaction_read_only=on`, SQL10초/lock500ms 상한이었다. SQL 원문·bind값·키는 기록하지 않았다.
- 새 fixture DB에서 실제 제품 `_freeze_reference`와 첫 페이지 DTO/ETag/응답 함수를 실행했다.
  빈 snapshot→재사용→빈 snapshot→재사용을 교대했다. 초기화는 fixture cache에만 수행했다.
- 원천/주소/mapping과 canonical 내용 SHA는 네 번 모두 같았다. canonical1428193bytes,
  첫1000건 응답874170bytes, 전체1466건이다.
- fixture는 `shared_buffers=128MB/work_mem=4MB`, 운영은768MB/16MB였다. 둘 다 `fsync/synchronous_commit=on`이다.
- 이는 DB 데이터가 이미 적재된 상태의 application cold 측정이다. OS 냉기동·HTTP/ASGI·네트워크·
  당시 운영 부하·운영 테이블의 만료 정리 비용을 모두 재현한 것은 아니다.

**기존12.43초 요청에 사후 계측값을 정확히 배분한 표가 아니다.** 같은 입력과 코드의 두 격리
재현으로 원인 구간을 좁혔다. 과거 요청의 단계별 trace가 없으므로 나머지 차이를 네트워크나
잠금 때문이라고 단정하지 않는다. CPU는 Python 프로세스 CPU이며 PostgreSQL 서버 CPU가 아니다.

## 최상위 구간: 서로 더할 수 있는 시간

| 구간 | 첫 구성1 | 첫 구성2 |
| --- | ---: | ---: |
| transaction 준비·성공 head 조회 | 0.070초 | 0.034초 |
| 전체 snapshot 구성 | 8.746초 | 8.950초 |
| 첫 페이지1001행 읽기 | 0.272초 | 0.609초 |
| 첫1000건 페이지 DTO 검증 | 0.084초 | 0.131초 |
| commit | 0.007초 | 0.006초 |
| ETag/JSON 응답 생성 | 0.471초 | 0.178초 |
| 합계 | **9.651초** | **9.908초** |

재사용 경로는1.504/1.966초였다. 총 Python CPU는 첫 구성3.266/2.786초,
재사용0.550/0.565초였다. wall과 CPU 차이에는 서버 실행·통신·스케줄링 대기가 함께 있으므로
그 차이 전체를 디스크 I/O나 DB lock으로 해석하지 않는다.

## 8.75~8.95초 내부의 큰 비용

다음은 구성 구간 안의 계측이다. **주소 처리 시간은 원천 조립 안에, DB JSON 직렬화는 항목 저장 안에
포함된다.** 이들 중첩 수치를 다시 더하지 않는다.

| 작업 | 측정 범위 | 실제 작업량 |
| --- | ---: | --- |
| 입력 지문 확인 | 0.716~1.095초 | 실제 source/주소/code/registry의 JSON·SHA 집계 |
| 원천·주소·매핑 조립 전체 | 3.403~4.054초 | SQL13회, 최대400건씩4묶음 |
| 그중 주소 처리 | 1.769~2.893초 | 주소1293건 파싱·좌표키·필드 정리·DTO |
| snapshot 항목 저장 | 2.663~3.458초 | JSONB1466개, executemany4묶음 |
| canonical JSON 변환·재파싱 | 약0.535~0.961초 | dumps1466회와 loads1466회 등 |
| 저장 내부 DB JSON 직렬화 | 0.181~0.360초 | 다시 dumps1466회 |
| 만료 대상 탐색(빈 fixture) | 0.021~0.026초 | 해당 측정에서는 삭제할 기존 snapshot 없음 |

입력 지문 namespace 등의 작은 JSON 직렬화 일부는 지문 확인 안에 포함되므로 JSON 집계 수치도
독립 합계로 쓰지 않는다. 만료 대상이 있는 운영 GC의 삭제 시간은 이 빈 fixture 수치로 대체하지 않는다.

## 원인1: 첫 페이지가 전체 본문 생성을 기다린다

`export_references.py`의 첫 페이지는 `_freeze_reference`가 끝난 뒤에만 페이지를 읽는다.
`limit=1000`이어도 전체1466건을 구성·검증·해시·저장한 다음 첫1001행을 다시 읽어1000건을 반환한다.
원천 수량은 작아도 요청 경로에 materialization 작업이 직렬로 놓여 있어 응답 시간이 길다.

단순히 첫1000건만 먼저 구성하도록 자르면 다음 페이지 사이에 원천/주소/매핑이 바뀔 때 세대가
섞일 수 있다. 현행 불변 snapshot 계약을 유지하려면 전체 본문을 미리 확정하거나 원천 자체의
버전 저장이 필요하다.

## 원인2: 장기 유휴 뒤에는 같은 원천도 다시 만든다

`export_current.py`의 epoch는15분, 새 handle 수명은15~30분이다. `_freeze_reference`는
현재 epoch와 바로 이전 epoch만 조회하고, 만료 정리는 항목 본문도 함께 지운다.
따라서 source revision이 그대로여도 이 구간을 넘겨 다시 조회하면 전체 구성을 반복한다.
현재 본문 수명과 HTTP cursor 수명이 충분히 분리되지 않은 상태다.

철도 기준정보의 tracked 예약은 하루1회이고, 운영에서 Map의 실제 조회 간격은 별도다.
적어도 시간 단위·일 단위 간격으로 읽는 소비자는 이전1.81초 반복 조회 수치만으로 체감 속도를
예측할 수 없다. 지난 변경의 인접 epoch 복사는 이 유휴 구간을 해결하지 않는다.

## 원인3: 주소 처리의 Python 반복 비용이 크다

좌표가 유효한1293건마다 다음 작업을 다시 수행한다.

1. `AddressTarget` 생성과 좌표 유효성/정규화 키 계산
2. 저장 주소의 좌표키 대조, provider/payload/region 구조 검사
3. 문자열8필드 정리와 행정동 코드 확인
4. `ExportAdminAddress`1293개 생성 후 다시 dict로 변환

별도 CPU profile에서 좌표키 계산1293회, `_text`10344회, Pydantic 검증1293회,
model_dump1293회를 확인했다. async 함수의 profiler 호출 횟수에는 await 재개가 섞이므로
주소 함수를12번 호출했다고 해석하지 않는다. 실제 논리 호출은4회다.

주소 전체 JSON은732050bytes, 사용하는 provider/address/region으로만 투영하면532298bytes였다.
약27%를 줄일 여지가 있지만 데이터 전송량 절감만으로 주소 구간 전체가 사라지지는 않는다.
좌표키 검증은 오래된 좌표의 주소가 잘못 붙는 것을 막으므로 제거 대상으로 삼지 않는다.

## 원인4: bulk 호출이지만 실제 저장 경로는 행별 JSON 바인딩이다

실제 계측은400/400/400/266개의 네 executemany 묶음이었다. 현재 설치된 SQLAlchemy2.0.52
asyncpg dialect는 `use_insertmanyvalues_wo_returning=False`이며 이 INSERT에는 RETURNING이 없다.
기본 INSERT는 snapshot_id/ordinal/payload의 값 한 묶음으로 compile된다.
따라서 네 번 호출했다고 해서 네 개의 다중 VALUES SQL로 저장했다고 보면 안 된다.
드라이버 pipeline을 고려하지 않고 네트워크 왕복1466회라고 주장하는 것도 부정확하다.

추가로 `dict → canonical JSON bytes → json.loads → DB serializer의 JSON → JSONB`를 거친다.
내용 해시·상한 검산은 필요하지만, 중간 재파싱/재직렬화는 줄일 수 있는 후보다.
실제 다중 VALUES와 JSON 묶음 기반 INSERT를 같은 데이터·제약·순서·트랜잭션으로 비교해야 한다.
[SQLAlchemy의 executemany와 insertmanyvalues 설명](https://docs.sqlalchemy.org/en/20/core/connections.html#insert-many-values-behavior-for-insert-statements).

## 원인5: SQL1회인 입력 지문도 가볍지 않다

운영 SELECT의 `EXPLAIN (ANALYZE, BUFFERS)`에서 입력 지문은 계획16.918ms·실행1006.285ms였다.
source1466·주소1293·연결 code948·registry1행의 실제 값을 JSON으로 만들고 행별/집합 해시를 계산한다.
주소 집계 노드는545.978ms, code 집계는320.301ms였다. 자식 노드 시간이 포함된 값이다.

대표400건 원천 조회5.854ms, 주소 조회13.024ms, code 연결14.853ms였고 각각 기존 PK/unique
인덱스를 사용했다. 이번 계획의 shared read/temp spill은0이었다. 관측 시 해당 운영 DB의 다른
client4개는 idle/ClientRead였으며 Lock 대기는 관측되지 않았다. 이 관측을 과거12.43초 시점까지
소급해 잠금이 없었다는 증거로 쓰지 않는다.

이 측정에서 우선 근거가 있는 병목은 반복 JSON/해시와 materialization 경로다. 인덱스 추가,
work_mem 증가, MV 전체 refresh, fsync 해제를 먼저 할 근거는 없다. EXPLAIN의 노드 시간은
하위 노드를 포함하고 실제 전송/변환 시간과도 다르다. [PostgreSQL18 실행 계획 해석](https://www.postgresql.org/docs/18/using-explain.html).

## 수정 우선순위: 아직 구현하지 않은 제안

1. **본문과 cursor 수명 분리** — source·주소·매핑의 입력 revision에 묶인 불변 본문을 유지하고
   짧은 cursor는 그 본문을 가리키게 한다. 유휴 뒤에도 원천이 같으면 본문을 재구성하거나 복사하지 않는다.
   현재 본문·미만료 handle의 pin·GC 경계를 함께 설계하며 상태/실패는 계속 실제 head에서 읽는다.
2. **준비 시점 이동** — 성공 수집/주소/매핑 변경 뒤 새 본문을 준비하고 입력 revision CAS로 발행한다.
   요청에8~9초 생성 작업을 맡기지 않는다. 첫 준비·진행 중·실패 때의 API 계약도 명시해야 한다.
3. **저장과 주소 비용 감소** — 위의 실제 bulk 저장 대조, 필요한 주소 필드 투영, 반복 DTO/좌표키
   계산의 안전한 재사용을 검증한다. 순서·좌표 정합성·해시·16MiB/시간 상한을 유지한다.
   좌표 정규화 규칙은 기존 공용 라이브러리를 유지하며 backend에 복제 wrapper를 추가하지 않는다.
4. **전체 입력 해시의 대체 검토** — 모든 실제 writer와 관리자/주소/매핑 갱신을 포괄하는 DB revision이
   필요하다. 단순 last_seen_at/수집 성공 시각으로 바꾸면 누락 갱신을 숨긴다. 하나의 전역 행을
   매 원천 행마다 갱신하는 잠금 hotspot을 만들지 말고 source/도메인별로 batch 단위 전진을 검토한다.

위 제안의 개선율은 아직 측정하지 않았으며 제품 반영 성공으로 쓰지 않는다.

## 원장과 종료 검산

Git 밖 `transport-cold-analysis-20261110/`의 `profile.json`, `summary.json`,
`readonly-source-detail.json`, `driver.json`, `terminal-proof.json`이 정본이다.
최종 원장 `final-analysis.json`의 SHA는 `aef25b31a4ac885a037e16902808fe534b7f9671c2197ce43f5a2ab99a9a02f5`다.
정상 Manager G/R에서 실행한 분석 first `2259181ffcb94e24a32927ac06a279d1`은 실제0/done,
자식11개 종료·Main0·cgroup/PID부재·전용 PG 제거를 확인했다. 운영 다섯 역할의 CID/이미지/healthy도 같다.
운영 DB 쓰기·수집·추가 이미지·새 리뷰·SDK 변경·백업/복원·원본/영구통계 정리는0이다.

별도 제품 CI42727647602는 backend1813통과·2생략·33경고·54 subtest 통과,
frontend/관리자 성공으로 완료했다. live-e2e 생략과 실제 운영 HTTP 수용은 구분한다.
