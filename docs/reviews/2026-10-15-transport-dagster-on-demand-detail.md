# Transport Dagster 실패 상세 선택 조회

## 문제와 변경

기존 관리자 overview는 실패 실행 최대3개의 상세를 Promise.all로 조회했다.
실패3개를 반환한 로컬 원본 재현에서 overview1회+상세3회가 발생하여,
초기 조회1회 기대 회귀가 실제4회로 실패했다. 운영 GraphQL502 관측과 관련된
불필요한 fanout을 줄이지만, 이 구조가502의 단독 원인이라고 확정하지 않는다.

최신 main38eafb1(PR79 merge)에서 Weather4bb의 선택·취소·버전 패턴을 적용했다.
Transport의 기존 overview25초·상세 전체15초·20page·메시지2000자 상한을
유지하며 proxy10초도 바꾸지 않는다. Common 제품·vendor·Python·API계약은 변경하지 않는다.

초기 조회는 named overview1회다. 최근30건과 별도 진행 중 최대1000건의
기존 조회·중복 제거·상한 경고·작업 예산 표시를 유지한다. 실패 행은 미조회로
표시하고 사용자가 선택한 실행 하나만 상세를 순차 조회한다. 성공 실행은
오류 로그를 조회하지 않는다. scoped run/tag·operation allowlist·인증은 그대로다.

한 page와 마지막 step 요약만 보존하고 run-level 실패를 찾으면 바로 표시한다.
빈 완료·미조회·오류·상한 도달 incomplete를 구분한다. 전체15초는 단조 시계로
요청 전과 최종 body 뒤에 검사하며 caller 취소와 결합한다. 오류를 null로 숨기지 않는다.

선택 변경·refresh·unmount는 이전 요청을 취소하고 버전을 무효화한다.
취소를 무시한 늦은 결과도 현재 선택/목록을 덮지 못한다. pending 동일 선택은
중복 요청하지 않고, 상세 오류는 목록을 유지하며 명시 재조회로 복구한다.
Common의 기존 controlled selection/detail props를 재사용하고 CSS를 fork하지 않는다.

## 검증과 한계

- OLD RED:38e+새 초기 fanout 회귀1개 FAIL(4회 vs1회). 선택 제외7건은 실패 수에 더하지 않았다.
- 최종 관리자 frontend 전체202 PASS(26파일), 그중 lib17·실제 React/Common DOM8.
- type-check·lint·production build PASS. lint 예외를 추가하지 않았다.
- 초기DOM6건은 jsdom25의 AbortSignal.any 부재로 실패했다. 테스트에만 Node22의
  정본 AbortController/Signal을 주입한 뒤 취소·경합을 다시 검증했다. 제품 polyfill은 추가하지 않았다.
- 최초 lint의 effect 안 동기 setState 지적은 초기 외부 요청과 사용자 refresh 상태
  변경을 분리해 해결했다. unused local도 제거했고 최초 실패 로그를 보존했다.
- UI 회귀: 초기1회, 성공 선택 무조회, pending중복 차단, 선택 변경 취소와 늦은
  응답 차단, 상세 오류/재조회, refresh/unmount 취소, incomplete, 목록 오류 보존.
- lib 회귀:20page상한·15초최종응답검사·2000자·cursor오류·HTTP/GraphQL오류·caller취소.

브라우저 취소가 proxy 뒤 Dagster 계산까지 강제 중단한다는 뜻은 아니다.
운영 배포·live E2E/UI·2인 적대 리뷰·CI·Docker2차·backend 재실행은 아직 NOT_RUN이다.
실제 CPU 감소율이나502해소를 로컬 green만으로 선언하지 않는다. 후속 검증을 마친 뒤 머지한다.
