# 2026-11-02 전체 PR 통합 새 이미지 반영

사용자의 “모든 PR 반영해서 이미지부터 새로 올려” 지시에 따라 열린 제품 PR을 통합하고 새 ARM64 이미지를 반영했다. 동일 코드라는 사유로 기존 이미지를 재사용하지 않았다. 고정 공식 nginx 이미지인 Transport gateway는 최신 구성으로 재생성했다.

- 통합 PR: #172
- 반영 원 PR: #31, #38, #81, #93, #128, #157, #161, #162, #163, #165, #167, #168, #170, #171
- 실제 이미지 제품 소스: `f22364dc08c94c4be88ade88cf635728d94c8272`
- 배포 최초 Invocation: `515ea7cb66274a7f8126ca6118133517` · 실제 정상 종료, Main PID0, cgroup 부재, 소유 자식 종료
- Manager current metadata: `/srv/ktdm-releases/transport-adopt-20261102T151552Z-70fd4a1f635d4e51963117b0b149cf4c` · adopt/verify/show healthy
- 원 일정: 19개 원래 상태 복원
- 백업·복원: 사용자 지시로 생략. 앱 백업 POST/목록 GET을 실행하지 않았다.
- 추가 독립 리뷰: 사용자 지시로 생략.
- 비공개 지도 키: BuildKit secret/기존 런타임 설정 유지. Git·문서·로그에 값을 기록하지 않았다.

|역할|실제 CID|이미지|역할별 제품 소스|실제 명령 포트|
|---|---|---|---|---|
|kor-travel-transport-backend-1|`d5ac6780a6dbf93d9b89414781f7e8161da435362dd744da2ebcaedd39c150f0`|`sha256:0ffe9631276dc2c37c01a79e5ad4479a5b8f6539c3ed1e7c290f0d44150d2951`|`f22364dc08c94c4be88ade88cf635728d94c8272`|`uvicorn app.main:app --host 0.0.0.0 --port 12302`|
|kor-travel-transport-dagster-code-server-1|`435ed7027df0ab97c24cf9cf7a30fad055d23b4bc1ee4af2fb9c8591c2c007de`|`sha256:0ffe9631276dc2c37c01a79e5ad4479a5b8f6539c3ed1e7c290f0d44150d2951`|`f22364dc08c94c4be88ade88cf635728d94c8272`|`dagster code-server start -h 127.0.0.1 -p 12306 -m app.dagster.definitions --location-name kor-travel-transport --inject-env-vars-from-instance`|
|kor-travel-transport-frontend-1|`85b7dca69943926df3c5cbfb4a47e74338421fdcdf18fbe3784d8a9fc45d0224`|`sha256:bbd4c9fa954228f75e9319e46435d9a2e53bcfc42412035b32cf9b17153b778c`|`f22364dc08c94c4be88ade88cf635728d94c8272`|`./node_modules/.bin/next start --hostname 0.0.0.0 --port 12303`|
|kor-travel-transport-transport-admin-web-1|`8d0ce563ba3b8414319a4a32608bf0c56c99403ccde53c29ba012eda394cd021`|`sha256:7004e07098b1056513630e30b7c987d0b5049f0393e604177bca969ca4ec5d0c`|`f22364dc08c94c4be88ade88cf635728d94c8272`|`sh -c npm run start -- --hostname 0.0.0.0 --port 12305`|
|kor-travel-transport-transport-api-gateway-1|`7901c6e76300b593b4a6a4c007af91ef8cb1ec76897b5e9d5db7d31ab76273a6`|`sha256:96868d9fa38f469a86d2f25787e43ee9ad330339d30be260aa9f5a338bb03751`|`공식 고정 이미지`|`nginx -g daemon off;`|

## 검증

- WSL 타입 검사와 출발·도착 지정/이름 단독 자동 확정 방지/오래된 응답 취소 회귀시험5개 통과. 지도 목록 일부 표시 시험5개 통과.
- 별도 Docker PostgreSQL18에서 기존0039→0040_archive_rail_merge 전환과 두 분기 테이블 생성을 확인했다. 기존 migration revision을 변경하지 않았다.
- 운영 같은 DB는0040_archive_rail_merge이며 Transport pg_dump18을 실제 확인했다.
- PC1440/mobile375에서 기본 철도 지도, 일반철도 실제 시간표·첫차/막차 API-DOM 행 수, 도시철도 저장표·첫차/막차, VWorld 실제 이미지 타일을 확인했다.
- 이번 성공 수집 세대만 유가 요약에 쓰는 정책과 영구 집계 이력을 유지했다. 추가 수집·통계 재발행·archive/backfill/prune를 실행하지 않았다.
- 기존 철도 초도2357저장/967제공기관 자료없음은 별도 관측 결과다. 자료없음을 운행 중단이나 저장 성공으로 바꾸지 않았다.
- CI41454776748의 frontend·transport-admin은 성공했다. backend는1717통과/2생략/54subtest통과, 제거한 구 호스트 스크립트의 문서 링크1건 실패였다. 원 실패를 보존하고 cbdea2da에서 문서만 정정한 뒤 해당 WSL 시험2개를 통과했다. 이를 전체 CI 재성공으로 바꾸지 않는다. live-e2e job 생략과 위 운영 Firefox 관측도 구분한다. 기존 시험 계약 정렬65개와 PostgreSQL18 migration 시험 격리21개가 통과했다. 시험·문서·퇴역한 호스트 도구 정리로 제품 이미지를 다시 빌드하지 않았다.
- 한국시간11월3일 서울→부산75편과 서울역 도시철도 저장표488행의 API-DOM·첫차/막차를 PC/모바일에서 대조했다. 기본 철도 지도는 별도 종류 선택 없이 표시됐다. 유가 지도5유종의 지역 카드 가격이 실제 API와 일치하고 update_pending=false였다. 준비 완료 캡처까지 PC5.566초/모바일4.486초이며 로그인·렌더링을 포함한 관측으로 API 단독 응답시간이 아니다. 지역 라벨 겹침 과제와 제공기관 자료없음은 그대로 남는다.
- 각 화면 수평 넘침 없음, 로그아웃과 소유 브라우저 프로세스 종료를 확인했다.
- 실제 화면/원문은 Git 밖 작업 원장에 보관했다. 다른 서비스·공용 daemon·비공개 환경 파일을 보존했다.
