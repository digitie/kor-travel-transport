# 최신3f 운영 빌드·배포 수용 체크포인트

이 문서는 2026-10-27 **21:02:54Z의 운영 빌드 관측**까지 고정한 초안이다. 문서 작성자가 추가 운영 조회나 변경을 실행한 결과가 아니다. 이후 실제 cutover 결과로 갱신하며, 아래 미완 항목을 성공으로 바꾸지 않는다.

## 완료한 코드·격리 검증

- 최신 원격 main과 배포 준비 source는 `3f5160a0d5e0c246fa744864998a3fc805542ce4`다. PR #154의 통합 변경과 이미 머지한 PR #155의 교통 저장 배치 개선을 포함한다. 후속 문서 커밋은 새 이미지가 필요하다는 뜻이 아니다.
- exact3f의 GitHub backend·frontend·transport-admin 세 check가 SUCCESS다. GitHub `live-e2e` check는 SKIPPED이며 이를 성공으로 바꾸어 쓰지 않는다. 별도 실제 격리 UI39 수용은 아래 근거다. 과거65a의 CI6 결과와 구분한다.
- exact3f 프론트엔드를 **새로 컴파일**한 뒤 같은 source의 격리 PG18/schema0036·실제 API·Next·브라우저에서39개가 통과했다. 이전3bf/65a Next 재사용 결과를 새3f 컴파일로 바꿔 쓰지 않았다.
- UI는 모바일·데스크톱, 기존32개와 유가 통계 D-1/D-6·누락일·안내창을 포함한39개다. 14.569초, API15·tile40, 초기 script hold8개와 정상 종료·소유 API/PG·volume·unit/cgroup·터널/C7 정리를 확인했다. 고정 합성 fixture의 가격·날짜·신선도는 운영 데이터의 검증값이 아니다.
- Manager는 Odroid `f368af3e` 공식 설치와 공개 UI12 수용·문서 PR #564를 마쳤다. n150은 같은 제품 `d1468213`를 유지했다. 원래 설치 후 CLI25초 timeout과 뒤이은 Transport 공식 stage의 필수60초 검사 성공을 구분한다. 40.166초는 stage 전체이며 CLI 단독 시간이 아니다.

## PR155 실측의 의미

[교통 저장 배치 운영 전 기록](2026-10-27-traffic-store-batched-prefetch.md)의 측정은 Linux amd64/WSL·PG18·고정 입력8,300개 관측의 **저장·commit 구간**이다. 같은 phase 안에서 원본·후보6회의 전체 행 digest가 같았고, client CPU·wall 중앙값이 약93% 줄었다. 전체 Dagster job, 원천 fetch, 운영 ARM 또는 서버 전체 CPU가93% 줄었다는 증거가 아니다.

표본 RSS 중앙값은 신규·정정·원입력 재적용에서 약2.90/3.35/3.25MiB **증가**했다. 서버 RSS와 ARM 전체 수집 전후는 아직 측정하지 않았다. 수집 CPU 개선과 메모리 저감을 같은 완료 항목으로 묶지 않는다. 이번3f 체크포인트에서 이 성능 시험을 다시 실행하지 않았다.

후보 API의16개 수집 관련 설정은 격리 검증에서 OFF였다. 운영 수집을 중지했다는 뜻이 아니며, 이번 문서 작업이 운영 설정·기존 lock/fence·소유권 경계를 바꾸지 않았다.

## 운영에서 완료한 준비와 미완 빌드

정본 Manager를 통해 최신3f source stage가 정상 종료했고 Git source827개·보호 파일/환경과 기존 runtime 보존을 확인했다. 현재 서빙4d와 desired3f를 같은 것으로 취급하지 않는다.

**21:02:54Z 관측에서는 backend 빌드가 약22분 진행 중이었고 전체 빌드는 미완료였다.** 고유 빌드 unit은 active/running, 마지막 phase는 backend building, 최종 result는 없었다. 이 관측만으로 backend 이미지 완성, frontend/admin 빌드 완료, unit 정상 종료나 배포 성공을 주장하지 않는다. 당시 source와 NVMe·정본 G→R·소유 builder 상한을 따른 T의 별도 운영 경로가 진행 중이었다. 다른 builder를 중지하거나 잠금을 우회하지 않았다.

이전 G 경합으로 실제 build0이었던 실행, 첫 prebuild 계약 거부와 보존 검사, source 재준비 이력은 남긴다. 후보 UI의 최초 mux 경로/API 종료 기록 실패와 첫 성능 SDK 준비 실패도 기존 기록에서 지우지 않는다. 제어된 후속 성공은 원 실패를 무효로 하지 않는다.

## 남은 실제 수용

- [ ] 공식 backend/frontend/transport-admin 세 이미지의 완성·불변 imageID·정확 source, 소유 빌드 종료·정리와 원장 검증.
- [ ] native 전체 catalog·selector/state 두 ID·원 상태 capture, Transport 원 RUNNING만 pause, tick 두 관측·다섯 active 상태·물리 worker 및 별도 PG writer의 자연 drain 수용.
- [ ] 정본 prebuilt cutover와 실제 API/code-server/admin source·schema·포트·호환 health 검증. T01 API/CS 동일 설정 앵커와 T05 제한 rollback 정책이 같은 release에 포함됐는지 확인.
- [ ] 원 RUNNING만 원복하고 원 STOPPED·다른 location·공용 daemon과 보호 서비스 상태를 보존한 실제 결과.
- [ ] **운영 공개 UI35** 수용. 기존32개와 실제 유가 DTO·card/dialog·모바일 구조3개를 검증하며 격리39의 합성 가격/D-1/D-6 값을 운영에 복사하지 않는다.
- [ ] 자연 수집의 성공·실패 안정성, 실제 ARM 전체 job CPU·메모리·PG 비용 전후 측정. 비교 가능한 입력·실행 구간·다른 부하를 함께 기록한다.

현재 문서는 위 항목을 완료 처리하거나 native helper를 변경·실행하지 않는다. 실제 실행·cutover는 T, 공개 UI와 자원 슬롯은 Root의 별도 검토 경계를 따른다. 코드·격리 시험 수용을 운영 배포 완료로 확대하지 않는다.

## 근거 지문

민감한 원장은 저장소 밖에 보존하고 여기에는 식별 지문만 남긴다.

| 근거 | SHA256 |
| --- | --- |
| exact3f fresh Next build | `96c279d4fd3de38186f961f7972dba577bb5daaed8c3a1fe7cdb942588fdac3b` |
| exact3f 실제 격리39 | `b4875de6ca68e07d8aa0e78455612ca6733a9c0f32642ebafd5c4ebecc4370ac` |
| 격리39 독립 실제 수용 | `e04d1459bb78575e6c00346549edfbb5d639c14a25cad651270780da8c9e4c0b` |
| 최신3f 공식 stage와 보존 | `13e66c9a039f77b8eee617dfebae3858c95c1d4b5c811b2939e4066e125fa210` |
| 21:02:54Z 미완 빌드 관측 | `5a2fd0205d84ee571f7c46c05ced0cdce5ef029bf50745eec770b85d2268409d` |
| PR155 저장 실측 raw | `b9d501f3aff0574c68f633b81befbfde59a830a209c6a35c939c17c73201bc08` |
| PR155 독립 실측 검산 | `7554c83f92098f29fe6ee09c6680ff40748ac74f944546770c33eb8c90462f8f` |
