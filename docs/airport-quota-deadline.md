# 공항 KAC quota 대기의 원래 종료시각 보존

ICN 수집이 정상이어도 KAC가 quota 대기 중이면 native partial_success가 반복된다. 예전에는
최신 non-skipped native run.started_at에서 backoff를 재계산해 KAC 대기가 영구 연장될 수 있었다.
118 marker 보존과 별개인 운영 rollout 전 필수 수정이다.

기존 transport_collection_states의 source=airport_kac_quota, last_started_at/next_due_at을
사용한다. schema나 오류 문자열 파싱을 추가하지 않는다. 실제 quota 실패 run의 원래 started_at과
설정 backoff로 until을 확정한다. blocked 관찰은 원래 until을 읽기만 하고 연장하지 않는다.
구배포 native 오류는 한번만 명시 deadline으로 채택한다. deadline이 있거나 만료된 state가
준비된 뒤에는 새 blocked native run의 시각으로 과거오류를 다시 계산하지 않는다.

원래 until이 지나면 provider를 정상 재시도하며 실제 새 quota 실패만 새 deadline을 만든다.
실제 nonquota 결과는 만료된 deadline을 해제한다. 오래된 worker의 정리/실패는 source행 잠금과
origin 비교로 새 deadline을 지울 수 없다. 초기 비quota 성공도 원장행과 origin fence를
전진시켜 새성공 뒤에 도착한 옛 quota 실패가 대기를 다시 만들지 못하게 한다. 표의 last_success_at은 임의로 KAC 성공을 주장하지 않는다.
Map flagON/OFF 모두 공항 collector의 기존 live quota 판정을 사용한다. source raw/provider 파싱과
기존 이력·API계약은 그대로다. 즉시 quota를 반복 호출하거나 남은 KAC fee 순회를 계속하지 않는다.
ICN 수집은 계속된다.

두 독립 리뷰/정확CI/로컬PG·Compose 검증 전 운영 배포하지 않는다. 공유 daemon과 활성수집은
root 조율 아래 유지한다. 이 문서의 구현은 PR118 고정 범위와 분리한다.
