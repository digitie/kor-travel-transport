# 고속도로 소통 관측의 배치 조회·저장

## 2026-10-28 최종 코드·UI·성능 수용

PR [#155](https://github.com/digitie/kor-travel-transport/pull/155)는 검토·CI·후보 UI·격리 성능 검증을 마치고
main `c19d6bc93273b36427a05d9eb1827407b4ae9d6b`로 정상 머지됐다. 실제 검증 소스는
`65a185f8305516dc22835d76cc83567c92a25794`, 비교 원본은 준비 main
`8bc25638c44409cc04e3cf0586b27d5c0c69b312`다. 정확65a의 backend/frontend/admin CI는
두 실행에서6개 SUCCESS이고 live-e2e2개 SKIPPED는 아래 실제 UI 수용과 구분한다.
제품 두 독립 리뷰의 추가 차단 지적은 없었다. **운영 배포는 아직0이며 ARM 수집 효과는 미측정**이다.

### 최신 후보 UI39

Git822개 mode/blob·frontend243개+지도 gitlink1개를 검산하고, 입력이 같은 기존3bf의 실제 Next build를
새65a source/lab에 복사했다. manifest4/static59와 runtime47181개 hash/mode/link를 양쪽 대조했으며
새 컴파일을 했다고 세지 않는다. 실제 PG18/schema36·Common c289/frozen106/site9425에 결박한
API·BFF·브라우저에서 SSR/login/reload/menu/교통·유가 지도/타일/목록·모바일과 유가 통계
D-1/D-6·누락일·안내창을 포함한39개가 모두 통과했다. API15/tile40·page/console/HTTP/request/nav 오류0,
28.967초/정상 exit0다. 고정 합성 fixture의 후보 수용이며 운영 수집·provider·백업 검증으로 확대하지 않는다.

첫 UUID c44는 브라우저 시작 전 tunnels 단계에서11.184초/exit1로 실패했다. master-only로 실제 재현한
SSH mux 경로95+임시 suffix17byte 오류는 private cwd의 상대 control path로 고쳤다. Uvicorn 원 SIGTERM
재전달로 바깥 finally 기록을 보장할 수 없어 public shutdown 완료 직후 API 종료 영수증을 남겼다.
두 소스 리뷰 뒤 명시 승인된 새 UUID8f18 한 번의 성공이며 원 실패를 보존한다. API graceful 종료·network denied0,
PG CID/익명 volume·API/Next unit/cgroup·터널/control·C7 정리와 frozen 환경 전후 불변을 확인했다.
후보 API의16개 수집 관련 설정은 OFF로 격리했다. 제품 current 기본값·기존 commit/소유권 fence·
고속도로 advisory lock과 운영 설정은 변경하지 않았다.

### 격리 PG18 실측: 저장·commit 구간

Linux amd64/WSL·CPython3.13.14·동일 frozen106/Common c289·PG18에서 원본/후보를
AB/BA/AB 순서로 각3회 실행했다.8,302개 입력/8,300개 고유 관측의 신규·정정·원입력 재적용
각 구간에서 원본·후보6회의 전체 행 digest가 일치했다(총18측정). 신규 count는8,300/0/0이다. Alembic upgrade/check와6회 시험은 모두 exit0이며
정확 CID/name/label·volume1개와 소유 자식 정리, 소스/의존성 전후 불변을 수용했다.

| 구간 | 저장·commit wall 중앙값 원본→후보(초) | client process CPU 중앙값 원본→후보(초) | 표본 최대 RSS 중앙값 원본→후보(KiB) |
| --- | ---: | ---: | ---: |
| 신규 | 12.343→0.893 (92.77% 감소) | 8.269→0.582 (92.97% 감소) | 108,320→111,288 (+2.74%) |
| 정정 | 12.555→0.885 (92.95% 감소) | 8.315→0.542 (93.48% 감소) | 118,516→121,944 (+2.89%) |
| 원입력 재적용 | 11.883→0.868 (92.69% 감소) | 7.799→0.466 (94.02% 감소) | 130,024→133,348 (+2.56%) |

**표본 RSS는 감소하지 않았다.** 각 중앙값 차이는2,968/3,428/3,324KiB(약2.90/3.35/3.25MiB) 증가다.
RSS는20ms 표본 최대의 하한이며 client process CPU에는 표본 수집 비용이 포함된다. process 수명 전체
`ru_maxrss`는18구간 모두192,152KiB로 같지만 시작·검증·allocator 이력을 포함하는 별도 범위다.
PG 전체 child CPU 중앙값7.560→1.256초도 import/준비/검증/background를 포함하며 저장 구간 전용 수치가 아니다.
서버 RSS는 측정하지 않았다. 각3회·공유 PG cache·첫 원본 cold 효과와 배경 간섭을 포함하므로 일반적인
감소율·통계적 유의성·운영 ARM 전체 수집 저감으로 확대하지 않는다. 마지막 구간은 정정 뒤 원입력을 다시 적용하는 시험이다.
조회8,300→21은 이 시험의 source에서 유도한 lookup 호출 수이며 실제 SQL 이벤트 계측이나 서버 DML 횟수가 아니다.

첫 성능 r6는 outer를 제품 venv로 실행해 Docker SDK import가 없어 PG 생성 전4.89초에 실패했다.
소유 자원0·환경 불변을 확인하고 원 실패를 보존했다. 제품 환경에 SDK를 설치하지 않고 outer 제어만
기존 도구 venv로 분리한 r7을 두 독립 리뷰 뒤 새 UUID 한 번 실행했다. migration/probe는 계속 제품 c289 Python이다.

원 UI 수용 SHA256은 `ef1afc0600b92e5da57e157099951c2cbf120fb9bb00389674b5f0b4189722be`,
성능 raw는 `b9d501f3aff0574c68f633b81befbfde59a830a209c6a35c939c17c73201bc08`,
Root 독립 실측 검산은 `7554c83f92098f29fe6ee09c6680ff40748ac74f944546770c33eb8c90462f8f`다.
UI는 W/Root/T, 제품·CI는 Root/T, 성능 source는 J/Root/W의 역할을 분리했고 성능 실제 결과는 Root가 독립 검산했다.

## 아래는 각각 작성 당시의 준비·과거 소스 검증 기록


상태: 후보를 준비 시점 main `8bc25638c44409cc04e3cf0586b27d5c0c69b312`와 정상 합성했다.
batch 제품·회귀와 Python/Common c289 의존 lock는 보존했고 PostgreSQL18·schema36 및
주차 영구 통계 선행 저장/원본 삭제 차단·prebuilt 배포 계약은 upstream 원문으로 채택했다.
운영 변경은0이다. 아래 기존 검증은 각각의 소스·DB 버전·환경 이력이며 새 합성과 구분한다.

## 8bc256 통합과 기존 Next 재사용 검토

직전3bf의 코드 CI6개는 모두 SUCCESS, live2개는 SKIPPED다. b2fbb UUID의 실제 Next build는
정상 종료했고 Git809·manifest4/static59·소유 unit/cgroup 소멸을 수용했다. 실제PG/API/browser는0이다.
main8bc와의 프론트 전체 path·package/lock·입력 계약은 같아 기존 산출물 재사용 후보지만, 새 source/lab의
Git 전체 매니페스트와 frontend-input 동등·복사 영수증을 별도로 검증하기 전 재사용 완료라고 하지 않는다.
기존3bf source 아래 backend를 덮어쓰지 않는다. 새 API의 schema36/새 PG18에 맞춘 최소 하네스를
두 리뷰 후 실행하고, 기존PG16/schema35·32개 SQLite 결과를 새 버전 수용으로 바꾸지 않는다.

Python 패키지/uv.lock/Common c289와 traffic module은 동일하다. c289106/site9425는 전후 해시 확인으로
재사용할 수 있지만, Docker의 PGclient18 설치/실제 PG18·신규 schema36 검증은 별도다. 원본48시간 목표는
영구 통계 선행 저장 이후의 단계이며, 분석 읽기 전환·검산 전에는 운영 원본 삭제를 하지 않는다.
이번 준비 main은8bc로 동결하며 이후 진전은 원칙 후속으로 분리하고 최종 머지 전 다시 확인한다.

## 5c823 준비 기준 당시 검증 경계

직전 `516d4b21c053f97b0d85b370b9dbc1756bc38a18`의 backend/frontend/admin CI는 push·PR 각3개,
총6 SUCCESS이고 live E2E2개는 SKIPPED다. 그 소스의 후보 Next/PG/API/browser 기동은0이었다.
새 main의 자동 역 연결 backend3/admin3개 런타임 파일을 그대로 채택했으며, batch 제품과 신규회귀의
import/UTC 정리는 직전516 그대로다. journal·resume의 양쪽 추가와 main 본문을 모두 보존했다.

Common c289·pyproject/uv.lock·admin package/lock·Dockerfile/Compose·지도 gitlink·schema35가 같음을
Git blob으로 확인했다. 별도 c289106환경의 SQLite32통과8.64초·신규회귀/핀시험 Ruff 통과는516의 수용이다.
기존 수집 파일의 Ruff12개는 같은 도구·조건의 main에도 동일하여 이번 작업에서 고치지 않았다.
원 venv는 보존했고 새 환경9425파일·Common19·실제 import를 검산했다. 새 API 모듈·최종 합성 HEAD의
source/import·CI·두 리뷰·fresh Next/동일 API39 UI는 별도로 결박해야 하며 이전 UI 성공을 승계하지 않는다.

이번 빌드의 기준 main은 준비 시점5c823으로 동결한다. 빌드 중 새 upstream은 원칙적으로 후속 범위로
분리하고, 최종 머지 전의 진전은 다시 확인한다. 실제PG/Docker 재검증·CPU/RSS 실험·운영 배포는0이다.

## abd408/Common pin 합성 당시 검증의 범위

PR146의 Common pin `c289b4624c8640eb918cc915803e72ae754e58fb`와 정본 pyproject/lock·설치 핀 회귀를
그대로 합쳤다. batch 제품·회귀 blob은 `103a0e00fb727af31fc16261bd7113b8fa5ce3db`와 동일하다.
journal의 양쪽 prepend와 기존 본문을 모두 보존했으며 API·UI·배치 제품의 추가 변경은 없다.

기존 PG15(18.48초)·801/8,300개3단계 동등 검증은 제품 코드 `1788d6c`의 **Common e746** 환경이다.
103a는 그 코드에 문서3개만 더한 head였다. 추가 Docker 집중15개도103a/e746 frozen106에서23.62초에 통과했고,
Git798개 mode/blob·site9423개 hash/size·106개 version/direct_url·lock·실제 import 경로를 검증했다.
소유 준비/시험/PG 컨테이너·익명 volume·생성 의존성 이미지 정리를 수용했으며, 이는 cached CPython3.13.14
amd64 환경의 집중 회귀다. 공식 Dockerfile 전체·CI3.12·후보 API/UI·ARM 성능 수용으로 확대하지 않는다.
원 result SHA256은 `e34e5f4e3a1d55fef03f7516602af999a4545c45073e6ef501afef2ac70615d7`다.
첫 Docker 준비의5초 ReadTimeout(정확 하위 단계 미확정)과 두 번째 uid/mode0600 proof 읽기 실패는
보존한다. 세 번째는 실제 소유 uid1000으로만 고쳐 통과했고 권한·상한·검사는 완화하지 않았다.

103a CI backend/frontend/transport-admin3개 SUCCESS와 live-e2e SKIPPED도 과거 head의 결과다.
c289 합성 후 새 exact head의 실제 의존성 설치·집중 PG/Docker와 CI·두 리뷰·fresh Next/same-head API/UI를
다시 결박해야 한다. 기존 backend/.venv는 과거 증거로 보존한다. CPU/RSS 실험과 운영 배포는0이다.

## 변경과 보존 경계

`_store_traffic`가 관측마다 기존 행을 조회하던 부분만 최대400개 exact `(identity_key, observed_at)`
pair 조회로 바꿨다. 원 source 조건과 기존 unique key를 유지한다. 묶음마다 ORM 변경을 flush하고
기존 행 참조를 비워 일시 보유량을 제한한다. 전체 입력의 첫 중복 우선, 같은 수집 시각,
기존 PK 정정, 새 행만 세는 반환값, 원 raw/provider 필드는 유지한다.

SQLite의 저장 UTC 시각이 naive로 반환되는 경우는 UTC 기본값으로 정규화한다.
제공자 입력을 KST로 해석하는 경계와 혼용하지 않는다. KST `+09:00`와 같은 instant의 UTC 입력,
배치 경계 양쪽 중복, 파싱 실패의 단일 수집 시각 fallback과 뒤 배치 오류의 전체 rollback을 검증한다.

commit·원 실행 소유권/CAS·고속도로 advisory lock은 기존 호출자가 그대로 담당한다.
current OFF를 활성화하지 않으며 ON일 때는 같은 전체 pair 집합을 기존 current 갱신 함수에 전달한다.
최근2시간 통계 재집계·다른 수집·전역 잠금 구조는 이번 변경에 섞지 않는다.

## SQLite에서 관측한 조회 수와 값 동등성

803개 입력/801개 고유 관측을 같은 고정 시각으로 신규 저장·정정·재확인했다.
각 단계의 전체 행 JSON digest는 원본과 후보가 모두 같았다.

| 단계 | 원본 SELECT | 후보 SELECT | 원본 INSERT/UPDATE 관측 | 후보 INSERT/UPDATE 관측 |
| --- | ---: | ---: | ---: | ---: |
| 신규 | 801 | 3 | INSERT801 | INSERT801 |
| 정정 | 801 | 3 | UPDATE801 | UPDATE3 |
| 재확인 | 801 | 3 | UPDATE801 | UPDATE3 |

수치는 SQLAlchemy `before_cursor_execute` 이벤트 횟수다. `executemany`/`insertmanyvalues`의
행 수와 PostgreSQL 서버의 실제 DML 실행 수·왕복 수는 같지 않다. SQLite 신규 INSERT 감소나
운영 CPU/RSS 절감을 이 자료로 주장하지 않는다. 일시 ORM 객체는 묶음 상한을 가지지만
전체 payload와 중복 판정 set은 기존처럼 수집 입력 크기에 비례한다.

원자료: `transport-traffic-batch-sqlite-baseline-r2.json`
SHA256 `fc7dccbd36dca95ebe766db66e7d5372050bfea3d00442abe7d952bb0811981b`,
후보 `transport-traffic-batch-sqlite-candidate-r2.json`
SHA256 `6ec7e406ede0faa0619b7285cadd558ab8511e91e163820b4498ea476e742021`.
첫 probe는 필수 provider enum 누락으로 준비 단계에서 실패했고, 첫 pytest 호출은 작업 경로 오기로
수집0이었다. 두 실패를 성공으로 세지 않고 fixture·호출 경로만 바로잡았다.

## 격리 PostgreSQL의 정확성·배치 조회 수

동일한 PostgreSQL16·SQLAlchemy2.0.52·asyncpg0.31.0에서 원본 backend187개 파일을
Git blob/mode와 대조한 뒤 원본·후보를 같은 DB·고정 수집 시각으로 순서대로 실행했다.
801개와8,300개 고유 관측의 신규·정정·재확인6쌍 모두 전체 행 digest가 같았다.
신규 행 count·기존 PK·raw 필드와 시각 정정도 유지됐다.

| 고유 관측 | 원본 SELECT/INSERT 또는 UPDATE 관측 | 후보 SELECT/INSERT 또는 UPDATE 관측 |
| --- | ---: | ---: |
| 801 | 각801 | 각3 |
| 8,300 | 각8,300 | 각21 |

이 역시 SQLAlchemy dispatch 관측이며 서버의 행별 DML 수와 혼동하지 않는다.
이력·current와 배치 뒤 실패 rollback의 실제 PG 집중15개는18.48초에 모두 통과했다.
Alembic upgrade/check도 통과했고, CPU1·RAM1GiB·swap 총1GiB·PID128·loopback 전용의
소유 컨테이너·label·익명 volume1개는 정확 ID로 정리했다. 운영 DB·원천 호출·설정 변경은0이다.

원 result SHA256은 `a3415e37286b9c186374eea3f08ac0747b4ef0493097a385971f3a88b9b67acf`다.
첫 준비 시도는 저장소의 `core.autocrlf=true`가 `git archive`에도 CRLF를 적용해 원본 blob
검사에서 거부됐다. DB 생성 전 실패/cleanup PASS를 보존했고, 해당 export 명령에만
`-c core.autocrlf=false`를 넣어 같은187개 정본 bytes 검사를 통과시킨 뒤 새 UUID로 한 번 실행했다.
글로벌 설정·제품 코드·검사 guard·시간/자원 상한은 바꾸지 않았다.
SQLite 첫 기준선의 소스 SHA는 정본 LF의 CRLF checkout 변환과 정확히 일치하며 Python의
줄바꿈 정규화 뒤 같은 원 코드다. PG 기준선은 처음부터 canonical LF blob을 사용했다.

## 남은 수용

Python3.13.14·frozen lock의 새 회귀와 기존 traffic/current/collection 집중85개는
84통과/SQLite에서 실제 PostgreSQL advisory lock1건너뜀(324.52초)이다. PG 검증과 별도로 정확 lock의 Docker 회귀,
CI·두 독립 적대 리뷰와 live UI·실제 ARM 수집 전후 측정은 별도이며, 완료 전 운영에 배포하지 않는다.
