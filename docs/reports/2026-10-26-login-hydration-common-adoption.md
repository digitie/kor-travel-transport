# 공통 로그인 hydration 준비 경계 채택

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

설계 초안만 준비했다. Common 제품 source는 `f0b60bb70e65d53219f2a4bda57115c4e8fa2144`이며 두 독립 리뷰·CI는 진행 중이다.
채택 제품·단위·소비자 CI/UI는 아직 NOT_RUN이다. 두 리뷰·CI·실제 UI 전 main merge나 운영 변경을 하지 않는다.
이 PR revert로 package/lock/vendor와 회귀를 원복한다. 기존 세션과 운영 자격증명은 수정하지 않는다.
