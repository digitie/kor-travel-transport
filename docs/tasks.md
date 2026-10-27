## 2026-10-27 — 지난 10일 Codex PR 리뷰 후속

- [ ] T-REVIEW-10D-01 — 리뷰 통합 수정 PR(`review/codex-10d-transport`, T01~T20): 소유자 승인 뒤 머지한다.
  운영 배포 때 T01 compose 앵커(API·code-server 같은 플래그·범위)와 T05 rollback 정책(스키마 불변·code-server
  단계 실패에서만 자동 rollback)이 같은 release로 들어가는지 확인한다. 외부 운영 controller도 같은 두 조건을 따른다.
- [ ] T-SEC-UIPW-01 — (소유자) 공개 저장소의 운영 관리자 UI 비밀번호 리터럴: 운영 값 회전과 보호 environment Actions
  secret 등록 뒤 저장소 리터럴을 secret 참조로 바꾸고 history 정리를 검토한다. 값은 문서·로그에 옮기지 않는다.
- [ ] T-PARK-03 — #144 반영 뒤 공항 op의 분석 캐시 재계산 주기·watermark 기준·직접 계산 fallback single-flight를
  재측정한다. 여전히 5분을 넘으면 별도 job/sensor 분리를 설계한다.
- [ ] T-RAIL-04 — 퇴역한 `rail_station_references` 행의 현재 집합 정의·수동 매핑 의미·FK 재계산·Map 철도 export 정합을
  함께 정하는 별도 PR.
- [ ] T-DEPLOY-02 — 배포 중 Transport instigator pause/restore·QUEUED drain을 스크립트로 옮길지 외부 controller와 결정한다.
  code-server 정본 포트 14005→12306 정리는 Manager의 odroid override 소비 확인 뒤 한다.
- [ ] 소유자·설계 결정 대기: OPINET 통계 모집단의 사라진 주유소(공용 퇴역·신선도 정책), KRIC 계획 시간표 48시간
  신선도와 수집 예산, 고속도로 통계의 전체 주기 서버 집계(새 API), Map T2~T4 `last_attempt_failed`·급감 override·
  parking 신선도 기준, 일반철도·ITS 결정적 오류의 provider 실패 분류. 세부는 리뷰 통합 PR 본문의 보류 표를 따른다.
