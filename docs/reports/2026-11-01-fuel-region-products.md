# 지역 유가의 모든 유종 동시 표시

시도·시군구별 카드 하나에 휘발유·경유·고급유·등유·LPG를 함께 표시하고 ‘평균’ 문구는 제거한다.
숫자는 기존 API의 유종별 집계를 반올림해 표시하며 계산 방식은 바꾸지 않는다. 자료가 없으면 미제공이다.
유종마다 다른 대표 좌표가 있어도 같은 region_key를 카드 하나로 묶는다. 서로 다른 지역·출처를 섞지 않는다.
지역 카드는 유종 필터와 무관하게 다섯 유종을 함께 읽으며, 줌12 이상 개별 주유소와 목록의 유종 필터는 유지한다.

원 코드에서 시도·시군구의 동시 표시 회귀2개가 실패했다. 수정 후 WSL 관리 UI366개(QA 예시1개 포함),
Docker 정식365개·타입·lint·Next 빌드를 통과했다. Docker 첫 실행의 QA 예시 경로 실패는 보존했다.
운영은 관리 UI만 반영하며 API·수집기·DB·일정·Weather·백업/복원은 변경하지 않는다. 실제 결과는 아래 정산을 따른다.

## 실제 운영 반영과 화면 검사

관리 UI 제품 `add7dea905ea0bcf4506468efe1240c2b755d046`만 반영했다. 실제 CID는 `b76f485a5191fc63b8df9c4b50cd1393745cbe94e114efdb0bc60e88f5b44292`,
이미지는 `sha256:14423b95c46dd4270b161f8b3bf052c19108caeb2383115db4c8177164c55db2`, 실제 Cmd 포트12305다. API CID53380200ac1e/이미지a30c786b는 유지했다.
기존 Compose 서비스의 CID·이미지·시작 시각, 보호4파일과 버전 표식을 제외한 관리 UI 환경은 동일했다.
수집기·공개 프론트엔드·gateway·Weather·일정·DB 마이그레이션은 변경하지 않았다.
기존 RUNNING 빌더는 유지하고 9415 빌더는 STOP 상태를 유지했다. 백업·복원은 사용자 지시로 생략했다.

Manager `/srv/ktdm-releases/transport-adopt-20261101T004256Z-ce1193b77b6845a782b72249021058ea`는 healthy·issues0이다.
별도 반영 unit29ed의 첫 Invocation93cbab6333164489a952f6fa14085480은 실제0·Main0·cgroup 부재·소유 자식 종료다.
제품 add7dea의 backend/frontend/transport-admin CI는 모두 성공했고, 자동 live-e2e SKIP을 PASS로 바꾸지 않았다.
실제 Firefox157 PC1440/모바일375의 시도·시군구 카드마다5행·‘평균’ 문구 없음·가격 DTO/DOM 일치를 확인했다.
더 확대해 PC는 주유소13개/클러스터13개, 모바일은 주유소1개/클러스터5개로 기존 전환을 확인했다.
가로 넘침0·logout303·쿠키0, 캡처한 소유 브라우저/driver9PID의 동일 신원 잔여0과 검사 종료0을 확인했다.

원문·SHA는 `transport-fuel-all-products-20261101/post-live-acceptance.json`,
실제 캡처는 `before/sido-1440.png`·`before/sido-375.png`와
`after/sido-1440.png`·`after/sido-375.png`·`after/sigungu-1440.png`·`after/sigungu-375.png`,
개별 카드 캡처는 `after/card-1440.png`·`after/card-375.png`다.
단위는 공통 머리글 원/L로 표시하며, 응답에 없는 유종은 미제공으로 남긴다.
분석·범위 통계의 ‘평균’ 지표와 인접한 다른 지역끼리의 라벨 충돌은 이번 변경 대상이 아니다.

## 원 실패 보존

첫 unit5d90은 관리 UI 교체에 불필요한 backend/CS instance producer가 unavailable이어서 빌드·up 전에 실제1로 종료했다.
관리 UI 전용 경로는 실행 중인 수집기의 기존 읽기 전용 정본 mount를 Compose 해석에 재사용한다.
정본 파일의 root 소유·단일 링크·파일명/내용 SHA 일치와 기존 mount 동일성을 확인했으며,
이 경로를 backend/CS 배포의 instance producer 대신 사용하지 않는다. 설치·prepare·수집기 전환은 하지 않았다.

다음 unit6b90은 build-admin 자식0·실제 이미지14423b95 완성 뒤, 동일 mount 배열의 순서가 달라 검사에서 실제1로 종료했다.
목적지로 정렬하면 모든 필드가 동일함을 새 읽기로 확인했다. 첫 unit과 두 번째 unit을 재시작하지 않았다.
별도 반영 unit은 기존 실제 이미지를 검증해 소비했으며 재빌드0이다. 최초 DNS 단발 실패도 기록했고
전역 DNS 설정을 바꾸지 않고 정상 조회 확인 후 실제 UI 검사를 통과했다.
