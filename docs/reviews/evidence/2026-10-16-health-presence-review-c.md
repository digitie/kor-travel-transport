# Transport82 health EXISTS 독립 적대 리뷰 C

판정: SOURCE_PASS / 열린 P0·P1·P2=0. 원격 배포·전체 suite·CI·운영 CPU 감소의 PASS가 아니다.

- 기준 bde61206c2e3522624ba22ce5d28a9ec39762c5e / base15a928b07c7a30415cfa3d81ba5ee412e79981f5.
- 작성자 checkpoint f57fdfc202e09f03cbbfa7c1f07858e3d3b05bf553adba65ff2a2bc408efbe6f / 전체diff dc4c336be4d27dacbb8ecef50a6d532c1c02644c37b16fb1d096cf6f03928aa1.
- 실행ID transport82-review-c-3aa19e88-02c0-4b4c-b519-e6158c285b18, 시작2026-10-16T09:45:28.842407+00:00, 종료2026-10-16T09:47:37.095600+00:00.
- AGENTS/CLAUDE/SKILL·hostile-review/실패runbook·관련architecture/data-model/resume를 읽었다. immutable commit의Git archive에서검증하고작성자WT시작·종료clean/수정0을확인했다.
- A/다른reviewer 원문 미열람. 작성자근거문서는설명으로읽었으며benchmark/전체검증을본인검증으로합산하지않았다.

## 전체 검토 범위

변경5파일(main.py/newtest/문서3)의전체diff와정확blobSHA를checkpoint와대조했다. runtime AST는 sqlalchemy exists import와health의seeded query만제외하면원본전체와동일하다. DTO/라우팅·get_db 수명/예외middleware/provider·scheduler·Common pin·HC cadence·run/executor는변하지않았다.

backend/app/main.py779–786은 SELECT EXISTS(SELECT * FROM parking_snapshots) 한개의scalar를읽는다. PostgreSQL dialect로actualroute의statement를compile해EXISTS/FROM정확·COUNT/JOIN없음을확인했다. ParkingSnapshot.id는실제모델의NOT NULL PK다. 따라서동일MVCC-visible set에서 COUNT(id)>0과EXISTS는빈집합false/한행이상true로동등하다. SQL선택은read-only이며원천/인덱스/schema/transaction격리를바꾸지않는다. RLS/권한하에서보이는행범위도그대로따르고존재하지않는행을보이게하지않는다.

이검토는column별특수grant나RLS를실제Postgres에서구성한시험은아니다. SELECT * 안의열권한이특수배포에다르게영향하는지까지운영정본으로증명하지않았고,정상앱의전체테이블읽기권한을줄이는변경도없다. PostgreSQL optimizer가존재행하나에서멈출수있지만빈테이블/가시행없는deadtuple·RLS/heap상태에서는전체탐색이필요할수있으므로항상O(1)·고정CPU절감이라고하지않는다.

DB예외를잡아false로바꾸는분기는추가되지않았다. 실제health 함수에오류세션을주입하면동일exception이전파되고,실제ASGI에서기존500 problem+json/고정안전detail·원오류미노출을확인했다. status/database/seeded/release_sha의타입·값과HTTP200계약은보존된다. readiness를DB없는liveness로약화하지않았다.

## 본인이 실제 실행한 검사

1. 커밋archive의신규4회귀를conftest없는별도standalone 경로에서재실행: **4 PASS,0.93초**.0/1/1024행은자기tmp_path SQLite2개뿐이며TEST_DATABASE_URL빈값/SQLite임시flag·정확PYTHONPATH로격리했다.기본Weather/Transport공유fixture·PG접속0.
2. actualhealth AST/실제ParkingSnapshot·HealthResponse를사용한정상false/true·단일쿼리·정확DTO·Postgrescompile·같은오류전파·PK조건·0/1/1024/500000boolean동등·전체runtime AST정규화 **13조건 PASS**. 모델은DB/SDK/운영을실행하지않는다.
3. source import는본인archive/backend/app/models.py를지목하며main SHAe5fc5af49b5aa4cf6165fb2e6ce1755f21ec4171c518f76dd347abefe0d4c4af를확인했다. venv는읽기만했으며제품·의존성을수정하지않았다.

새시험의SQLite최소id테이블은health의쿼리/DTO회귀를검증하며실제Postgres planner/테이블폭·물리MVCC성능을대표하지않는다. 작성자nativePG16.14의50만행3쌍benchmark·초기환경실패보존/메모리상한/정상정리문서는이한계를명확히표기한다. 그수치를운영hostCPU개선으로확대하지않았다. 작성자fullbackend는D소유이며본인이재실행/poll하지않았다.

## 후속 gate

정확candidate CI·D전체backend/필수Docker2차·두독립리뷰·배포후실제health 응답/HC실행횟수·CPU초/업무freshness는별도다. PR81 미배포/pin/cadence변경과분리한다. 이번변경으로Transport Node/Chromium/daemon coldimport가해결됐다고하지않는다.

관련 원문: transport82-health-review-c-r1-20261016.context.json / .pytest.json / .models.py / .models.json.
checkpoint는transport82-health-exists-review-c-r1-20261016.checkpoint.json이며5파일·diff·조건별SHA를담았다. 모든도구terminal,운영접근·DB변경·SSH·Docker·provider요청·소스수정0.
