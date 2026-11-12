# Transport 장기 미처리 PR 정리 — 2026-11-12

## 처리 결과

사용자는 신규 차트·성능 변경에 앞서 오래 열린 PR의 반영 여부를 확인하고 필요하면 닫거나 반영하도록 지시했다. 열린 23건을 조회한 뒤 Git 조상 관계를 직접 대조했다. 오래된 21건의 최종 HEAD 전체가 #180의 원 HEAD `3f68255669687b50cd30d6ec7a78a60846288481`에 포함된다. 이 21건은 #180으로 통합한다는 설명을 각 PR 본문에 추가하고 닫았다. 원 브랜치와 기존 실패·검증 이력은 삭제하지 않았다.

이는 **main 머지 완료를 뜻하지 않는다**. #180을 main 대상으로 전환하고 최신 main `9aebd19947c3606c2953eb564e7eee4541be5856`과 통합한 후보 `4c06e26b48053efa8558106504f7189bf2d54ffb`를 push했다. 오늘 생성된 별도 지도 로딩 안내 PR #186은 그대로 유지한다.

| 종료한 PR | 확인한 최종 HEAD | 보존 위치 |
| --- | --- | --- |
| [#31](https://github.com/digitie/kor-travel-transport/pull/31) | `6b727062b6d450b2c248ad2779a40aab29718329` | #180 Git 조상 |
| [#38](https://github.com/digitie/kor-travel-transport/pull/38) | `671397e797931e22abe18ca8d20a48b16f5b4c86` | #180 Git 조상 |
| [#81](https://github.com/digitie/kor-travel-transport/pull/81) | `027ad551e68c238bb211f380c3f9a54f20eaad48` | #180 Git 조상 |
| [#93](https://github.com/digitie/kor-travel-transport/pull/93) | `a370e23d3501e08953175b2d006ae9df70629255` | #180 Git 조상 |
| [#128](https://github.com/digitie/kor-travel-transport/pull/128) | `5d7a9c1d09f757949baed6c46168bf283b97fdbb` | #180 Git 조상 |
| [#157](https://github.com/digitie/kor-travel-transport/pull/157) | `8a34ec747a066fa06227417a4a3f6a1b916726cd` | #180 Git 조상 |
| [#161](https://github.com/digitie/kor-travel-transport/pull/161) | `da4ab903154025b99b315603bf8cefcb78940356` | #180 Git 조상 |
| [#162](https://github.com/digitie/kor-travel-transport/pull/162) | `f4ea9e096b421d626133f72835f02ce90f92024a` | #180 Git 조상 |
| [#163](https://github.com/digitie/kor-travel-transport/pull/163) | `ec9a4866b08e264ce3a491287a7fe563a430e265` | #180 Git 조상 |
| [#165](https://github.com/digitie/kor-travel-transport/pull/165) | `a85e30c7721319b5c6e1e4b8efd832e06d667858` | #180 Git 조상 |
| [#167](https://github.com/digitie/kor-travel-transport/pull/167) | `098f1da132f32ee823d8a0db0d08a36193cff1f3` | #180 Git 조상 |
| [#168](https://github.com/digitie/kor-travel-transport/pull/168) | `379fd7a12b9b77547b5f78b95fe8551fb211537a` | #180 Git 조상 |
| [#170](https://github.com/digitie/kor-travel-transport/pull/170) | `64d667a783dbc7f08d7cd46fb3e410eb2fb70f27` | #180 Git 조상 |
| [#171](https://github.com/digitie/kor-travel-transport/pull/171) | `90ed75ce0637448053189809370a37335e39f732` | #180 Git 조상 |
| [#172](https://github.com/digitie/kor-travel-transport/pull/172) | `16c0bcc8c7db520fedb47e8cc93916898b084a1c` | #180 Git 조상 |
| [#173](https://github.com/digitie/kor-travel-transport/pull/173) | `f135c05a11f5992fdd9280701c7118dcdf4927dc` | #180 Git 조상 |
| [#174](https://github.com/digitie/kor-travel-transport/pull/174) | `68990e4a4d3a3e9125903a36ceebec73b223c1fb` | #180 Git 조상 |
| [#175](https://github.com/digitie/kor-travel-transport/pull/175) | `f721df42369b67cc2871961da388743741bd3d5f` | #180 Git 조상 |
| [#176](https://github.com/digitie/kor-travel-transport/pull/176) | `0e771c30bf8e0a82d078c16493cbeec8100ddf37` | #180 Git 조상 |
| [#177](https://github.com/digitie/kor-travel-transport/pull/177) | `6f3367c84f97a0e1b106fa56474b4e8b1ed0d0a0` | #180 Git 조상 |
| [#178](https://github.com/digitie/kor-travel-transport/pull/178) | `3e745bfab2c32ea9e5b8f5c1760e2470990c9ad3` | #180 Git 조상 |

## 통합 방식

- 새 격리 작업 브랜치에서 main을 merge했다. 기존 작업자의 원래 작업 트리는 수정하지 않았다.
- 백엔드 기능·마이그레이션·의존성과 유가 MCP·일반 주차장·철도 일일 수집·영구 유가 요약은 기존 기능 브랜치를 보존했다. backend의 main 통합 변경은 관리자 계약 시험 1파일이다.
- 충돌 21곳 가운데 공통 지도·콤보박스·역 안내·메뉴·일반 주차장 UI는 최신 main을 사용한다. 두 문서 이력은 함께 보존했다. 지역 유가 중계 경로의 allowlist 시험은 실제 통합 백엔드 계약에 맞췄다.
- 관리자 앱과 main의 최종 차이는 중계 경로·운영 문서·기존 로그인 회귀 등의 7파일이다. 현재 요청한 EvilCharts 변경은 아직 섞지 않았다.

## 검증과 남은 절차

- 후보4c06의 GitHub 공개 웹·관리자·공통 정책과 한 전체 백엔드 CI 실행은 성공했다. 같은 소스의 다른 중복 실행은 당시 진행 중이었다. 아래 리뷰 수정 후 후보의 검증과 구분한다.
- 정확한 새 backend import 경로를 확인한 WSL 집중 시험은 15건 통과했다. 옛 검증 환경의 KRIC SDK import 오류와 최초 DrvFS 임시 파일 오류는 새 제품 실패로 해석하지 않고 원문을 보존했다.
- 관리자 WSL 타입 검사는 통과했다. 전체 458건 중 457건 통과·1건 timeout을 보존한다. 해당 계약 시험은 첫 동적 모듈 로딩이 5초 시험 제한 안에 포함됐다. 모듈을 정적 import로 이동한 후 기존 제한과 모든 단언을 그대로 둔 집중4건은369ms에 통과했다. 제품 코드는 바꾸지 않았다.
- Docker 집중 backend는12PASS/3SKIP이며 주차장 계약4건은390ms에 통과했다. 해당 관리자 QA 부모는 결과 파일 경로를 쓰는 recorder의 TypeError 때문에 CLI1로 보존한다. 자식의 시험 통과를 부모0으로 바꾸지 않는다. 최초 tmpfs 인용 실패·Vitest 임시 저장소 부재도 원문을 보존하고 QA 설정만 교정했다.
- n150의 정확4c06 격리 앱은 build 성공·메뉴/역 SSR15PASS였다. shared-map-ui2건은 최초 QA Origin 누락으로 로그인 단계에서 실패했다. 별도 r2에서 Origin을 고친 뒤 모바일의 기본 접힌 필터를 열지 않는 기존 시험과 실제 키를 쓰지 않은 PC 지도 초기화에서 실패했다. 두 부모/소유 서버는 종료됐다. 이 fixture 실패를 제품 결함이나 전체 UI 성공으로 단정하지 않는다.
- 최종 CI·필요한 실제 UI 수용·main 머지는 미완이다. 이 상태에서 Draft를 임의로 완료 처리하지 않는다.

## 두 독립 리뷰와 수정

James는 UI/접근성 관점, Popper는 backend/PostgreSQL/운영 관점에서 후보4c06과 최신 main 병합 결과를 독립적으로 읽기 전용 검토했다.

- James P1: 저배율에서 주유소 이름·주소·브랜드 검색이 지역명과 다르면 API total에는 일치 지점이 있어도 cluster와 지역 카드가 모두 사라졌다. 이름/브랜드와 시도/시군구 축척4조합에서 수정 전4FAIL을 재현했다. 검색어가 있을 때는 실제 일치 주유소의 묶음을 보존하고, 검색어가 없을 때는 기존 영구 지역 통계를 읽도록 수정했다. 수정 후 같은4건은 통과했다.
- James P2: 지역 유가 카드의 지점이 cluster 합에서 빠져 `0건 표시`가 나왔다. 원0건과 기대2건을 실제 DOM으로 재현했고 API total을 보존하도록 고쳤다. 이후 지도 전체19건은 통과했다.
- James P2: vendor README의 dev.9 설치/보존 문장은 당시 이력으로 고치고 현재 C11 원장을 가리켰다.
- Popper: 통합 때문에 사라지는 backend 기능이나 실행 중 데이터 삭제 경로의 확정 P0/P1은 없었다. 다만 `0037_regional_fuel_and_rail_daily.py` downgrade의 빈 테이블 검사와 DROP 사이에 첫 writer가 들어올 수 있는 P2를 지적했다. 정상 배포에는 downgrade 호출이 없고 현 운영에는 영구 통계가 있으므로 이번 경로의 blocker가 아니다. 자동 downgrade는 계속0이며 후속에 비자동커밋/READ COMMITTED·배타 잠금과 경합 시험을 추가한다.
- 수정한 유가 조회는 전용 PG18에서 schema0042까지 공식 migration 후 WSL6건·Docker6건을 각각 통과했다. 같은 시험을12건으로 합산하지 않는다. 정확 소유 CID/label을 확인한 일회용 PG는 종료·제거했다. 운영 DB·수집 변경은0이다.

이번 정리로 운영 이미지·환경·DB·수집 일정은 변경하지 않았다. 백업·복원은 사용자 지시에 따라 생략하고 prune OFF를 유지한다. 후속 21개 요구사항은 별도 계획에 보존하며 PR 정리 뒤 이어간다.
