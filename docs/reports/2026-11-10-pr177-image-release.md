# PR177 최신 이미지 반영

사용자가 새 이미지 반영을 명시해 최신 소스4dac82d의 API·수집기 이미지를 새로 빌드했다.
수정 코드7ff7b52의 CI42604663260은 backend1793통과·2생략, frontend/관리자 성공이다.
4dac82d는 문서 마감만 추가한 소스이며 배포 뒤 문서 변경으로 같은 제품을 다시 빌드하지 않는다.

## 빌드 수용

기존 역할별 이미지를 바탕으로 최신 backend·스크립트·계약 파일을 반영했다. API는
`b9ac0d18f128959cf4dab1770b4951984bfc3758868c7233b2bad00f4ee9db77`, 수집기는
`22f47ac583577db462ed1c30946cc0999f95dcad5cf6deaef7bebe49e8b727b7`다.
71개 앱 파일 SHA·역 수집 두 op·전체 설치 package 지문·명령·entrypoint·healthcheck·사용자가 같다.
새 의존성 설치·migration·웹 재빌드는 없다. 실제 빌드 first1b408d1c는 done/Main0/cgroup부재와
모든 소유 자식 종료를 확인했다. 로컬 제출의 문법·SSH 인자 길이 실패는 운영 교체 전 이력으로
보존하고, 별도 build-r2에서 파일 전달 방식으로 실제 빌드를 완료했다.

## 운영 반영 상태

정상 Manager G→Transport R/FD9에서 API를 먼저 교체했다. API CID228c3522는4dac82d/
schema0041·실제12302·native Settings·키/개별 환경을 보존한다. API와 gateway `/health`는
새 release/DB ready·HTTP200이며 저장 철도역·유가 조회도200이다. 이 조회는 성능 개선율이나
원천 자료의 최신성 보장이 아니다.

원래 Transport 일정을 capture/pause한 뒤 기존 run·worker의 자연 종료를 확인하고 수집기도 교체했다.
API CID228c3522·수집기 CIDf85e0fe8과 기존 웹/관리자/gateway의 다섯 역할 모두 healthy다.
원20일정·Transport location·일반철도 두 op·개별 환경/키·schema0041을 보존했고 Manager
adopt/verify/show healthy를 확인했다. 공용 daemon·Weather/Geo·다른 서비스를 중지하지 않았다.

첫 배포는 수집기 교체와 원20복원 뒤 Settings 전체 지문 비교에서 AssertionError/actual1로 종료했다.
기존 수집기에는 없던 `transport_fuel_mcp_enabled` 선언이 최신 전체 소스에 추가된 것이 원인이다.
제거 필드·기존 필드 값 차이는0이며, 실제 컨테이너 환경은 RELEASE_SHA 이외 모두 같다.
원 실패를 보존하고 별도 completion Root에서 현재 두 CID를 고정해 검증·Manager metadata만
마감했다. 재빌드·재교체·추가 pause는 없다. completion first67dcc9b3는 done/Main0/cgroup부재다.
빌드11·원 배포93·마감10개 소유 자식의 실제0/종료와 잔여PID 부재를 확인했으며, 원 배포 부모1을
성공0으로 바꾸지 않는다. 백업/복원·원본 삭제·prune·main merge는 하지 않았다. PR177은 Draft다.

기존 수집의 공식 terminal은 유가5d5282ef SUCCESS, 공항5a7de983·고속도로c0b145f0 FAILURE다.
강제 취소·재수집을 하지 않았고 두 실패를 새 이미지·Manager healthy와 별개 이력으로 보존한다.
두 실패 step의 오류 종류는 Dagster `Failure`이며 세부 수집 원인은 이번 판독에서 미확정이다.

정본은 Git 밖 `transport-pr177-image-20261110/plan.json`과 build-r2/deployment 원문이다.
