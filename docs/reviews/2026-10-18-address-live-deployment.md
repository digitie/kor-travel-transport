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

READ ONLY 추가 조회에서 실제 VWorld 결과의 resolved_at은 2026-10-18T07:07:13.429664Z,
next_refresh_at은 2027-04-18T07:07:13.429664Z였다. KST 달력 기준 6개월 일치를 확인했다.
이는 저장된 다음 갱신 시각의 검증이며 daemon의 자동 실행을 검증한 결과는 아니다.
시각 증거 SHA256: 702b49de15bb8aac95a7ae1d18e3a2fab72e2e66544f65e7298f09e887dc114c.

## UI 결과와 남은 수정

기존 실제 UI 34개 중 첫 결과는 33 PASS/1 FAIL이다. 로그인·지도·native identity·monitor 오류
복구는 통과했지만, 관리자 웹의 Dagster 실행 링크가 이전 공개 origin을 사용한다.
실제 링크 30개를 확인했으며 시험 기대값만 바꿔 통과 처리하지 않는다.
NEXT_PUBLIC_TRANSPORT_DAGSTER_URL을 현재 Odroid 공개 origin으로 명시해 두 환경 파일에
영속화하고 관리자 이미지만 재빌드·교체한 뒤 최종 UI를 재검증한다.

링크 수정 전 이미지에서 별도의 새 주소 UI 10개는 n150 Chromium으로 모두 통과했다.
익명 조회 401, 로그인, 실제 sidecar 요약, 데스크톱 1365px·모바일 390px,
허용되지 않은 Origin 403, 수동 실행 QUEUED/202, 같은 요청 재전송 시 동일 실행,
다른 요청 중복 409, 로그아웃 후 보호 경로 이동을 확인했다.
시험이 생성한 실행은 native SAFE_TERMINATE로 CANCELED 처리했으며 기존 대기열 3개는 보존했다.
daemon OFF 상태의 접수 시험이므로 실제 수집 실행 완료를 의미하지 않는다.
새 UI 증거 SHA256: e58c8d26bb1414efeb3d18ef285b852e3bcb167382927c22967407bdacb3e954.
취소 증거 SHA256: 7341fa732ac2bc9b5de90455926cebc270d4a8f18e4a184dccaa85ab8d86b137.

이 문서 시점에는 링크 수정 후보의 빌드·재배포·최종 UI는 미완료다.
원천 데이터·나머지 세 역할은 이 링크 수정 때문에 재배포할 필요가 없다.
기존 [제품 리뷰·정확 CI](2026-10-18-native-address-final.md)와 운영 수용을 구분한다.
문서 PR의 CI는 사용자 요청대로 생략하며 제품 CI 성공으로 계산하지 않는다.
daemon ON 수집 완주 및 전후 수집 CPU·RSS 개선은 후속 작업이다.
