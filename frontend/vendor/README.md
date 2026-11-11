# 공통 UI 통합 후보

관리자와 같은 부모 pack의 UI 0.2.0/tokens 0.1.1을 사용한다.
버전·정확한 SHA512는 [`../common-artifacts.json`](../common-artifacts.json)에 고정하며,
`npm run check:dependencies`가 실제 tgz·lock·원장을 대조한다.
이 디렉터리에서 재pack하지 않는다. 정식 릴리스와 운영 배포는 부모 통합 후 별도 게이트다.
