# Transport #86 운영 배포·UI 수용 결과

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

## 초기 UI 실패와 후속 검증

기존 실제 UI 34개 중 첫 결과는 33 PASS/1 FAIL이다. 로그인·지도·native identity·monitor 오류
복구는 통과했지만, 당시 관리자 웹의 Dagster 실행 링크가 이전 공개 origin을 사용했다.
실제 링크 30개를 확인했으며 시험 기대값만 바꿔 통과 처리하지 않는다.
NEXT_PUBLIC_TRANSPORT_DAGSTER_URL을 현재 Odroid 공개 origin으로 명시해 두 환경 파일에
영속화하고 관리자 이미지만 재빌드·교체한 뒤 아래 최종 UI를 재검증했다.

링크 수정 전 이미지에서 별도의 새 주소 UI 10개는 n150 Chromium으로 모두 통과했다.
익명 조회 401, 로그인, 실제 sidecar 요약, 데스크톱 1365px·모바일 390px,
허용되지 않은 Origin 403, 수동 실행 QUEUED/202, 같은 요청 재전송 시 동일 실행,
다른 요청 중복 409, 로그아웃 후 보호 경로 이동을 확인했다.
시험이 생성한 실행은 native SAFE_TERMINATE로 CANCELED 처리했으며 기존 대기열 3개는 보존했다.
daemon OFF 상태의 접수 시험이므로 실제 수집 실행 완료를 의미하지 않는다.
새 UI 증거 SHA256: e58c8d26bb1414efeb3d18ef285b852e3bcb167382927c22967407bdacb3e954.
취소 증거 SHA256: 7341fa732ac2bc9b5de90455926cebc270d4a8f18e4a184dccaa85ab8d86b137.

## 링크 수정 배포와 최종 UI

같은 제품 2c9b416c의 공식 Admin Dockerfile에 현재 Dagster 공개 origin을 빌드 인자로
명시했다. 새 ARM64 이미지 sha256:14e8c212173a7b06cfd4f8a0acd528d26d2afa11c39def3b1182e2dc555ad3ee의
컴파일된 JS에서 현재 origin 2개·이전 origin 0개와 run 경로 연결을 확인했다.
빌드 276.24초, 격리 검사 network none/read-only이며 기존 Admin과 이미지 Config가 같았다.

prepare 통과 후 Admin만 정상 종료·보존·교체했다. 두 환경 파일의 설정을 일치시키고
whole model에서 Admin 이미지와 해당 빌드 인자 이외의 변경이 없는 것을 확인했다.
새 Admin healthy·PID 고정, 다른 역할과 공유 서비스 수명·기존 큐 보존·daemon OFF로 완료했다.

최종 기존 UI는 34/34 PASS이며 이전에 실패했던 Dagster 링크도 통과했다.
주소 UI 10개도 새 Admin에서 다시 10/10 PASS였다. 시험용 QUEUED 실행 한 건을
정확한 job/location/request 태그로 확인 후 SAFE_TERMINATE하여 CANCELED로 만들었다.
큐는 4개에서 기존 3개로 돌아왔고 다른 실행은 보존했다. 수집 본체를 실행한 결과는 아니다.

최종 UI34 증거 SHA256: 1c294e12000553411dbbda044d08f868ca49f8357eb8c4616ac7fbce928844ab.
최종 주소 UI10 증거 SHA256: 96735b1c3abb2d520ee487f42a900849d4ba34e32ccd6718e4fa9445ae31ba8e.
최종 취소 증거 SHA256: 5140ea9810f7d8f0cc6be3dc8b38623df8209b576af7176ae35f7bf521a58aa9.

원 33/34 실패와 수정 전 주소 UI10 결과는 위에 별도 이력으로 남겼다.
이번 최종 UI에서 제공자 호출을 반복하지 않았으며 실제 VWorld·KST 6개월 저장값 검증은
앞 절의 별도 시점 결과다. Kakao fallback과 전체 갱신 sweep·자동 tick은 미검증이다.
원천 데이터·나머지 세 역할은 이 링크 수정 때문에 재배포할 필요가 없다.
기존 [제품 리뷰·정확 CI](2026-10-18-native-address-final.md)와 운영 수용을 구분한다.
문서 PR의 CI는 사용자 요청대로 생략하며 제품 CI 성공으로 계산하지 않는다.
daemon ON 수집 완주 및 전후 수집 CPU·RSS 개선은 후속 작업이다.
