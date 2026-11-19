# 주차 이력 DB 수신 중 API 실행 기회

기준은 공통 UI가 포함된 PR220 merge `abbf456ab249c6b5971f97d42115a2eb6cbf3d22`다. 이 변경은 `load_snapshot`의 DB 결과 수신만 분할한다. 전체 이력 데이터를 한 번에 Python 행으로 만들면서 event loop를 점유하는 구간이 있어, 기존 CPU 스레드의 협력 실행만으로는 다른 API에 실행 기회를 충분히 주지 못했다.

## 변경

SQLAlchemy 공개 `AsyncSession.stream`/`AsyncResult.partitions`로 2,048행씩 받고 다음 묶음 사이에 다른 async 작업이 실행되게 한다. 수신 완료 뒤 세션을 닫고 기존 CPU 스레드의 snapshot 구성·인코더를 호출한다. 실패나 취소는 cursor와 session을 닫고 부분 snapshot을 게시하지 않는다.

수신한 여섯 필드는 표준 라이브러리 NamedTuple에 담고 동일한 공항 코드 문자열은 이번 구성 안에서만 재사용한다. 일반 Row를 전부 보관하는 단순 streaming 후보는 별도 프로세스 측정에서 약565.5MiB를 써 제외했다. 외부 의존성·전역 캐시는 추가하지 않는다.

기존 최대 ID 고정·30일 범위·live 우선 중복 제거·수집시각/ID 정렬·공항/주차장 필터와 원본 변경 후 게시 거부를 유지한다. 5초 폴링과 30초 미검증 거부, 압축·정상/실패 상태의 의미도 그대로다. 스키마·API·수집 job을 바꾸지 않는다.

## 검증과 범위

- 관련 로컬 시험21PASS·PostgreSQL 전용1SKIP. 새 시험은 DB 묶음을 다 받기 전에 다른 API 작업이 실행되는지, 전체 응답 값/순서, DB 수신 오류·실제 task 취소 시 cursor/session 정리와 부분 snapshot 차단을 검사한다. 기존 SQL의 live 우선·최대 ID 조건 시험도 유지한다.
- 기존 격리 PostgreSQL fixture의 일회용 DB에50만 native 행과1,000개 migration 중복을 넣었다. 실제 최종 파일을 import한 함수와 불변 PR220 기준 함수를 각각 새 프로세스에서 실행해 SQLAlchemy 두 쿼리 shape와70,860,026바이트 전체 응답 해시가 같음을 확인했다. cursor의 추가 FETCH 왕복은 있으며, 두 shape라는 표현이 전체 네트워크 왕복2회를 뜻하지 않는다.
- 이 최종 한 쌍에서 event loop 최대 지연981.45→113.93ms, 프로세스 CPU3,631.88→2,925.66ms, 최대 RSS498.0→475.4MiB였다. 전체 시간8,058.66→4,919.97ms는 순차 DB cache 상태가 달라 운영 개선율로 쓰지 않는다. 이 fixture의 메모리 관측은 임의의 큰 데이터까지512MiB를 보장하지 않는다.
- 최초 일반 streaming3교대 쌍은 동일 본문에서 최대 event loop 지연 중앙849→107ms였으나 전체 생성은 약3.6% 늘었다. 최종 compact 행 경로와 구분한다. event loop 최대 지연은 HTTP p95나 철도역 최초1초 달성의 증거가 아니다.
- 시험용 DB는 실행마다 자기 UUID DB만 삭제했다. fixture 준비 중 타입 추론·큰 seed 문장 상한 실패는 별도 원문에 보존했고 성공으로 세지 않았다. 운영 조회·수집·캐시 삭제는 없었다. 실제 source 해시와 원문은 비공개 `transport-history-fetch-yield-work` 증거에 결박한다.

다음은 독립 두 집중 리뷰·정확 CI, 정상 캐시 이미지/native, SDK 배포와 실제 응답 검증이다. 공통 UI PR220의 진행 중 배포와 이전 영수증은 이 후보 결과로 바꾸지 않는다. TRN04의 운영 재구축 중/밖 지연과 철도역 최초1초 목표는 실제 수용 전이다.
