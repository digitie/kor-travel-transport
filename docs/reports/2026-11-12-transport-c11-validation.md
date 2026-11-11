# Transport C11·Scope2 최종 실행 검증 — 2026-11-12

C11 최초 릴리스 bytes를 유지한 ef7bd62의 새 native/Alpine build와
각 production Chromium public4/admin18이 모두 통과했다. 기준 source의 원A/B와 CI도 통과했다.
추가 변경은 실제 발견된 비동기 E2E readiness 보강2줄과 이 검증 기록뿐이다.
제품 runtime·manifest·lock·vendor·backend/Compose/배포 source는 ef7bd62와 같다.
후속 보강 커밋의 CI·리뷰 delta와 실제 merge/배포는 별도다.

## 동결 산출물·설치

공통 PR49 main e8ed3ae75000be5cd22a3a11492bd97660635d78에 병합된 최초 릴리스의
UI0.2.0/tokens0.1.1을 사용한다. pack source는 a35481349d6747b4f13b958ae64d9c0bbd0b5413이다.
원장의 pack 당시 CANDIDATE_NOT_RELEASED metadata도 포함해 부모 원본 bytes를 보존했다.
동일 버전 재pack이나 산출물 수정은 없다.

공식 @radix-ui/react-focus-scope@1.3.1+kortravel.fix.2는 직접 runtime file/루트 override로 고정한다.
source1752a539,33511bytes,SHA256
1ca04870692565c243130d99c3dba91f3ac853ab2ec9538fc7b658b17fb7b49a다.
VWorld core1.0.1/web1.0.3, LightningCSS1.33.0+nativecss.fix.4도 같은 canonical bytes다.
미사용 fix1 vendor 두 개는 참조 부재를 확인한 뒤 제거했다.
중앙 workflow code/common-ref는 exact55a921b55d248106cbe320e7f5305f3d3cdb60fe다.

인수 후 및 fresh N150 설치에서 public153/admin263 파일 모두 tgz와 exact였다.
최종 Alpine 이미지에서도 각각153/263 파일의 SHA256을 모두 대조했다.
installed/external canonical guard와 strict peer 설치가 통과했다.
WSL node_modules/.next symlink 대상은 보존했고 root에서 큰 install/build를 실행하지 않았다.

## 실제 gate

| gate | public | admin |
| --- | --- | --- |
| 부모 C11 전체 unit | 164 PASS | 356 PASS |
| 기준 ef7 실제 CI unit/build/type/lint/Doctor | 164/성공/경고0 | 356/성공/경고0 |
| N150 fresh native build | exit0 | exit0 |
| native Chromium | 4 PASS | 18 PASS |
| fresh Alpine build | exit0 | exit0 |
| Alpine Chromium | 4 PASS | 18 PASS |
| Alpine 실제 패키지 파일 | 153 MATCH | 263 MATCH |

최종44개에 skip/flaky/unexpected는 모두0이다. 브라우저는 원래3개 admin spec과 public spec의
assertion·timeout·worker1 계약을 유지한다. Node는 native22.22.2, Alpine22.23.1이며 npm12.0.1을 사용했다.
N150 builder 이미지 tag는 public=transport-c11-public-harvey:ef7bd62,
admin=transport-c11-admin-harvey:ef7bd62다. 실제 image ID는 검증 JSON에 고정했다.
QA 이미지이며 운영 배포 이미지라고 보고하지 않는다.

기준 source ef7의 [일반 CI43084745064](https://github.com/digitie/kor-travel-transport/actions/runs/43084745064)는
backend/frontend/admin 모두 SUCCESS다. backend 원문은1548PASS/2SKIP/6warnings·2875.08초다.
[중앙 정책43084745441](https://github.com/digitie/kor-travel-transport/actions/runs/43084745441)의 두 표면도 SUCCESS다.
Draft live-e2e SKIPPED는 PASS에 합산하지 않았다. 후속 test/docs 커밋의 CI는 이 기준 CI와 구분한다.

## 최초 native 실패와 보강

원본 admin18은17PASS/1FAIL이었다. 375px 버스 화면에서 출발·도착 검색 클릭이 기존45초 제한에 도달했다.
trace의 immediate isVisible 호출은11143.623ms에 false를 반환했다.
그 순간 MapFilter trigger DOM은 없었고11332.706ms snapshot에는 생겼다.
BusJourney의 TransportMap은 ssr:false 비동기 import라 최초 표시 전 분기가 필터 열기를 건너뛰었다.

기존 조건 분기 앞에 expect(filters).toBeAttached() assertion을 추가해 실제 마운트를 기다린다.
제품 코드·기존 assertion·timeout·retry·skip을 바꾸지 않았다.
기준 native build 입력306개 중 해당 E2E1개만 달라졌고 나머지305개는 같다.
보강 뒤 전체 admin18 native와 별도 fresh Alpine18이 모두 통과했다.
첫17/1을 통과로 덮지 않고 원 trace·화면·JSON을 보존했다.

## 원A/B·원문·종료

원본 C11 batch1 manifest c0affe2a88bf0f176abb0e3df298b0fb2da698f442f74196f00ac3e237f30a4c의
Mill/Epicurus 원A/B는 ef7 source/package PASS, 신규0이다. 구현자의 점검을 독립 리뷰로 세지 않았다.
위 E2E/doc 추가 delta는 원 판정과 별도 입력으로 보고한다.

[검증 JSON](2026-11-12-transport-c11-validation.json)에 actual stats·image ID·원문 SHA256을 기록했다.
로컬 원문은 validation/transport-c11-n150-checkpoint와 transport-c11-n150-final,
remote 원문은 /var/tmp/transport-c11-harvey-ef7bd62dd81c다.
본인 native 서버 종료143과 QA 컨테이너2개 exited143/runningfalse,
activeOwnedProcesses0을 직접 확인하고 슬롯1을 반환했다. 이미지·원 실패 증거는 보존했다.

부모 최초 installed guard의 잘못된 KT_REQUIRE_CANONICAL 호출 거절과 guard-final exit0도 보존했다.
backend source가 같으므로 기존 전체 WSL1511PASS/39SKIP·Docker1508PASS/42SKIP를 보존했고
metadata만을 이유로 로컬 전체 backend를 반복하지 않았다. 새 GitHub CI1548/2와 섞지 않는다.

## 공식 배포 준비

최종 canonical main merge40을 source로 기존 공식 deploy-prod.sh --host와
deploy-transport-admin-prod.sh --host를 설치된 Manager G driver/current receipt/pin 아래 실행한다.
UI-only는 영향 최소화 선호이며 hard 제한이 아니다. 공식 entry가 Transport 소유 backend/code/gateway를
함께 재시작해야 하면 실제 운영 기준선과 source/lock/same-schema 불변을 확인해 승인 범위로 수행한다.
요청하지 않은 migration, DB/RustFS·공용 daemon·다른 target lifecycle은 변경하지 않는다.

저장소 루트 context·NVMe·기존 secret/env/backup·Transport만의 instigator drain/복원을 지킨다.
Aquinas와 normal SDK991 설치 receipt 및 Geo/Weather형 external G driver의 Transport official entry 연결을 조정한다.
strict prebuilt를 쓰면 공식 stage 뒤 genuine receipt를 가진 기존 remote child를 사용한다.
private 실행 계획은 validation/transport-merged-deploy-private.md, 계약 요청은
transport-manager-ui-promotion-request.md다. raw Compose·수동 receipt/adopt로 우회하지 않는다.
현재 실제 merge SHA는 없고 운영 배포는0이다.
