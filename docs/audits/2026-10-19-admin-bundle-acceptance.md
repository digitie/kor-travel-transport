# 관리자 ARM 번들 전달 수용 증거 회수

T-TRN-02의 새 env → builder → 정적 bundle 전달은 PR86 실제 빌드에서 검증했다.
제품 source2c9b416cc92f18cd6f4c47c1852344c7049ad67c, ARM64 admin 이미지
14e8c212173a7b06cfd4f8a0acd528d26d2afa11c39def3b1182e2dc555ad3ee다.
공식 Dockerfile로276.240732초에 exit0, 기존 canonical NEXT_PUBLIC_TRANSPORT_DAGSTER_URL
build arg와 release SHA를 전달하고 VWorld 값은 출력하지 않았다.

생성 JS30파일/3690978바이트에서 canonical origin2건, obsolete origin0건,
run 경로2건, 새 origin과 run 경로가 함께 있는 chunk2개를 확인했다.
정적 probe는 networknone/read-only이며 종료 후 소유 컨테이너0이었다.
이는 정적 검증이며 그 자체를 브라우저 UI 수용으로 확대하지 않는다.

PR89 수집 저장 개선 배포 후 별도 UI34/34 PASS의 transport-admin-web 실제 image ID가
위14e8c212와 같다. 따라서 새 주소의 번들을 검증하고 실제 설치된 세대와 연결했다.
PR90은 gateway만 변경하며 같은 관리자 이미지를 보존한다. 이 문서 작업은 재빌드하지 않는다.

원문 artifact SHA256: 0df7965512651fd2103fcf48e3445574755e7f3f9486afaefb15aa6a34d6fbf3
compiled BUILD_ID SHA256: 8fcc282fc2f6d0dbaed28d0242bb5e3e3cd1704000f5185f3124483eed3e65ea
compiled manifest SHA256: 35c32a3bc50bb69b58c211aa5b36a27d88162d5dbea7806bb40ddd5dc3867850

전체 Track2나 Opinet 실provider 수집, 5역할 메모리 한도 수용을 이 증거로 닫지 않는다.
