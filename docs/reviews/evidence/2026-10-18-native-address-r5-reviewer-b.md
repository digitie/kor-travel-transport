# Transport native consumer r5 — Popper exact pin closure

**PASS_CONSUMER_SOURCE_AND_SCOPED_OWN_FIXTURES_ONLY. OPEN P0=0 / P1=0 / P2=0.**
원 r4 CONDITIONAL/REQUEST_CHANGES는 그대로 보존한다. r4의 유일한 a68 timeout 의존성 P2는 이번892 pin에서 CLOSED. 전체 CI/운영/실provider/daemon 수용 판정이 아니다.

## 불변 대상

- manifest **/home/digitie/dev/reverse-address-transport-native-review-delta-20261018-r5.json**, 관찰 SHA256 **fc7216458e4ead688dd1abaf916eea7dc155aa67868331f30f3e9608a9f6f809** (전달과 일치).
- 이전 **bb191137406b95a43f6ed8e477b35b786f88df0d** → head **3f5651772f7945e48b3d822898894f76814a69b4**.
- Common **89291f36d731ab906161b96757522e1cd833b4ef**.
- r4 본인 FULL **/home/digitie/dev/reverse-address-transport-review-popper-r4.md**, SHA256 **c47c59d5c8a6fc4528a852436b68664c7bedfc61ca4a2df9bc4696ebe7b27db6**를 계승한다. 다른 소비자/peer PASS로 대신하지 않는다.
- WSL Ubuntu-26.04 / immutable Git object / own temporary fixture만 사용. shared source/index/branch/WIP 수정0. 새 상대 r5 결과를 읽거나 요청하지 않았다. 최종 확정 UTC **2026-10-18T05:29:55.284160+00:00**.

## 전체 delta 확인

manifest changes와 실제 Git changed paths가 정확히 같다. 모든 제품/lock/health test는 **a68 문자열→892 문자열 역치환 시 이전 bytes와 동일**하다. 아래 SHA는 최종 Git blob의 SHA256이다.

- backend/pyproject.toml: **a5cc078e710215ce771fca2943888cb371798e046df88c97634d207ad4063ba7**.
- backend/tests/test_health_cpu_contract.py: **e40eefef2fb5bf3bf1cbaaac4eafb53de999225f37bbb5d303baa6d052651dd0**.
- backend/uv.lock: **a52416671d08ef898615e653a3d59c208ca95b872d74eebabdd965c6371cfe0f**.
- docs/reverse-address-refresh.md: **047274e21a46d2fb931e416b0971e3dbb272c0a348edb1149b77a725b304ad95**.

Common VCS dependency·lock rev/fragment·health installed provenance assertion이 같은892다. SDK/SQLAlchemy/다른 dependency version이나 extra 범위를 바꾸지 않았고 assertion을 약화하지 않았다. health Test/interval/timeout/start/retry, HTTP/body cap, admin auth/Origin/session/token, BFF route/scope·component·migration/DTO/OpenAPI·backend source selector·source preservation·page/retries/pending callback 모두 이전 r4와 byte 동일이다. 제품 변경이 없으므로 소유 BFF22/app 및 SQLite/schema5/app을 불필요 반복하지 않고 정확한 동일 source에 귀속한다.

guide는 이전 a68 failure 이력을 지우지 않고 새892의 공식 Pool.recreate/native 설정·listener 계승·원 pool 미대여·connection loss fencing 유지·최종 gate/운영 배포 전 범위를8행 추가한다. 늦은 POST unknown에 UUID를 보존하는 UI, NOT_STARTED resume, 단일 Node 프로세스 guard와 복수 replica 전역 admission 미보장 한계는 유지한다. Common webserver 선배포 후 소비자 Admin이라는 순서와 Daemon OFF가 유지된다.

원 T86-B-P2-01 legacy ferry admission, T86-B-P2-02 current source/좌표 MAX는 CLOSED 유지한다. 같은원천/NULL/admin_manual·legacy 제외·기존 파생행 숨김·같은좌표 실패 last-good는 r4에서 새a68로 검증했고,892의 해당 reverse_address.py/address_providers.py/address_dagster.py는 a68과 byte 동일하다. 전역 MAX로 되돌아가지 않았으며 sidecar/source/fact/lineage 변경0이다.

