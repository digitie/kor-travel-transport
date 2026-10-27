# 공통 로그인 hydration 준비 경계 채택

## 2026-10-27 최신 운영 상태

공통 dev.9를 소비한 PR #141은 머지·배포를 마쳤다. 최신3691 공개 HTTPS UI32에서 실제
SSR의 입력·submit 비활성화와 hydration 뒤 로그인·세션·로그아웃303·보호 GET401을 확인했다.
[최종 운영 원장](2026-10-27-integrated-production-rollout.md). 아래 준비·미배포 절은 당시 이력이다.

별도 Native375/1440도 hydration 뒤 로그인과 정확 callback을 확인했다. 첫 Native 로그아웃 이벤트
미포착은 보존하고 auth 전용 후속에서303/auth cookie1→0·보호 페이지 복귀를 확인했다.
항공편 누락·분석 지연까지 전체 성공으로 확대하지 않는다.
[별도 최초 UI·배포 독립 검산](2026-10-27-parking-cache-rollout.md).

## 관측과 의존

기존 운영 UI 진단에서 로그인 단계의 native `POST /login` 차단이 확인됐다.
상세 hydration 지연 원인은 별도이며 이전 실패·재현되지 않은 진단을 성공으로 바꾸지 않는다.
Common [PR47](https://github.com/digitie/kor-travel-common/pull/47)의 T-217은 SSR·최초 client HTML에서 입력과 제출을 disabled로 닫고 effect 준비 뒤 기존 callback으로 제출한다.

## 최소 채택

- 최신 Transport main에서 별도 branch를 사용하고 기존 CPU138·Manager139 및 원본 dirty 변경을 포함하지 않는다.
- Common 정규 dev.9 tarball과 SHA256/source를 고정하고 package.json·lock만 같은 산출물로 정렬한다. 기존 dev.8 tarball은 보존한다.
- 앱의 인증 endpoint·세션·CSRF·redirect·로그아웃·API/DTO·provider·DB·배포 설정은 변경하지 않는다.
- 실제 앱 LoginForm을 SSR한 DOM에서 준비 전 native submit 부재와 hydration 후 정확 `/api/auth/login` callback 요청만 검증한다. 실제 공개 UI는 Root가 별도로 실행한다.

## 현재 gate와 rollback

Common 제품 source는 `f0b60bb70e65d53219f2a4bda57115c4e8fa2144`, CI 표기/fixture 정렬 후속은 `44d7a240ebe82b11389824fd503e33ca4000ddd7`이다. 제품과 정규 dev.9 산출물은 같다.

- vendor SHA256: `b738d8824e36eb6e58d8cc6b78af7dc31233b6763248d634286044def795b403`. 27파일 중 기존 dev.8 대비 `dist/login-form.js`와 package metadata만 바뀌었다. 기존 tgz는 보존했다.
- source package·lock는 이 파일 경로/버전·실제 SHA512 integrity만 정렬했고 다른 의존·앱 인증 구현은 바꾸지 않았다.
- 실제 앱 LoginForm의 SSR·hydration callback 회귀는 교체 전 1 FAIL/1 PASS, 교체 후 2 PASS다. 준비 뒤 실제 callback의 `/api/auth/login` JSON 1회·pending 중복 차단·401 실패/재시도·native submit 0을 검증했다. HTTP는 단위 대역이며 실제 인증 수용과 구분한다.
- 정규 `npm ci --offline --ignore-scripts` 후 frontend 39파일/284 PASS(17.05초)·`npm run type-check`·`npm run lint` PASS다. 로컬 Node22.22.2/npm11.19.1 범위다.
- Common 정확 후속 CI8 SUCCESS와 두 FULL+delta 리뷰는 Common 범위이며 이 소비자의 CI/실제 Next 후보 UI는 아직 미완이다. 로컬 공개 UI·운영·이미지 빌드·PG는 실행하지 않았다.

Common 실제 소비자 검증→Common merge→Transport 최종 source/main 정렬·CI/merge→별도 ARM 빌드·운영 순서로 진행한다. 각 단계는 Root가 판정하며 지금은 Draft다.
이 PR revert로 package/lock/vendor와 회귀를 원복한다. 기존 세션과 운영 자격증명은 수정하지 않는다.
