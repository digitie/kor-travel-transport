# 같은 트랜잭션의 Core stream으로 주차 이력 행 변환 CPU 축소

기준은 main `051bb46572334bbcdbec873db80081892e7f51c3`이다. `load_snapshot`의 max-ID 조회 뒤 같은 `AsyncSession`에서 `await session.connection()`을 얻고, 기존 SELECT를 그 connection의 공개 `stream()`으로 읽는다. ORM의 다중 열 tuple 재조립 경로만 피한다.

SQL·max-ID 상한·migration보다 live 우선·정렬·열 타입 처리·compact NamedTuple·공항 코드 재사용·2,048행 partition·sleep(0)·finally cursor close·Session 종료 후 to_thread는 유지한다. TTL30초·poll5초·캐시 generation과 원본 보존 정책은 바꾸지 않는다.

## 로컬 교대 측정

기존 공유 fixture의 전용 UUID DB에 합성50만 행과 최신 migration 중복1천 행을 넣고, 기준/후보·후보/기준·기준/후보 순으로 각 실행마다 새 Python 프로세스를 사용했다. 고정된 같은 x86 테스트 이미지의 Python3.12.13/SQLAlchemy2.0.52/asyncpg0.31.0, CPU quota2·메모리 한도1536MiB이며 ticker 주기는2ms다. 서버 캐시를 지우지 않았다.

| 쌍 | 실행 순서 | 전체 구성 wall ms | process CPU ms | ticker p95 ms | ticker 최대 ms | 전체 render 뒤 peak RSS bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline | 9204.2 | 4003.7 | 2.71 | 99.67 | 497438720 |
| 1 | candidate | 5589.8 | 3221.6 | 2.56 | 125.22 | 484294656 |
| 2 | candidate | 5366.8 | 3239.6 | 2.63 | 119.44 | 484544512 |
| 2 | baseline | 5883.2 | 3835.7 | 3.73 | 107.90 | 494014464 |
| 3 | baseline | 5550.3 | 3767.0 | 3.66 | 104.73 | 497266688 |
| 3 | candidate | 4992.8 | 3249.8 | 2.65 | 123.96 | 486891520 |

중앙값은 wall **5883.2→5366.8ms(-8.78%)**, CPU **3835.7→3239.6ms(-15.54%)**, ticker p95 **3.66→2.63ms**다. 반면 ticker 최대의 중앙값은 **104.73→123.96ms(+18.36%)**로 늘었다. 첫 기준 실행의9.2초에는 DB 캐시 상태 차이가 있으므로 첫 쌍의 큰 wall 차이를 효과로 일반화하지 않는다. RSS 중앙값497266688→484544512bytes는 이 합성 fixture의 관측값이며 운영512MiB 충족 증명이 아니다.

6회 모두50만 항목·max-ID501000·두 실제 SQL 문자열 SHA·전체 snapshot JSON 본문70860026bytes가 일치했다. 본문 SHA256은 `5b66808376e61b1769cb3743d2e8ec7cb9f2ec27037c3ddcc32f9e8f97e04477`다. 실제 운영 HTTP·ARM 결과·rail15초 timeout 해결이나 최악 지연 개선을 주장하지 않는다. 051b 첫5초 프로파일의 ORM 변환 비용 관측을 보완하는 국소 CPU 후보이며 그 요청의 전체 원인 설명은 아니다.

## 회귀 검증과 한계

기존 이력 파일의 관련 시험과 실제 PostgreSQL live/migration 우선순위·새 행 감지 시험, 같은 Session connection 사용 및 cursor→Session→CPU 순서 guard를 합쳐 **23PASS/0SKIP(51.58초)**다. 실패·취소 시 부분 게시 금지/close guard도 유지했다. 실제 Alembic head까지 전용 DB를 이행했고 benchmark/test DB는 finally에서 각자 삭제했다. 공유 fixture를 생성·중지하거나 운영 DB에 접근하지 않았다.

캐시 테스트 이미지의 오래된 KRIC 때문에 최초 collection이 실패했다. 기존 로컬 Git에서 lock의 정확한 `c006c8be64edfa4dc73cc3dd087c92cdeb9fba84` 소스만 추출해 테스트 import 경로에 연결한 뒤 통과했다. 설치·provider checkout 변경은 없었다. 동일 Ruff0.16.1 설정의 기준/후보 비교에서 기존 진단5개가 동일하고 신규 진단은0개다. 전체 lint PASS로 표시하지 않으며 무관한 정리·억제는 추가하지 않았다. git diff --check도 통과했다.

제품 SHA256 `f3834f079f2414394f375931231ea796a4614c12639b8c5c32e3916f4e010860`; 시험 SHA256 `d4631677b43385ef38d00cf2bffb5e69dbe79526798d11e72072499292b3e511`. 상세 실행은 작업 영수증 `transport-core-stream-work/benchmark-result.json`, `focused-result.json`, `ruff-baseline-comparison.json`과 frozen manifest에 보존한다. 두 집중 독립 리뷰와 정확 CI는 Draft 후속이며 운영051b QA는 별도 소유자가 계속 담당한다.