- [ ] Common·별도 PR 대기: reverse_address keep 규칙(Common), MapReadout 좌표 live region(Common), 관리자 e2e 정비,
  메모리 한도(#93), 이미지 크기·빌드 시간(#81), 목록 상한 안내(#128).

## 원본 JSON 변환 국소 CPU 후속

- [ ] T-CPU-PLAIN-01: `_plain_json` 정확 builtin scalar 조기 반환 후보의 결과·오류·identity를
  보존하고 scalar/중첩 bulk CPU·RSS·bytes를 대조한다. 정확 builtin6줄과 원본/후보31회귀·
  국소 합성 계량을 확인한 PR #138은 최종 CI·두 독립 리뷰·머지와3691 운영 소스·공개 UI32를 수용했다.
  전체 수집 CPU/RSS 효과의 실제 비교는 남아 있어 후속 과제는 열어 둔다.
  [설계·검증 원장](reports/2026-10-26-plain-json-scalar-cpu.md).

# tasks.md — parking-radar 백로그


## 2026-10-26 — Manager instance 정본 전달

- [ ] **T-DAGSTER-INSTANCE-01** — #139의 CI·두 리뷰·머지와 Odroid Transport CS의 정본 a7 read-only 소비·운영 복구 계약은 수용했다. 공용 plane c444→a7 수렴과 다른 소비자/호스트의 effective 일치는 별도 미완이다. [소비·복구 범위](reports/2026-10-27-integrated-production-rollout.md).


## 2026-10-25 — 조사 기반 지도·이용 흐름 후속

[사전 조사](research/2026-10-25-mobility-ux.md)와 [설계·선행 관계·수용 조건](design/2026-10-25-mobility-improvements.md)을 따른다.
아래는 문서 PR에서 구현 완료로 세지 않는다. 과거 10/12지표 목록보다 이번의 이용 결정·실제 동작 수용을 우선한다.

- [ ] **C-MAP-01 / P0** — Common 담당: Map 기준 외곽/가용 높이·상세 슬롯·프로젝트 테마 계약과 Map 회귀·패키지 인계.
- [ ] **T-MAP-01 / P0** — 모든 Transport 지도에 동일 작업면 적용, 모바일 접근·반복 안내·주소/외부 복귀·프로젝트 톤 수용.
  첫 작은 묶음에서 공용 navy/dark 토큰·단일 stage 테두리와 유가 요약/메타를 적용했다([PR131](https://github.com/digitie/kor-travel-transport/pull/131)).
  Common dev.8·9경로 작업면/상세 슬롯은 [PR132](https://github.com/digitie/kor-travel-transport/pull/132)의 main `1d807fd`에 머지했다.
  275단위·74UI·실제 API/타일8개+무좌표2개·두 독립 리뷰와 전체 CI를 수용했다. PR132 당시 운영 배포는 미완이었다.
  Map 본체 소비자·실기기 수용은 계속 미완이며 Transport 운영 배포는 아래10월27일 기록에서 완료했다.
  10월27일 `7f01b013` 배포 뒤375/1440의9경로 외곽과 Firefox map/fuel 실제 타일을 확인했다.
  초기 유가 로딩 중30px 변화·고속도로roads429는 보존하고, 모든 지도 데이터/전체 소비자 성공으로 확대하지 않는다.
  4d 운영의 Firefox375 map/fuel은 실제 타일18/18·38/38·565px stage와 핵심 조작을 수용했다.
  map401 원인·map 상세 NOT_RUN·fuel 명시 선택 후 PNG 조회 중과 실기기/다른 소비자 한계는 남긴다.
  [4d 수용 범위](reports/2026-10-27-flight4d-production-acceptance.md).
  [전후 치수·검증 원장](reports/2026-10-25-map-workspace-layout.md). 최종 모든 소비자 수용 전까지 완료 처리하지 않는다.
- [ ] **T-RAIL-01 / P0** — 일반/도시철도 실제 시간표 실패를 코드 연결·권한·참조·수집·요일·신선도로 분리 재현.
- [ ] **T-RAIL-02 / P0** — 일반철도 참조 준비/정상 ID 조회와 지도 역→시간표 선택 연결, 실제 지원 구간·차종 수용.
  [10월27일 읽기 조사](reports/2026-10-27-rail-flow-audit.md)는 기존 구현·당시89편 성공과 현재 cold 참조/선택 연결 단절을 구분했다. 운영 재현·복구 완료가 아니다.
  별도 자동 참조 갱신의 provider 없는 preview/apply는 설계·순수 core 개발 중이며 운영0이다.
  참조 준비·일반철도 실제 시간표 전체 수용을 이번4d 운영으로 완료 처리하지 않는다.
- [ ] **T-RAIL-03 / P0** — 도시철도 매핑·달력·저장/이후 편·방향 복구 및 실제 두 노선/기관 수용.
  KR/K4 복합 이름의 표기 차이만 정규화하는 [작은 수정](reports/2026-10-27-rail-composite-alias.md)은
  실제 FK·요일별 저장 시간표 수용과 분리한다. 직접1251↔P313 공식 대응 행은 없으며 task는 계속 열어 둔다.
  PR149 exact536a328은 전체 WSL1314통과/2건너뜀·Docker1310통과/6건너뜀·794파일 불일치0·CI6개·두 SOURCE
  재확인 뒤10:14 UTC main ca59458에 머지했다. 150도 포함한 이 main은 운영4d와 다르며149·150은 미배포다.
  [최종 소스/운영 경계](reports/2026-10-27-flight4d-production-acceptance.md). 초기93%/머지 미완 기록은 당시 이력이다.
- [ ] **T-PARK-01 / P0** — 기존 job/run·원본·이력·cache·outlook/API 시각 대조, 원시/파생 정지 원인 재현.
- [ ] **T-PARK-02 / P0** — 확인된 수집→분석 단절 복구, watermark·부분 성공·멱등/재시작·캐시 신선도 수용.
  기존 Dagster 경로에서 current5/cache80 불일치를 정상·부분 성공으로 재현하고 원본 commit 뒤 갱신·신선도 검증을
  적용한 PR134는 main `f5f96ef`에 머지했다. 소스별 전체/집중 검증·CI·두 코드 리뷰는 완료했으나 운영 자연5분 tick의
  원본/run/cache/API 시각·값 대조는 미완이다. 성능·공식 요금·Firefox 첫 opening UNKNOWN/실기기 확인도
  [통합 인계](reports/2026-10-26-parking-admin-integration-acceptance.md)에 남겼다. [복구 검증 원장](reports/2026-10-25-parking-analytics-refresh.md).
  10월27일 자연 job SUCCESS와14공항44개·김포 기본 캐시0→24행을 확인했으나,
  분석 순차 계산 약9분이5분 주기를 넘고 최초 모바일 분석은504였다. 새 관측·신선도·성능 수용 뒤 닫는다.
  이후 엄격한 두 관측에서는 자연 run3023·새 적재·기본 캐시24행의 시각과 watermark 갱신이 통과했다.
  파생 구간 약395초로5분 주기 초과가 남아 이 task 전체를 닫지 않는다.
  [실제 배포·수용 기록](reports/2026-10-26-parking-production-rollout.md).
  #144/3691에서는 baseline 뒤 자연 두 실행과 새 김포10개·기본24cache·6범위 갱신을 수용했다.
  실제 cron은5분이다. 첫 모바일 주차 UI·HTTP 값/응답 성능과 CPU/RSS 효과는 별도 미완이며,
  analytics ready와 flight 대기 분리 후보를 남긴다. [최신 수용](reports/2026-10-27-integrated-production-rollout.md).
  별도 최초 모바일200/12.971초·후속Firefox0.876초, 이후 네 run의 원본 저장→종료105.370/86.421/95.672/87.484초와
  전공항14/58범위/232행의 최신 원본 반영도 확인했다. 콜드 지연과 늦은 비행편 응답 UI 후속이 남아 전체 task는 열어 둔다.
  [추가 검증·현재 한계](reports/2026-10-27-parking-cache-rollout.md).
  앞 문단들은 PR134/144 당시의 수용·미완 이력이다. 이후 PR147/4d 운영 뒤 자연 예약 SUCCESS3개·
  김포 새15행/6범위24cache 갱신, 최종14공항/58범위/232행의
  TTL과 최신 원본 반영을 함께 수용했다. 중간 TTL유효·3181세대 반영 상태에서 최신3182세대를 반영한 공항0/14도 보존했다.
  원본 finish→job end74.552/75.936/83.055초는 정확 캐시 commit 시각이 아니다.
  Native/Firefox 네 화면의 늦은 항공편 성공 복구와 최초 주차 분석 콜드12.971초/CPU 한계는 별개다.
  [4d 배포·실제 화면·자연 갱신 정본](reports/2026-10-27-flight4d-production-acceptance.md). 상위 task는 계속 열어 둔다.

- [ ] **T-FUEL-01 / P1** — 지도 상부 작은 bbox 요약·compact 주유소 상세·주소/출처 i·동일 필터 집계.
- [ ] **T-FUEL-02 / P1** — 기존 저장 이력 기반 7일 여러 유종 차트·최신 가격 직접 표시·결측/효력/모바일 표, 휴게소 이력 공백 별도 수용.
- [ ] **T-FUEL-03 / P1** — 기존 품질/시설 flag 의미 확인·API 필터/투영·선호 저장·공식 조건에 맞는 브랜드 마커/상세 자산.
- [ ] **T-FUEL-04 / P1** — 유가·변화·지역/관심 후보 추이 우선 통계, 가정 운영비 계산 후순위.
  PR150 exact19e35fd의 저장 history 비교일·평균 변화 UI는 WSL/Docker291·fixture375/1440·두 SOURCE 리뷰와
  PR CI를 수용해 main a15에 머지했다. 별도 push workflow backend pending 이력과 실제 운영 미포함을 구분한다.
  브랜드/관심 후보·운영 가격 수용은 남아 전체 task를 닫지 않는다.
  [비교 계약](reports/2026-10-27-fuel-history-comparison.md), [main/운영 구분](reports/2026-10-27-flight4d-production-acceptance.md).
- [ ] **T-HWY-01 / P1** — krits SDK 우선 도로 방향·구간·사고/CCTV 연결과 실제 범위/시점 수용.
- [ ] **T-BUS-01 / P1** — 양방향 연결 후보·미조회/전체 검색·고속/시외 실제 시간표 및 경쟁 응답 수용.
- [ ] **T-AIR-01 / P1** — 마중/출국의 항공편·터미널 주차 연결과 관측 패턴·상태/시각·요금 수용.
  PR147/4d의 실제 늦은 항공편 응답·365그룹마커/DOM과 별도8초 대기 재생은 수용했다.
  outlook은 현재 화면에 없어 NOT_APPLICABLE이며 구현/수용 완료가 아니다. 연결·패턴·요금 상위 범위는 미완이다.
- [ ] **T-ACCESS-01 / P2** — 확보된 역/휴게소/항구 접근·시설 자료의 시점/범위와 공식 안내 연결.

- [ ] **T-OPINET-30** — 클릭150~850ms 적용 후 전국 수집 약62분(2026-10-25 08:03~09:05 KST)의 추가 병목을 확인하고30분 목표를 검증한다. [관측·운영 원장](reports/2026-10-24-vadahub-ferry.md).

진행 중/예정(`[ ]`) task만 두는 백로그다. 완료 항목은
[`docs/tasks-done.md`](tasks-done.md)에 이동하고, 현재 진척과 다음 작업은
[`docs/resume.md`](resume.md)에 기록한다. 작성 규칙은 [`docs/tasks-rule.md`](tasks-rule.md)를
따른다. 2026-09-06에 사용자 요청으로 shadcn/ui 전환 + 과거 자료 조회 + Hallmark
재감사/재설계 initiative(T-033~T-038)가 추가됐고, 2026-09-07 `T-038`(마지막 phase)
완료로 이 initiative 전체가 끝났다. 계획 전체는
`C:\Users\digit\.claude\plans\iridescent-finding-parasol.md`에 있다.

## 진행 중인 작업 인덱스

- [ ] 이용 목적 중심 관리자 7~11번 수용: 홈/분류 메뉴·12지표·일반/도시철도·버스·공항·정보 버튼/모바일 지도·ITS 선택 노선 선형 지도 구현의 최종 PG/Compose/CI/독립 리뷰를 마감한다. 전국 버스 전체 연결·미확인 터미널 좌표는 별도 미완료다. 순수 UI 호환분은 PR127로 main34f8fab에 머지했고 빌드·배포는 다른 담당이 진행한다. API/schema/ITS는 PR126에서 별도 검증한다. [검증 원장](reports/2026-10-24-transport-user-journeys.md).


- [ ] 오피넷 수집·저장 복구: 지역별 체크포인트·완료 결과 저장 재개·최신 가격 SQL 병목·실패 뒤 예약·진행 로그 필터를 검증한다. 배포는 사용자 지시로 대기하고 다른 에이전트의 일괄 배포에 [인계](reports/2026-10-24-opinet-deployment-handoff.md)한다. 새 후보의 실제 최신 source·export200·전국30분 실측은 운영 수용 후 정산한다. [상세 점검](reports/2026-10-24-opinet-resume-review.md).

- [ ] 오피넷 작업 완료 뒤 Dagster 공통 개선: 사용자 2026-10-24 지시에 따라 진행 로그 필터·가림·op 범위 복구를 공통 라이브러리/Manager 계약으로 옮기고 모든 프로젝트 소비를 검증한다. 공용 daemon과 다른 실행은 유지한다.

- [ ] Map T2/T3 운영 수용: schema0030~0033와 API/CS를 승인된 drain 뒤 배포하고 source별 정상 성공 head를 준비한다. API·CS의 단일 defaultOFF flag를 일치시켜 활성화하고 승인된 수집 순서로 bootstrap한 뒤 실제 HTTPS·Map 새 frozen reader·UI·TTL/실패 복구를 검증한다. KAC quota PR119를 배포에 포함하며 원래 deadline 만료 뒤 재시도를 확인한다. [구현·검증 정산](reports/2026-10-23-map-t2-t3-acceptance.md).




- [ ] Map service API 후속: T1/T4/T5 PR108~110은 운영 배포·계약7/기존UI16 수용을 마쳤다. 오래된 OpiNet의 T1 fuel200/admin·최신 수집·Map 소비자 수용은 별도 미완이다. T2/T3 제품 구현은 PR112/114~118로 정산하고, 운영 수용은 위 별도 task에서 추적한다. [Map 인계](map-service-exports-handoff.md).


- [ ] 수집 CPU/RAM 후속: 기존 Track 1·2 수용 뒤 동일 입력으로 fetch/raw 변환/traffic 저장/통계/commit을 계측한다. 현재 traffic 8,300개에 약16,600개 SELECT·write 문장이 필요한 구조와 매번 최근2시간 재집계는 코드 조사 결과이며 실측 기여율은 미확인이다. bounded 배치 저장→변경 bucket만 재집계→incident 배치 저장을 각각 작은 PR로 검증하고, 원본·정정·삽입 수·소유권·통계 동등성을 보존한다. 단일 op executor의 프로세스 절감과 draft PR93 메모리 수용도 실제 run 증거 전에는 완료 처리하지 않는다.

- [ ] 배포 사전 검증·캐시 후속: Manager CLI의 약28초 startup/검증 비용과 현재30초 제한을 계측해 안정 여유를 정하고, 사전/공식 staging의 파일 metadata를 일치시킨다. 검증 우회나 실행 중 context 변경으로 해결하지 않는다.

- [ ] EX 유가 원천 이상값 정정 추적: 2026-10-21 `B00067` 사천(부산)주유소의 휘발유 저장값184와 원본 `gasolinePrice="184원"`이 일치한다. 공급자 정정 여부를 확인하고 최신 정상 수집 뒤 최저가·절감액을 재대조한다. 임의의1840원 보정이나 통계에서의 무근거 제외는 하지 않는다.


- [ ] 회수 sensor tick 예산·정체 경보·서버 statement_timeout(`feat/recovery-sensor-budget-stall`,
  Map ADR-112 교훈 적용): PR CI green 뒤 머지, 그 다음 odroid 재배포(codex 소유). 재배포 Compose
  호출에 `/opt/kor-travel-odroid/transport/transport.override.yml`를 반드시 포함해 code-server gRPC
  12306을 유지한다. 배포 뒤 sensor tick 로그에 `transport_worker_recovery.stalled`가 없는지와
  cursor가 `stall:null`인지 확인한다.

2026-10-20 KRIC 역 이름·코드 crosswalk 기능을 진행한다. KRIC 파일의 역 코드와 위치 파일의
역 번호를 확인하고 이름을 보수적으로 정규화해 자동 연결하며, 모호한 항목은 관리 UI 수동
보정 대상으로 남긴다. 데이터 모델·검증·Draft PR 후속은 `docs/resume.md`를 따른다.

- [ ] KRIC 모든 도시철도 역 이름·코드를 JSON 카탈로그로 저장하고, 역 번호와 정규화 이름의
      유일 대조로 안전한 항목을 자동 연결한다. 미연결은 관리자 UI에서 수동 연결·해제하고
      JSON으로 내보낼 수 있게 한다. 현재 1,108행 표본의 923개 자동·185개 수동 검토 후보를
      테스트·CI·두 독립 적대 리뷰·live UI E2E·배포로 검증한다.

2026-10-19 PR90의 포트/NVMe/project/export 정본과 실제 gateway 전환·Map GET·UI34는
수용했다. 실패·수정 집중검증은 [기록](reviews/2026-10-19-track2-runtime-contract.md)을 따른다.
전체 T-TRN-01~05를 일괄 완료 처리하지 않으며 03/04 문서·legacy와05 메모리 수용은 후속이다.

> **2026-10-17 당시 정산:** [Transport 남은 작업 감사](audits/2026-10-17-remaining-work.md)가 source 완료·실환경 잔여·낡은 체크박스를 구분한다. PR84는 main d1593ecc로 머지됐고 기존 UI34/호스트 효과/Docker95는 수용됐다. 전체 ARM build·새 URL bundle·첫 전체 cutover/T05는 별개라 T-TRN-01/02 전체 체크는 유지한다. 당시 daemon OFF 기록은 현재 지시가 아니다. 현재 사용자 정책은 공용 daemon RUNNING이며 배포 시 Transport instigator만 일시 pause/drain/원상 복원한다. T-040/041/043의 오래된 묶음 체크는 새 제품 구현 목록으로 그대로 재실행하지 않는다.

- [ ] 통합 교통 통계 캐시 미적중 지연 조사: n150 운영에서
      `/v1/transport/statistics?days=2` 공개 요청이 간헐적으로 10초 프록시
      제한에 걸려 504를 반환했다. `days=3` 내부 미적중 0.69초 및 `days=4`
      공개 미적중 0.75초와 대조해, 수집 실행 중 PostgreSQL 대기·CPU·락과
      집계 단계별 시간을 관측한다. 30초 이내 사전 생성 결과 허용 범위에서
      냉/온 모두 3초 이내로 만들고, 별도 회귀·live 부하 검증을 추가한다.

- [ ] 대량 전체 주차 이력의 부하 시 3초 초과: 정상 단일 브라우저 10/10건은
      3초 이내이나 관리자 E2E 직후 공개 요청 2/5건과 동시 8 worker 시험
      8/10건이 초과했다. 현재 전송 슬롯 2개·압축 본문 약 2.7MB·공개 경로
      전송량을 함께 측정해, 대량 응답의 동시성 상한과 지연 목표를 명시하고
      요구되면 네트워크 용량/전송 모델을 별도 설계한다. 무제한 JSON 계약은
      사용자 확인 없이 바꾸지 않는다.

- [ ] n150 배포 전 Dagster 작업 드레인: 배포 도중 새 고속도로 작업이 시작돼
      code-server 교체 후 Dagster 실행과 `collection_runs`가 running으로
      남았다. 이미지 빌드 후 스케줄 실행을 멈추고 기존 worker의 정상 종료를
      기다린 뒤 서비스 전환하며, 시간 초과 시 배포를 중단하고 스케줄을
      복구하는 보호·회귀 테스트를 추가한다. 2026-10-01의 단회 고아 실행
      복구는 자동 예방이 아니다.

- [ ] 저장 데이터 API 1초 지연 목표(기존 무제한 주차 이력만 3초): 운영 냉·온 반복 측정으로 유가 목록·지도
      최대 허용 `limit`, 유종 필터, 주차 통합 분석·30일 이력·실제 이력 화면의
      90일 시계열을 모두 확인한다. 관리자 HTTPS 프록시와 지도 동시 요청의
      전체 로딩 시간도 별도로 측정한다.
      `0018_fuel_latest_prices` MV/이력 인덱스, `0019` 원본·읽기 모델 세대값과
      공휴일 날짜 선택 조회를
      전용 PostgreSQL·WSL Docker·n150에 검증하고, 목표 초과 경로는
      별도 원인 분석 없이 완료로 표시하지 않는다.

- [ ] 항구·터미널 미확인 좌표 후속: 운영 적재 후 항구 607/749곳과 터미널
      649/803곳은 좌표가 없다. 자동 보류 시설은 코드·주소·시설명 공식 교차표로
      풀고, 결과 없음·모호·불완전 페이지(VWorld 8건·Kakao 36건)는 제공기관
      원자료와 실제 승선/승차 시설을 대조한다. 동명 장소에 섬 중심점·항로
      안내 점을 넣지 않는다. 실좌표의 지도 마커 표시·클릭은 아직 전용 live E2E로
      검증하지 않았으므로 별도로 확인한다. 2026-09-30 운영 재수집 뒤의
      [미확보 시설별 CSV](reports/unlocated-port-terminals-2026-09-30.csv)를
      검증 대상 목록으로 사용한다. 해당 재수집은 정상 완료됐으나 캐시 보호로
      신규 외부 호출·좌표 증가가 없었다.
      전국 버스정류장 파일은 정류장 독립 좌표 원천으로 검토하되 터미널 ID와
      직접 일치 0건, 이름 후보 203건·도시 확인 41건·단일 좌표 7건은
      시설명·주소·실제 승차 위치 검증 전에는 자동 적용하지 않는다.

- [ ] PR #52 배포 후 확인: 코드·두 적대적 리뷰·CI·머지·n150 배포·`0016` 적용,
      자기부상 6역 저장 좌표 복구는 완료했다. 새 날짜 우선 배편 수집의 다음 자연
      정기 run에서 제공기관 호출 280회 상한·실패·보류 수와 오늘 출발 항구 적재 범위를
      기존 346/749와 비교한다. 개선되지 않으면 원인을 조사한다. PR #52 당시
      배편 10일 snapshot 3,452개·오늘 출발 항구 346/749개는 과거 기준이며
      전국 완료로 표시하지 않는다.
      PR #54의 운영 관리자·지도 브라우저 E2E 447개와 실제 Kakao 장소 목록·상세
      1개는 통과했다. PR #52 당시 미완료였다는 기록은 이 검증으로 갱신한다.
      [진행 기록](runbooks/pr52-journey-fixes.md).

- [ ] 통계 deadline 후속(P2): 동시 대기 테스트의 전체 `calls == 1` 가정은
      PR #56에서 최대 동시 집계 1·슬롯/lock 반환 검증으로 교체했다. 남은 일은
      요청별 예산과 이미 만료된 예산으로 handler가 진입하는 경계를 별도 보강하는 것이다.
      PR #52 최초 CI·독립 재현 근거는
      [검증 기록](runbooks/pr52-validation.md)에 남겼다. 지도 변경과 분리한다.

- [ ] provider 브라우저 진단 후속(P2): 비숫자 지역은 안전한 순번으로 구분하고,
      응답 이후 DOM/파싱 및 초기 navigation 오류의 안전 진단도 별도로 보강한다.
      현재 응답 대기 구간 진단을 전체 오류 정제나 timeout 근본 해결로 해석하지 않는다.

### 후속: 유가 지역 분산 수집 (현재 모든 작업 머지 후 별도 PR)

- [ ] [준비 메모](plans/fuel-regional-scheduling.md)의 지역별 재수집 계약으로 처리량을
      검증한다. 사용자가 1번을 선택했으므로 같은 시군구의 수집 완료 후 재수집까지의
      간격이다. 다른 시군구는 그 사이 분산 처리하며 전역 이동 대기로 구현하지 않는다.
      요청한 지도·검색 UI 후속 작업과 분리하며, 아직 운영에 적용하지 않았다.
- [ ] 시군구별 수집 간격을 30분~2시간 범위의 무작위 간격으로 변경한다.
- [ ] 시군구 순서와 하위 주소체계의 수집 순서를 각각 무작위화한다.
- [ ] 최하위 주소체계 수집 간격을 2~90초 범위에서 무작위화한다.
- [ ] `Asia/Seoul` 06:00 이상~20:00 미만에는 위 주간 간격을 적용하고, 20:00~다음 날
      06:00에는 시군구 60~180분, 최하위 주소 10~120초의 무작위 간격을 적용한다.
      사용자의 최종 수정에 따라 기존 야간 3배 규칙은 폐기한다. 순서 무작위화는
      양쪽 시간대에 유지한다. 시간대 경계·자정·재시작 회귀를 포함한다.
- [ ] 주소 단계별 실제 provider 지원 범위를 먼저 확인하고, 진행 위치·다음 허용 시각을
      영속화해 Dagster 재시작/중복 실행에 안전하도록 설계한다. 제공기관 호출 제한과
      차단·한도 오류의 유예를 우회하지 않는다. 현재 단일 검증 run에는 적용하지 않는다.

### 후속: 지도 정보·검색 컨트롤 개선 (현재 기항지/버튼 PR 완료 후)

- [ ] 유가 마커를 주유소 브랜드별 아이콘으로 표시
- [ ] PR #52 운영 시각 점검 P2: 선택한 주유소/충전소 이름이 주변 가격·묶음 마커에
      가려지지 않도록 선택 마커의 겹침/표시 순서를 보강한다. 1440px·375px에서
      확인했으며 상세 조회는 정상이다. 새 회귀 여부는 미확정이다.
- [ ] 공항 마커에 주차 현황과 현재 기준 ±10분~±1시간 출도착/비행편 정보 표시
- [ ] 고속도로 노선별 돌발 현황을 지도 마커로 표시
- [x] 교통/유가 페이지를 분리하고 각각 교통 종류/유가만 표시하는 지도 뷰 추가
- [ ] 열차/도시철도 역·노선 검색/선택을 shadcn multiselect combobox로 전환하고 칼럼 폭 축소
- [ ] 배편 검색도 같은 combobox·좁은 칼럼 구성 적용
- [ ] 고속/시외버스 출발·도착을 shadcn combobox로 전환하고 출발지 선택 시 실제 연결된 도착지만 제공
- [ ] 나머지 select도 단일/다중 shadcn combobox로 전환

- [x] Map Feature 지도 페이지의 탭·viewport 상태·필터 중심 레이아웃을 교통/유가 지도에 반영
- [ ] Weather Dagster 정보 페이지의 색상 외 구조·상호작용·페이지별 링크를 최대한 동일하게 반영

현재 진행 중 task는 `T-042`, `T-043`(운영 식별자 개명)이다. 예정: `T-046`(ADR-014 odroid 이전 — T-TRN-02/03a/05는 소유자
확인 뒤 즉시, T-TRN-01은 Manager T-MGR-01a 머지 뒤, T-TRN-03b/04는 배포 게이트 뒤). `T-033`~`T-039`(shadcn/ui 전환 + 과거 자료 조회 +
Hallmark 재감사/재설계 + UI 밀도 개선) 전체가 완료돼 `docs/tasks-done.md`로
이동했다.

### T-046 odroid 호스트 이전(ADR-014, 교차 저장소 Track 2 설계 2026-10-13의 T-TRN-01~04 + 저장소 추가 T-TRN-05)

정본은 [ADR-014](adr/014-odroid-host-and-deploy-host-flag.md)(accepted, 현재 운영 수용)와 Manager ADR-58. T-TRN-03a 외에는 **코드 T**이며 이
문서 PR(`docs/adr-014-odroid-host-move`)에서는 하지 않았다. 의존: T-TRN-01만 Manager T-MGR-01a(`hosts:`·`ktdctl targets validate
--json` — 출력에 `targets.<id>.host`(hosts **키**, `host:` 생략 target도 resolve된 키)와 **`hosts.<키>.addr`**가 함께 실려야 한다,
ADR-014 "후속" 교차 저장소 계약) 머지 뒤; T-TRN-02·05는 소유자 확인(변수명 이탈·한도 값) 뒤 바로; T-TRN-03a는 소유자 §14-2
(legacy 폐기 범위) 결정 직후·odroid 배포 4b **전**; T-TRN-03b는 odroid 배포 게이트 초록 뒤. 수용 기준은 "빨갛게 만드는 입력"을
하나씩 포함한다. file:line은 head `eb40e3b`(원문이 정본, 줄은 참고 — 이 PR 머지 뒤 README 줄이 밀린다). **legacy 자산 집합 M**
(ADR-014 결정 6) = `docker-compose.odroid.yml`, `deploy/odroid/README.md`, `deploy/odroid/remote-deploy.sh`,
`deploy/odroid/bootstrap-docker.sh`, `scripts/deploy-odroid.ps1`, `scripts/odroid-status.ps1`(그중 fail-closed 마커는
`docker-compose.odroid.yml`·`remote-deploy.sh`·`deploy-odroid.ps1` 셋; 나머지는 n150 전용 설치 스크립트·legacy 상태 프로브·README) —
T-TRN-01은 M을 건드리지 않고(제외), T-TRN-03b가 M 부재를 단언한다.

> 2026-10-20 Dagster override 운영 장애 후속: release `5916b0a8`의 배포에서 Compose가 tracked override를 읽지 않아 14005로 기동했고 Manager registry의 12306 location이 unavailable 상태가 됐다. 포트 전용 overlay와 archive/stage/NVMe atomic install/Compose effect guard를 추가했다. 현 운영 code-server·location·12 schedules·5 sensors는 복구됐다. 테스트·review·live UI·공식 merged-release 배포가 끝나면 이 후속을 `tasks-done.md`로 옮긴다.

> 2026-10-17 PR84 이번 범위 수용: 필수 --host/Manager530 addr 효과/.env.prod source 정렬, 독립 A/C 리뷰, af8a source CI 6 SUCCESS·live 2 SKIP, WSL 배포 계약 95 PASS와 로컬 Docker 95 PASS·0 SKIP를 확인했다. root는 운영 tracked source를 af8a로 전진시키고 중앙 env와 동일한 .env.prod(0600/UID1001), 실제 승인/비로컬/env 없음 3종 효과 검사 및 기존 34개 live UI 기준 34 PASS를 확인했다. 77개 컨테이너·16 running·보호 파일11개·daemon OFF를 보존했고 build/recreate는 0이다. Manager530 제품의 설치 수용과 PR530의 머지는 별개이며 PR530은 아직 미머지다. 전체 ARM 빌드·새 번들의 env 전달 재현·첫 전체 cutover는 NOT_RUN이므로 T-TRN-01/02 전체 체크와 T-TRN-03 이후 항목은 유지한다. 자세한 실패 이력·범위는 journal 같은 날짜.

- [ ] **T-TRN-01** 배포 스크립트 두 개 개명 + `--host <addr>` 필수(기본값·host 목록 파일·스크립트 안 키→주소 표 없음):
      `scripts/deploy-server14.sh`·`deploy-server14-remote.sh` → `scripts/deploy-prod.sh`(+`deploy-prod-remote.sh`),
      `scripts/deploy-transport-admin-server14.sh` → `scripts/deploy-transport-admin-prod.sh`(운영 UI 12301/12305, Dagster 링크
      build arg는 T-TRN-02). 효과 검사(둘 다, 거부 = exit 2) = 원격 IPv4 집합 ∋ addr ∧ Manager 설치 ∧ 원격 `sudo -n ktdctl targets
      validate --json`에서 `k = targets.transport.host`(두 스크립트 같은 키 — registry에 `transport-admin` target은 없고 만들지 않는다;
      `k`가 비어 있어도 거부)를 읽어
      `hosts.<k>.addr == addr`(`sudo -n` 불가·`hosts` 필드 부재·`k` 없음도 거부) ∧ env 파일을 호출 사용자가 읽을 수 있음(`remote.sh:25`의
      `-f`에 `-r` 추가 — `.env.prod`는 n150과 같이 `digitie:digitie 0600`, ADR-014 결정 1; 원격 단계 실행 사용자는 digitie 그대로
      `deploy-server14.sh:5`, `remote.sh:43-44,91,121`, admin `:23-51,114`, 토큰 `set-transport-admin-write-token.py:14,41-48` 무변경).
      `.14` 리터럴 거부(`deploy-server14.sh:18-21`, `deploy-transport-admin-server14.sh:13`)·`REMOTE_HOST` 기본값(`:4`, `:6`) 삭제;
      app dir·env 파일명·project명 **대조는 유지하되 env 승인 값을 `.env.server14` → `.env.prod`로**(`deploy-server14.sh:26-29`,
      `deploy-transport-admin-server14.sh:9,15`); DSN `require`/regex(`remote.sh:71,77-84`)·plane 버전 동등(`:145-150`)은 유지.
      이름 추종 변경(ADR-014 B1′): `.env.server14.example` → `.env.prod.example`, `backend/Dockerfile:25` COPY·compose-contract 경로,
      `deploy-server14-remote.sh:86` mktemp 접두, `.gitignore:18`, `.dockerignore:13`, `docker-compose.shared.yml:24` 주석,
      `scripts/set-transport-admin-write-token.py:14,41`, `scripts/verify-release-stage.sh:4`, `.env.example:38`,
      `packages/kor-travel-transport-admin/frontend/.env.example:11`, 계약 테스트 5개(`backend/tests/test_deploy_server14_remote_guard.py`,
      `test_shared_db_deploy_contract.py`, `test_shared_dagster_cutover_guards.py`, `test_dagster_runtime_dependencies.py`,
      `test_admin_write_token_script.py` — 새 이름·새 검사를 단언하도록 갱신, 옛 이름을 흉내내는 대역은 함께 고친다).
      수용: **pytest 계약 테스트**(저장소에 bats 없음, CI `ci.yml:49-70`은 pytest·vitest·tsc만 — 설계 §13의 "bats"는 이 저장소
      규약으로 바꾼다; `test_deploy_server14_remote_guard.py`가 `docker`를 PATH 스텁으로 바꿔 진짜 스크립트를 돌리는 패턴을 `ssh`·
      `sudo` 스텁으로 확장) — `--host` 없음·원격 IPv4에 없는 addr·Manager 미설치·sudo 불가·`hosts.<k>.addr` 불일치(또는 `hosts`
      부재·`k` 빈 값)·env 읽기 불가 각각 exit 2(두 스크립트 모두); DSN을 `.13`으로 바꾸면 거부; `DAGSTER_POSTGRES_URL` 모양만 요구(DB 존재
      검사 없음); **plane 합류 가드 불변**(ADR-014 결정 10·B10): `remote.sh:222-226`은 그대로 두고, 스텁 webserver 응답으로
      "location `absent` → exit 2"·"location load error(`PythonError`) → 통과해 `wait_location_loaded`로 진행"을 각각 단언(빈 workspace
      plane + fresh DB 호스트의 첫 배포 모양); 첫 odroid 배포에서 결정 10 전제 ①(4a 뒤 `location_state` ≠ `absent`)·②(code-server
      healthy 뒤 3분 안에 `RepositoryLocation`) 실측값을 journal에 기록; `pytest -q backend/tests` 초록; 효과 게이트 `rg -n "deploy-server14|env\.server14" --glob '!docs/**'
      --glob '!deploy/odroid/**' --glob '!scripts/deploy-odroid.ps1' --glob '!scripts/odroid-status.ps1'` 보호용 구 env3개 exact exclude와 해당 보존 회귀를 제외하고 0건(M 제외 — head에서는
      `scripts/deploy-odroid.ps1:6`이 걸리므로 제외 없이는 T-TRN-03b 전에 초록이 될 수 없다). 문서: `docs/runbooks/deployment.md`
      (계획 절 → 현재 절차), `README.md`·`docs/current-state.md` 배포 명령.
- [ ] **T-TRN-05** compose 메모리·swap 한도(ADR-014 결정 11·B11, 설계 §3.2·실측 반영 #20; 규모 S). 수정 파일: `docker-compose.shared.yml`
      (`backend` `mem_limit: 0.8g`, `dagster-code-server` `mem_limit: 1g`, `frontend`), `docker-compose.transport-admin.yml`
      (`transport-admin-web`, `transport-api-gateway`) — frontend·admin web·gateway는 합 0.3g를 n150 `docker stats` 실측으로 분배;
      **다섯 서비스 모두 `memswap_limit == mem_limit`**(리터럴, 두 호스트 동일 — odroid cgroup v1 swap accounting on에서는 기본 swap 2×가
      실제 적용되고 n150 cgroup v2에서는 `memory.swap.max=0`과 같은 뜻); `oom_score_adj`·`pids_limit`은 두지 않는다. 계약 테스트
      (`backend/tests/test_shared_db_deploy_contract.py` 또는 새 파일): 두 compose 파일을 파싱해 "`mem_limit` 있는 서비스마다
      `memswap_limit == mem_limit`"와 "다섯 서비스에 `mem_limit` 존재"를 단언 — 하나를 빼거나 값을 다르게 하면 빨강. 수용(효과):
      `docker compose --env-file .env.example -f docker-compose.yml -f docker-compose.shared.yml config`·운영 UI compose `config` 렌더에
      다섯 서비스의 메모리 한도가 있다(렌더 키는 compose major에 따라 `mem_limit` 또는 `deploy.resources.limits.memory` — 테스트는 둘 다
      수용); n150 배포 뒤 `docker inspect -f '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}'`가 다섯 컨테이너에서 같은 두 값;
      Opinet run ≥1회 포함 창에서 OOM-kill 0(cs 한도 도달 시 한도를 올리지 않고 Opinet 배치 크기를 먼저 본다). 소유자 확인: 설계
      §3.2 값 그대로(backend 0.8g·cs 1.0g·나머지 합 0.3g).

### T-040 통합 교통정보 수집·OpenAPI

- [x] `python-krex-api` 고속도로 소통·돌발과 `python-opinet-api` Playwright 유가
      collector를 PostgreSQL 주기 수집에 연결
- [x] 저장 스냅샷 조회·내부 통계 OpenAPI와 Alembic migration 추가
- [ ] WSL/Docker 테스트, James/Popper 적대적 리뷰, n150 live E2E 후 PR 머지
- [ ] 현재 PR 머지 후 KRIC provider와 교통정보 확장 조사 문서 작업을 이어간다.
- [ ] 후속 P2: KREX 공통 코드 조회의 `FlowDirection` 노출, 대량 저장 데이터의 보관 기간과
      외부 목록 API 커서 페이지 정책을 정의한다. 현재 목록 조회는 최대 1,000건으로 제한한다.
      2026-09-19 운영 측정은 소통 16,740행/16,228,352바이트(인덱스 포함)다. 매 5분
      8,370개 신규 관측을 저장한다고 가정하면 소통 테이블만 약 2.18 GiB/일이다.
      실제 중복 관측은 저장하지 않으며 원본·백업 용량은 별도다. 보관 기간 결정 전
      데이터를 임의 삭제하지 않는다.
- [ ] 별도 보안 후속: `npm audit --omit=dev`가 보고한 Next.js/AVIF·sharp 취약점의 영향
      검토와 의존성 패치, WSL/Docker/live E2E 검증을 수행한다.
- [ ] 후속 P2: provider 인증/영구 파싱 오류의 장기 backoff·fail-stop 정책을 정의한다.
      현재 quota는 별도 backoff, 그 밖의 고속도로 오류는 기본 5분 주기로 재시도한다.
- [ ] 후속 P2: 통계 API의 운영 지연과 proxy timeout 여유를 측정하고 보완한다.
      9월 19일 공개 proxy에서 간헐 504 후 재조회 성공을 확인했다. 전국 데이터 증가 시
      쿼리 계획/응답량/호스트 I/O를 분리해 확인하며 단순 timeout 완화로 숨기지 않는다.
      9월 28일 이미지 적재·배포 후 첫 E2E에서 45초 timeout과 내부 집계 슬롯 포화 429가
      발생했다. 후속 2/7/10일 조회는 각각 1.85/5.10/16.65초에 성공했지만 최초 원인은
      미확정이다. 장기 집계의 유가 heap fetch·원본 경계 읽기, DB 조회 제한 시간과
      클라이언트 이탈 후 취소/슬롯 해제를 재현해 검증한다. 단순 재시도로 해결 처리하지 않는다.

### T-041 공용 DB·Dagster와 철도·여객항구 기준정보

- [ ] `kor-travel-docker-manager` 공용 PostgreSQL의 app/Dagster metadata 전용 DB·role provision
- [ ] FastAPI의 in-process scheduler를 운영에서 끄고 code-server/webserver/daemon/gateway 분리
- [ ] KRIC XLSX 철도 역사 및 여객항구 기준정보를 매 3일 Dagster job으로 저장
- [ ] 공개 파일을 공용 RustFS에 저장하는 async provider 계약을 `python-*-api`에 추가
- [ ] Map/PinVi `place`·`notice`·`price` contract REST와 항구 실시간 시간표 API 구현
- [ ] WSL/Docker, 적대적 리뷰 2명, n150 live E2E와 shared DB cutover 검증 후 PR 머지

### T-042 Transport 전용 운영 관리 UI

- [ ] PR #46 Popper P2: 내장 지도에서 검색 조건/전달 장소 목록이 바뀌면 이전 겹침 선택
      목록을 제거하거나 현재 결과로 제한한다. 전용 지도는 조회 변경 시 제거되지만 내장 지도는
      이전 실제 장소를 선택할 수 있다. 닫기/재선택이 가능해 후속으로 분리하며 회귀 테스트를 추가한다.

- [ ] PR #44 머지 후 오피넷 실제 수집 성공을 확인한다. 사용자 요청으로 배편 선실행 검증까지를
      이번 머지 범위로 정했으며, 오피넷 8시간 보호와 16:00 KST 정기 실행은 변경하지 않는다.
- [ ] 공용 PostgreSQL의 09-28 12:28~12:33 KST 내부 프로세스 종료·복구 모드 원인을 조사한다.
      자동 복구 후 API 200·항구 데이터 영속성은 확인했지만 초기 원인은 확정하지 않았다.
      다른 프로젝트/공용 DB 변경은 영향 범위와 권한을 별도로 확인한다.
- [ ] Popper 통합 리뷰 P2: 기존 `.env.example`의 `FERRY_TIMETABLE_MAX_DAYS_AHEAD=7`을
      코드/운영 예제의 9와 정렬하고 10일 조회 계약을 검증한다. origin/main에도 있던 불일치이며
      운영 설정에는 영향이 없다. PR #44의 배치 간격 변경과 분리한다.

- [ ] KRIC 48시간 보호 종료 이후 첫 실제 시간표 적재·공휴일 달력·정확 연결 범위를 확인한다.
      보호 종료는 9월 29일 15:04:58 KST이며 매시간 due 평가가 실행을 결정한다.
      API·역 비교 UI 구현과 실제 운영 데이터 적재 완료를 구분한다.
- [ ] 일반철도 운행 데이터 및 버스터미널 좌표 제공자를 연결한 뒤 동일 지도 검색 UI를 확장한다.
- [ ] 운영 호스트의 UI 빌드·이미지 적재 I/O를 분리한다. 9월 27일 n150에서 빌드 중
      CPU I/O wait 48~64%와 일시적인 Dagster 시작 timeout을 확인했다. 사전 빌드 이미지
      승격·레이어 전송 방식과 배포 시간대를 검토하며 health timeout만 늘려 숨기지 않는다.
      PR #43은 사전 빌드로 바꿨지만 9월 28일 UI 교체·첫 페이지 준비에도 수분이 걸렸다.
      직후 첫 공개 장소 목록은 29.7초, 주유소 목록은 17.4초였다. warm 반복 측정의
      p95 개선과 cold 응답·무중단 배포는 별개이며 완료 처리하지 않는다.
- [ ] 9월 27일 16시 오피넷 `Page.goto`/DOMContentLoaded 시간 초과 뒤 다음 정기 수집을
      확인한다. 마지막 성공 00:36 KST와 Dagster 작업 종료/실제 provider 실패를 구분한다.
      인증·호출 제한을 우회하거나 근거 없이 timeout만 늘리지 않는다.
- [ ] 오피넷 최신 병합 PR #19(`8708f10`, 기본 대기 60초)와 transport 고정 버전
      `39e7acc`의 차이를 반영한다. transport가 `opinet_browser_timeout_ms=30000`을
      명시 전달하므로 의존성 버전만 올려도 대기 정책은 바뀌지 않는다. 9월 28일 배치의
      화면 데이터 대기 실패와 호스트 I/O를 함께 재현·검증하고 수집 성공을 별도로 확인한다.

- [x] weather admin의 인증·server-side proxy·Dagster GraphQL 경계를 transport 전용
      Next.js 패키지로 복제
- [x] 기존 `parking-radar`와 독립된 API/Dagster/UI gateway Compose project 추가
- [x] 고속도로·유가 저장 스냅샷, 수집 상태, Dagster 상태, 허용 경로/세션/CSRF 단위·계약 테스트 추가
- [x] 교통·유가 통합 저장 통계 화면, Apache ECharts 비교 그래프, 열차·도시철도·배편 분리 화면 추가
- [x] `digitie/maplibre-vworld-react` 고정 revision을 사용하는 VWorld React 지도와 항구 시간표 명시 호출 계약 추가
- [x] bbox 기반 저장 장소 지도 요청·절단 안내, 실제 VWorld 타일·모바일 viewport live E2E 계약, vendor tarball provenance 기록
- [x] VWorld 제공 영역 밖 `200/XML FileNotFound`를 공통 provider fallback으로 분리하고,
      submodule·vendor tarball·SRI를 병합된 provider revision으로 동기화
- [ ] 후속 P2: 수집량 증가 전 fuel/rail numeric 좌표 bbox 복합 index를 `EXPLAIN (ANALYZE,
      BUFFERS)` 측정으로 설계한다. 현재 지도는 zoom별 전체 최대 900개를 요청하므로 즉시
      PostGIS migration을 강제하지 않는다.
- [ ] 후속 P2: `kind` 없는 legacy 장소 목록의 작은 `limit`에서 세 종류가 공정하게
      반환되도록 API 계약을 별도 버전으로 정리한다. 지도는 종류별 bbox 요청만 사용한다.
- [ ] 후속 P2: 지도 map event test seam으로 zoom 8·10의 종류당 200/300개 예산과, 타일
      오류 뒤 회복 시 안내 해제를 E2E로 고정한다. 현재 initial zoom 7의 종류당 100개,
      선택 중 오류 가시성, 성공 타일은 live E2E가 확인한다.
- [x] ~~후속 P2: VWorld `vworld-tile-error`의 `mapId`를 transport 지도 identity와 대조~~ —
      2026-10-09 `feat/admin-map-maplibre-vworld-react`에서 `vworld-map-web`을 되살렸다. 라이브러리
      `VWorldMapView`가 window `vworld-tile-error`의 `detail.mapId`를 자기 인스턴스 id와 대조한 뒤에만
      `onError`로 넘기므로 지도 사이 혼선이 없다. 회복 시 안내 해제는 `map-overlays.test.tsx`가 단위로 고정한다.
- [x] 2026-10-09 교통 지도 엔진을 `digitie/maplibre-vworld-react`로 되돌리고(#70의 손으로 쓴 셸·style builder 제거)
      Map 마커 겉모양은 유지. #70이 라이브러리 fallback을 우회해 제공 영역 밖 `200/XML` 타일 하나에도
      "타일을 불러오지 못했습니다"를 띄우고 거두지 않던 회귀를 닫았다.
- [ ] P2: 예정 열차 마커의 301역 viewport 절단·늦은 응답 취소·숨김 탭·클러스터 왕복
      조합을 자동 검증한다. PR #43은 목록 왕복에서 지난 열차 숨김과 DB 300역 조회를
      검증하지만 모든 지도 이벤트 조합을 포괄하지 않는다.
- [ ] 후속 P2: transport deploy script의 stale middleware 보존/제거 조건을 mock으로
      검증하고, versioned release directory의 atomic switch와 remote checkout canonical path
      검증을 설계한다. 현재 build 실패는 `up --force-recreate` 전에 끝나 기존 서비스는 유지된다.
- [ ] cAdvisor `12103`, Prometheus `12102`, Grafana `12104` 전환 후 n150에서 transport
      12301/12302/12305를 배포
- [ ] 두 적대적 리뷰, CI, n150 live E2E 뒤 Draft PR을 머지

### T-043 n150 운영 식별자 개명(airport → transport, ADR-010)

- [x] 저장소 준비(`chore/rename-deploy-identity-transport`): compose `name:`·network·이미지 fallback,
      배포 스크립트 allowlist, Dagster DSN `postgresql+psycopg2://` 허용, release 태그 export,
      임시 개명 guard, 저장소 백업 cron 제거, cutover 스크립트와 가짜 docker 테스트, runbook·ADR-010
- [ ] PR #44 머지 뒤 origin/main으로 rebase, CI, 두 적대적 리뷰, 머지(창 직전)
- [ ] Manager `chore/retire-dedicated-postgres` release를 따로 설치·검증하고 Manager 개명 PR을 준비
- [ ] n150 cutover: `prepare` → `restore-point` → stage → `prebuild` → `window` → `admin` → Manager 설치
      → `finish`(runbook `deployment.md` "운영 식별자 개명 cutover")
- [ ] 72시간 관찰 뒤 정리(은퇴 컨테이너·옛 network·옛 이미지·rollback 태그·은퇴 디렉터리), 후속 PR로
      임시 guard 제거
- [ ] 후속: API 백업 `BACKUP_COMMAND_TIMEOUT_SECONDS`·`BACKUP_STORAGE_LIMIT_BYTES`를 785 MB dump(약 8분)
      DB에 맞춰 검토. Manager transport 백업 역할은 #430으로 설치됐다(16:50·17:15 UTC).
- [ ] 후속(소유자 요구, Manager 변경): 공용 PostgreSQL의 모든 DB에 prewarm — `pg_prewarm`
      preload·`pg_prewarm.autoprewarm=on`·`shared_buffers`(지금 128 MB) 크기. instance 재시작이라
      개명 창과 따로 한다(ADR-010 후속, runbook 전제).

`T-034`에서는 `<select>`/`ResponsiveSection`의 `<details>`/
daily-flight-overlay-chart의 토글·체크박스는 테스트 호환성 위험 때문에 의도적으로
native 구현을 유지했다 — `T-035`에서 라우트 구조가 바뀌었지만 이 판단은 그대로
유효하다(재검토 결과 변경 없음). `T-035`가 남긴 후속 미해결 항목(`docs/tasks-done.md`
T-035 참고): 분석 뷰의 브레이크포인트가 860px→1024px(Tailwind 기본값)로 바뀐 것은
의도적이나 별도 공지·테스트는 없음, 라우트 전환 시 analytics 데이터가 캐시되지 않아
`/analytics`↔`/history` 왕복마다 재요청됨, 백업 생성/복원 진행 중 다른 라우트로
이동하면 진행 상태가 사라짐(백엔드 `operation_lock`이 데이터 손상은 막지만 사용자
피드백은 소실). `T-036`이 남긴 후속 미해결 항목(`docs/tasks-done.md` T-036 참고):
라우트 간 analytics 데이터가 캐시되지 않는 문제가 `/history`에도 동일하게 있음(같은
근본 원인, T-035와 동일), 날짜범위 선택 팝오버가 선택 완료 후 자동으로 안 닫힘(수동
닫기만 가능). `T-038`이 남긴 후속 미해결 항목(`docs/tasks-done.md` T-038 참고):
dark-mode 차트/톤 팔레트 미토큰화, `globals.css` 전반의 desktop-first 미디어 쿼리
구조, stock shadcn 프리미티브 3곳의 `transition-all`, 980–1024px 브레이크포인트
경계 전용 회귀 테스트 없음, `/backup`이 여전히 클릭 1번으로 열림(의도적 유지 —
아래 참고). `T-039`가 남긴 후속 미해결 항목(`docs/tasks-done.md` T-039 참고):
새로고침 버튼 tap target이 320px에서 44×42px(WCAG AA 24×24는 통과, AAA
44×44에는 2px 못 미침 — 사소함), `.lot-card-grid`가 숨는 이유(64rem 미디어
쿼리)가 JSX에는 클래스명이 아니라 주석으로만 남아 있어 향후 편집 시 실수로
`lg:hidden`을 다시 붙이면 같은 버그가 재현될 수 있음.

## 완료 조건

이 백로그는 코드·문서·테스트·운영 검증이 모두 끝난 뒤 각 항목을 완료 처리한다.

- [x] PostgreSQL 컨테이너가 healthcheck를 통과하고 애플리케이션이 기동된다.
- [x] 기존 SQLite 테스트와 PostgreSQL Docker 테스트가 모두 통과한다.
- [x] 최근 주차 관측 구간과 마지막 수집 시각이 이전 시스템보다 늦지 않다.
- [x] n150에서 연속 수집이 시작되고 5분 간격의 관측 공백이 발생하지 않는다.
- [x] n150 공개 포트는 API `14000`, web `14001`이며 live E2E는
  `https://pr.digitie.mywire.org`에서 실행한다.
- [x] API 외부 주소는 `https://pr-api.digitie.mywire.org`로 smoke 검증한다.
- [x] 백업 생성·다운로드·복원 UI를 실제 브라우저에서 확인한다. 실제 운영 DB를 덮어쓰는 복원 실행은
  pre-restore backup 보호를 확인한 뒤 별도 운영 승인으로 남긴다.
- [x] 모바일 320/375/414px와 데스크톱 768px 이상에서 가로 스크롤·접근성 회귀가 없다.
- [x] 두 리뷰 에이전트의 critical/major 지적이 해소되거나 근거와 함께 기록된다.
- [x] Draft PR이 CI와 live E2E를 통과한 뒤에만 머지한다.

## 운영 제약 및 미해결 위험

- 현재 Odroid 작업은 배포 런북·ADR-014를 따른다. 과거 SQLite 원본은 전용 내부 API를
  HTTP GET으로만 읽었고, 외부 원본 주소 `https://pr2.digitie.mywire.org`는 cutover 당시
  parking-radar가 아닌 Home Assistant 응답을 보여 원본 검증에 사용하지 않았다.
- HTTP fallback은 공항·주차장·관측 시계열을 보존했지만 raw response와 기존 collection run ID를
  복원하지 않는다. exact SQLite dump가 필요하면 운영자 권한으로 별도 파일을 제공해야 한다.
- 13번의 현재 수집기는 10분 주기로 동작 중이다. n150은 configured 5분 계약과 120초 safety
  buffer(실제 tick 180초)로 운영하며, 공공데이터 API rate limit과 실제 응답 시각은
  `docs/architecture/collection.md`에 기록한다.
- 백업/복원 API에는 별도 인증이 없다. 인터넷에 직접 노출하지 않고 내부망 또는 외부
  게이트웨이에서 접근을 제한해야 한다.

- [ ] Map T4 가격 이력: PR110 구현·검증·머지 완료(주유소 bounded 조회·공통meta·ETag/gzip·cursor/revision, 휴게소501). 운영배포·stale 이력/304/gzip/페이지 계약·기존UI16 수용은 완료다. Map 예시 인계 댓글은 게시했고 소비자 수용·실수집 최신성 회복 뒤 추가 확인이 남았다. T1fuel200/admin 정상자료도 별도 미완이다. [계약](map-service-price-history.md).

## UI 선행 반영(2026-10-24)

- [ ] 기존 API 호환 관리자 UI의 검증·두 독립 리뷰·관리자 웹 단독 배포와 운영 반응형 수용. [범위](reports/2026-10-24-ui-first-release.md).