## OPEN 의존성 P2 closure의 본인 근거

Common41 원문 **/home/digitie/dev/common41-review-popper-r4.md**, SHA256
**a5a00903ea0154e9f1d746579a90b6d83cb867666c84f6f2d1ebb98189a9e151**.

본인이 정식 own .24/SQLAlchemy2.0.54(C ext=true)와 .25/2.1.3에서 실행했다. native NullPool/QueuePool 양쪽 statement_timeout80ms가 submission 안에도80ms이며 pg_sleep이 약81ms에 취소된다. 원 pool 전량 대여 중 별도 backend/원 checkout 증가0, same connection storage fencing/context restore, lock backend 상실 후 RuntimeError/row1/최종STARTED 및 동일UUID replay를 확인했다. 기존 eventlog 실패시도 한계는 authoritative RunStorage 상태 보존과 구분했다.

이 수치는 소비자 운영 PG나 실 worker 검증이 아니다. 공통 source closure에 더해 이번 소비자 pin이 정확히 그 제품으로 연결되고 BFF·source 동작이 변하지 않았음을 직접 확인했다.

## 새 소비자 연결 검사

새892 Git archive에서 독립 빌드한 **wheel58563B/SHA14dd0d99c97ad561c529722c9a64a8bf076920e25fc4d722226202980297dfc9**를 own venv에 설치한 actual create_schema를 썼다. 이 소비자 exact-head scope의 **3 GraphQL documents를 두 SDK에서 parse+validate**, errors0. native ExecutionMetadata에 runId 입력을 추가하지 않았고 requestId는 새 mutation으로만 들어간다. native query/selector/permission 입력 계약은 앞선 공통 own8 및 r4 전체 검토와 연결한다.

- .24/SQLA2.0.54 proof: /home/digitie/dev/common41-popper-r4-544a1y0p/consumer-r5-schema2454.safe.json.
- .25/SQLA2.1.3 proof: /home/digitie/dev/common41-popper-r4-544a1y0p/consumer-r5-schema25.safe.json.
- base(previous_review)..head diff-check EXIT0.
- 준비 도구에서 함수 실행 전 V8 ReferenceError1회가 있었으나 shell/제품/fixture 실행은 없었고 즉시 올바른 도구 코드로 정정했다. 제품/test failure는 아니다.

## 한계·미실행

이 narrow closure에서 full suite/실제소비자PG migration/새이미지·ARM build/native browser/provider/운영/SSH/Docker/daemon/실job은 NOT_RUN이다. r5 요청 당시 집중/nativeUI/CI는 진행 중이라고 전달받았고 manifest에는 완료 결과가 없다. 진행 중 CI를 PASS로 세거나 새 CI를 실행하지 않았다. 공통59 묶음의100/75초 NOT_COMPLETED와 특정 resume 단독1PASS/나머지own8×2PASS 한계는 위 공통 보고서에 보존되며 전체 PASS로 합산하지 않는다.

Source PASS는 부모의 merge/deploy 권한을 철회하거나 새 사용자 승인요건을 만들지 않는다. 별도 Common38 wholewheel/daemon CLI 보존과 운영 적용·공통 최종 CI/각 소비자 CI는 root 소유 별도 정산이다. 단일 Node process 한계를 없앤 전역 exactly-once·provider quota 전체·운영 CPU/메모리 개선을 주장하지 않는다.

## 실제 전달 요청 원문

Common892 검토 뒤 소비자r5 좁은delta finalbinding 부탁: Weather7f549f1257089c7c05d6ee63b412ca8a1bc00c67, Transport3f5651772f7945e48b3d822898894f76814a69b4. /home/digitie/dev/reverse-address-weather-native-review-delta-20261018-r5.json SHAd7365c30e49a34a46199ed4a3ae8d348247d5af1d31f91502faf17c7c8c825e8; transport대응 SHAfc7216458e4ead688dd1abaf916eea7dc155aa67868331f30f3e9608a9f6f809. pin/lock/healthassert+guide만, productBFF동일. 집중/nativeUI/CI새로진행.
