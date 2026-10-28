# 주유소 상표 이미지

지도·목록·상세에서 주유소의 실제 상표를 식별하기 위한 원본 이미지다. 직접 그린 로고가
아니며, 색상·종횡비·로고 구성을 변경하지 않는다. 흰 바탕의 작은 상표 이미지를 `contain`으로
표시하고 원본 밖에 선택 테두리를 둔다. 상표권과 이미지 저작권은 각 권리자에게 있다.
이미지가 없거나 읽기에 실패하면 일반 주유기 아이콘과 제공된 상표 이름을 표시한다.

2026-10-28 [한국석유공사 오피넷의 주유소 홍보 상표 선택](https://www.opinet.co.kr/user/publicity.do)에서
상표 코드·이름·이미지 연결을 대조하고 아래 파일을 그대로 보관했다. 원본 주소의 공통 앞부분은
`https://www.opinet.co.kr/images/user/com/`이다.

| 코드 | 상표 | 원본 파일 |
| --- | --- | --- |
| SKE | SK에너지 | icon_sk.gif |
| GSC | GS칼텍스 | icon_gs.gif |
| HDO | HD현대오일뱅크 | icon_hy.gif |
| SOL | S-OIL | icon_soil.gif |
| SKG | SK가스 | icon_sk_gas.gif |
| E1G | E1 | icon_e1.gif |
| NCO | 남해화학클린오일 | icon_nc.gif |
| NHO | 농협알뜰 (NH-OIL) | icon_nho_new2.gif |
| RTO / RTE | 알뜰주유소 / 자영알뜰 | icon_rto_new2.gif |
| RTX | 고속도로알뜰 (EX-OIL) | icon_rtx_new2.gif |

추가로 [오피넷의 지역별 주유소 지도](https://www.opinet.co.kr/searRgOsSelect.do)의 실제 필터
코드·이미지 연결을 대조해 RTO는 `icon_rto_new2.gif`, RTX는 `icon_rtx_new2.gif`, NHO는
`icon_nho_new2.gif`를 보관하고 사용한다. NHO는 이 지도용 원본이 우선한다.
[공식 API 상표 코드 설명](https://www.opinet.co.kr/user/custapi/openApiInfoDtl.do?apiId=2)과
형제 `python-opinet-api`의 `opinet/codes.py`, `opinet-api.md`도 교차 확인했다.
RTE는 자영알뜰로 알뜰주유소 로고를 사용하고, RTX는 고속도로알뜰의 EX-OIL 로고를 사용한다.
ETC가 자가상표이며, 공통된 정유사 로고가 없으므로 일반 주유기 아이콘으로 표시한다.
상표 코드는 이름보다 우선하고, 미확인 코드를 다른 정유사의 이미지로 대체하지 않는다.

공식 CI 확인 자료:

- [SK에너지 CI](https://www.skenergy.com/company/ci?curTab=init): 로고 조합·색상·보호 공간 규정.
- [GS칼텍스 CI](https://www.gscaltex.com/kr/Company/Brand/CI): 공식 로고와 시그니처.
- [S-OIL CI](https://www.s-oil.com/company/CI.aspx): 공식 워드마크·색상·다운로드 자료.

오피넷의 저작권정책은 포괄적인 자유 재배포 허가가 아니다. 원저작권을 프로젝트의
오픈소스 라이선스로 재허가하지 않으며, 이 파일들은 상표 식별 목적으로만 사용한다.
출처 표시가 일반적인 재배포 허가를 대신한다는 의미도 아니다. 원본의 색상 변경·부분 삭제·
홍보용 재사용을 하지 않는다.
