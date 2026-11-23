# Common 정본 산출물 채택

## 2026-11-23 — 공통 UI 0.2.5

Common main CI의 [pack 산출물](https://github.com/digitie/kor-travel-common/actions/runs/45095095455/artifacts/14782962353)에서 UI 0.2.5와 tokens 0.1.6을 가져왔다. pack 출처는 `fe141143cc8ba75e8fd0b6134e1c9e518e294fa2`, 카탈로그와 정책은 `ade7b3eb50c0197caad4a1c98fcb97cffbc2a8a4`로 고정한다. 두 tarball의 SHA256과 SHA512 SRI를 Common 카탈로그와 대조했다.

## 2026-11-19 — 공통 관리자 셸 0.2.3 후보

Pack source: 0e2a3f5aa16323df0d009360802661c9bc496dc6
Catalog/policy: d644632ea9eaf2f6b6baa49305d65fae5bbc0bd4
Publication: https://github.com/digitie/kor-travel-common/actions/runs/44459847805
Artifact: 14500111373
ZIP SHA256: 19881f2c3ed598ed7ec213c559be21ece2be77068bddee6de5bd249b6f8019e1

- @kor-travel/ui 0.2.3 sha512-upv+JtiVcF+zg3C/KcZy9UQckx0n3vc0n4ANr3/elWM8PQ4srljxgTQmaBK4IxulEj8pd8gc7mnG3M67oFIQUQ==
  - SHA256 aa19793165ae37b2214d210692e23235545e1464c4e0059f99d943411fa753d9 / 일반 파일 96개
- @kor-travel/tokens 0.1.4 sha512-k6StI02tH/iRxKimczN0btU+MS9AvDZLlR/6Bn6xQHhZ5Mb79pkyIALd4RkoLT2GP3qlwR89YEgOaBiBxACDpA==
  - SHA256 33d08d7b37c60d3e319da19608ce05137f6bf587dc8d42e3ce0dfb4b597a61fc / 일반 파일 25개

중앙 main-push artifact의 실제 두 pack을 그대로 채택했다. 이 앱은 toast를 사용하지 않는다. UI96+tokens25=121개를 후속 정상 이미지/native 단계에서 검산한다. 현재 운영219의 Common119개 수용과 이번 소스 후보를 구분한다.

## 이전 채택 이력
Pack source: 706aaa7821588dfca72f660c9161f56be2d0445f
Catalog/policy: 5c1b3857e9af060d30ec776157760fb9e9c13ded
Publication: https://github.com/digitie/kor-travel-common/actions/runs/44313659808

- @kor-travel/tokens 0.1.3 sha512-m1WsuJw1DHYxAkPsJpAIrFN5P/Udb+Ln/sZHbrmPJpItQDHx+wuf8QEFgSrBsk5yW+NAX5CQnIQZRkPIFwO97A==
- @kor-travel/ui 0.2.2 sha512-/odxLZlFlMj0IB8oPMyjE77kj1MtZO46m/lyHiCTW/gYFq7o6XUSrSPOC7rm7cyEpbjD8dAnCqcz7zmE2GWF+Q==

기존 의존성만 갱신했다. npm lock 재생성과 소비자 guard 검증은 별도로 수행한다.
