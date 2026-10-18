# Transport #86 운영 배포·수용 진행

2026-10-18 제품 2c9b416cc92f18cd6f4c47c1852344c7049ad67c를 Odroid NVMe에 배포했다.
현재 소스·API·code server·일반 웹·관리자 웹을 교체했으며 자동 daemon은 OFF다.
기존 설정 5개를 같은 순서로 렌더하고, 두 환경 파일과 소스를 일치시켰다.
정상 종료·기존 컨테이너 보존·새 컨테이너 health·worker0·외부 서비스 설정과 대기열 보존을 확인했다.

## 운영 DB와 제공자

마이그레이션 0025_reverse_addresses 적용 후 READ ONLY 조회로 버전, sidecar 테이블 2개와
보조 인덱스 3개를 확인했다. 실제 VWorld 단일 대상 확인은 requests1/failed0으로 성공했다.
원천 5개 테이블 전체 행을 순회한 전후 해시는 같았다(버스795·철도1108·나머지3표0행).
단일 대상 성공은 전체 제공자 sweep·Kakao fallback·자동 6개월 tick의 운영 수용을 의미하지 않는다.

DB 증거 SHA256: 8a820bc1642910d54e5a3f2567d039d048ec6356297c38a4ea6ce11d830751a3.
단일 대상 증거 SHA256: d721e01f05a5ad85e6ca4458d03fcc25ce36891e0c4ab430103501a43e15b76f.

## UI 결과와 남은 수정

기존 실제 UI 34개 중 첫 결과는 33 PASS/1 FAIL이다. 로그인·지도·native identity·monitor 오류
복구는 통과했지만, 관리자 웹의 Dagster 실행 링크가 이전 공개 origin을 사용한다.
실제 링크 30개를 확인했으며 시험 기대값만 바꿔 통과 처리하지 않는다.
NEXT_PUBLIC_TRANSPORT_DAGSTER_URL을 현재 Odroid 공개 origin으로 명시해 두 환경 파일에
영속화하고 관리자 이미지만 재빌드·교체한 뒤 최종 UI를 재검증한다.

이 문서 시점에는 링크 수정 후보의 빌드·재배포·최종 UI는 미완료다.
원천 데이터·나머지 세 역할은 이 링크 수정 때문에 재배포할 필요가 없다.
기존 [제품 리뷰·정확 CI](2026-10-18-native-address-final.md)와 운영 수용을 구분한다.
문서 PR의 CI는 사용자 요청대로 생략하며 제품 CI 성공으로 계산하지 않는다.
daemon ON 수집 완주 및 전후 수집 CPU·RSS 개선은 후속 작업이다.
