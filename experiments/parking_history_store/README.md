# TRN-04 공유 DB reader 초안

상태: **미연결 실험**. PR208의01~03+재구성 계측 위 별도 branch
`codex/transport-history-store-draft-20261118`다. API/Dagster/Alembic에서 import하지 않는다.
부모의 첫Transport배포 뒤 실제 재구성 구간 p95 판정 전에는 전환·migration·배포하지 않는다.
Weather DB export/snapshot 이관은 부모가 별도로 계속하며 이 초안은 그 작업을 바꾸지 않는다.

## 선택한 최소 구조

처음에는 `all / days=30 / br,gzip`의 자주 쓰는 무제한 응답만 독립 worker가 준비한다.
API가 기존500k행 객체를 다시 구성하지 않고 압축 bytes를 그대로 전송하도록 한다.
필터·다른 기간·identity·범위 만료·원본 변경은 기존 정확한 SQL fallback을 따른다.
이것은 응답값 보존 설계이며 fallback 비율·필터별 지연까지 개선했다고 주장하지 않는다.
운영 사용 분포와 필터별 1/7/30일·소형 요청 p95를 전환 전후 확인해야 한다.

행 전체 JSON을 DB에 복제해 API에서500k개로 다시 복원하면 GIL 부하가 남는다.
파일로 Python 객체를 pickle하는 방식도 같은 문제가 있고 사용자 요청인 DB 활용에서 벗어난다.
그래서 우선 bytes 전달 reader만 만들고 publisher/새스케줄/범용chunk 프레임워크는 구현하지 않았다.

## 실제 코드의 표와 reader

`draft_store.py`는 독립 MetaData에 실험표4개만 선언한다. 실제 Base에는 등록하지 않는다.

| 표 | 역할 |
| --- | --- |
| `draft_parking_history_source` | 모든 관련 writer가 같은 transaction에서 증가시킬 단일 revision의 후보 |
| `draft_parking_history_generations` | source revision·format·완결 여부·전체 bytes/항목 수의 manifest |
| `draft_parking_history_heads` | 현재 완료 generation 하나를 가리키는 FK |
| `draft_parking_history_payloads` | generation/scope/days/encoding별 압축 bytea와 정확한 cutoff 허용 범위 |

reader는 current revision = generation revision, complete, format, scope, days, encoding,
cutoff_from ≤ 요청cutoff ≤ cutoff_through를 모두 확인하는 **SELECT 하나**다.
맞으면압축bytes와metadata만반환하고,JSONdecode·압축·DB쓰기는하지않는다.
단일본문16MiB·generation64MiB·본문8개상한은제안이다. 코드의DDL제약은행별상한이며,
producer의실제자식수/bytes합계검증은아직없다. 전체512MB예산수용을뜻하지않는다.

## 필수 갱신 계약 — 아직 구현하지 않음

1. `parking_snapshots` INSERT/UPDATE/DELETE/TRUNCATE와출력의공항코드를바꾸는`airports`의writer를
   모두포괄해야한다. 제안은statement-level AFTER trigger가원본과같은transaction에서revision을증가시키는것이다.
   수집함수에만revision갱신을붙이면수동보정·직접SQL·import·삭제를놓치므로사용할수없다.
   DDL/trigger는현재실험에설치하지않았다. writer별무효화·잠금비용시험이선행한다.
2. `CollectionService.collect()`의원본commit직후publisher를요청한다.
   **기존 `_collect_airport_with_analytics`의분석계산보다앞**이어야한다. 느린analytics뒤나
   `prepare_reference_exports`뒤만연결하면원본직후준비가아니다.
   파생준비실패로이미commit한원본을rollback하거나수집성공을전체실패로바꾸지않는다.
3. API의현재revision확인은최대5초마다,마지막성공확인이30초를넘으면shared본문을사용하지않는다.
   이독립reader는매조회DB revision을확인한다.30초local재사용/5초확인통합은아직미구현이다.
   5분수집schedule을heartbeat로삼지않는다.수집외writer/재시작/준비실패를보충하는독립복구경로가필요하다.
4. publisher는시작revision을고정하고원본SQL의DISTINCT ON·live우선·동일시각정렬을보존한다.
   스트리밍행을작은batch로읽어canonicalJSON을증분gzip/br압축하면500k객체동시보유를피할수있다.
   전체재구성중source행잠금을잡지않고,최종publish의짧은transaction에서revision재확인과head CAS를한다.
   변경되었으면결과를게시하지않는다.원자적자식수/bytes/digest완결검증뒤에만head를교체한다.
5. 단순한30일blob도**시간이동에따라cutoff를잃으면안된다**.
   준비시coverage_start부터첫포함관측시각까지의cutoff만동일본문을뜻한다.
   직전제외관측이있으면최소cutoff는그시각+1µs와coverage_start중큰값이다.
   이범위를벗어나면revision이같아도miss이다.publisher는최초관측의범위경계만료도다시준비해야한다.
6. boundedGC는current head를보존하고이전generation한개씩만삭제한다.
   old+new≤2generation과총상한을강제하고,GC장애때무한히새generation을쌓지않는다.
   이reader는단일SQL로본문bytes를받으므로후속cursor pin은없다.이전reader는PostgreSQL MVCC로보호한다.
7. API의전송동시2·64KiB backpressure·취소시슬롯반환과기존응답/압축/신선도헤더를유지한다.
   API512MB와publisher peak/RSS·조회중소형요청p95·generation저장량을실측한다.

## 확인한 것과 남은 것

로컬임시SQLite의독립시험8개는정상bytes전달/다른writer revision/미완결/format변경/
범위·encoding불일치/cutoff양경계와SQL1회·읽기전용계약을검증한다.
다른writer는시험에서revisionUPDATE로모사했으며실제trigger를검증한것이아니다.
PostgreSQL경쟁publish·CAS·FK·GC·publisher·API통합·운영성능은미구현/미검증이다.
이초안을그대로배포할수없다.단순한reader와구체적인준비/무효화계약까지만제공한다.

```bash
PYTHONPATH=. /원본체크아웃/backend/.venv/bin/python -m pytest \
  experiments/parking_history_store/test_draft_store.py -q
```
