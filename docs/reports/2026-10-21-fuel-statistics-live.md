# 2026-10-21 유가 통계 운영 검증

## 배포와 수용 범위

- 기능 PR [#101](https://github.com/digitie/kor-travel-transport/pull/101), main/runtime `86398267fc32c8558f8fa2f2ae40310fd46e5c00`.
- Odroid `192.168.1.13`에 공식 backend·admin 배포 도구로 적용했다. Alembic0028, backend/API health의 release SHA, 관리자 배포 receipt를 확인했다.
- 앱·빌드·환경 파일·DockerRoot가 모두 NVMe임을 확인했다. HAProxy와 다른 프로젝트 컨테이너는 변경하지 않았다.
- tracked override와 `/opt/kor-travel-odroid/transport/transport.override.yml`이 일치하고 gRPC12306이 열려 있다. Transport backend·code-server·admin·gateway는 healthy다.
- location `kor-travel-transport`는 `RepositoryLocation`, schedule12개·sensor5개 모두 RUNNING이다. 공용 daemon은 기동 상태를 유지했다. 별도 공용 plane 교체 중 조회가 잠시 끊겼을 때 공식 배포는 작업 종료 확인을 재시도한 뒤 교체했다.

## 테스트와 독립 리뷰

- 최종 리뷰 커밋 `2c2474d`: WSL/Docker backend 각각940 PASS·14 조건부 SKIP, admin 각각225 PASS, production build PASS.
- PostgreSQL 집중4 PASS, SQLite 집중4 PASS, 마이그레이션 downgrade0027→upgrade0028→check PASS.
- 격리 Playwright5 PASS + 실제 로컬 PG/API/BFF/로그인1 PASS. 실패 후 재시도, 늦은 범주 응답, 키보드 포커스, 날짜 공백, 모바일/PC를 포함한다.
- James/Popper 초기 지적4건을 재현·수정했고 독립 재리뷰에서 추가 P0/P1/P2가 없었다. [리뷰 기록](../reviews/2026-10-21-fuel-statistics.md).
- 최종 push/PR CI6개 SUCCESS. 자동 live-e2e2개는 명시적 실행 대상이라 SKIP이며 실제 브라우저 실행과 구분한다.
- 운영 HTTPS Playwright1 PASS(실제 테스트30.2초, 전체35.4초). 미인증401·실제 로그인·6개 범주 API·390/1440px·가로 넘침 없음·실제 VWorld 지도 확대2회·키보드 이동·변경 bbox 응답을 검증했다. API 응답/지도 SDK를 대체하지 않았다. 세 화면 캡처를 육안 확인했다.

운영 브라우저 명령은 admin frontend에서 다음과 같다. 비밀번호는 환경변수로 전달한다.

```bash
E2E_FUEL_STATISTICS_LIVE=true E2E_FUEL_MAP_CAMERA=true \
E2E_BASE_URL=https://transport.digitie.mywire.org \
npx playwright test e2e/fuel-statistics-live.spec.ts --workers=1
```

## 원본 대조와 초기화

`scripts/rebuild-fuel-statistics.py`로 공급자를 재호출하지 않고 최신 가격을 초기화했다. OPINET 발행 기준은00:49:20.470379 UTC, EX는03:32:56.122586 UTC다. 두 원천 모두 `update_pending=false`다. 현재 세대와 원본이 일치하는지 확인한 뒤 결과를 대조했다.

| 원천/유종 | 유효 가격 수 | 평균(원/L) | 원본 대조 |
| --- | ---: | ---: | --- |
| OPINET 휘발유 | 10,200 | 1,855.98 | 개수·평균·최저·최고 일치 |
| OPINET 고급유 | 2,058 | 2,397.34 | 동일 |
| OPINET 등유 | 5,626 | 1,571.65 | 동일 |
| OPINET 경유 | 10,238 | 1,842.07 | 동일 |
| OPINET LPG | 1,842 | 1,143.83 | 동일 |
| EX 휘발유 | 212 | 1,830.60 | 개수·평균 일치 |
| EX 경유 | 212 | 1,834.75 | 동일 |
| EX LPG | 157 | 1,218.10 | 동일 |

전국 지도에는 좌표가 있는11,836곳, 수도권 검사 bbox에는1,791곳이 있었다. 후자의 마커 limit을1로 제한해도 휘발유 통계는1,510곳을 포함해 마커 제한과의 독립성을 확인했다. 시군구 비교230개, 고속도로 노선29개, 노선/방향57개가 반환됐다. 이 숫자는 저장된 원천의 현재 범위이며 국내 모든 주유소의 무누락 보장을 뜻하지 않는다.

설치 전7일을 재구성하지 않았다. 오늘 포함7일 보관은 최초 발행일부터 누적하며 없는 날짜는 보간하지 않는다. EX `B00067`의184원 원본 이상값과 영향은 [분석 기준](../fuel-statistics.md#원본-가격의-품질)에 명시했다.

## 운영 응답 시간

내부 loopback API는 범주별5회, 지도별7회를 측정했다. 최종 측정 때 운영 수집과 다른 테넌트 작업은 계속 실행 중이었다. 격리 성능 보장이나 백분위 목표 수용으로 해석하지 않는다.

| 내부 통계 범주 | 중앙값(ms) | 최대(ms) |
| --- | ---: | ---: |
| 전국 | 121 | 141 |
| 시도 | 202 | 248 |
| 시군구230개 | 623 | 2,046 |
| 고속도로 전체 | 214 | 382 |
| 고속도로별 | 203 | 242 |
| 고속도로/방향별 | 759 | 1,764 |

| 지도 bbox | 첫 조회(ms) | 후속6회 중앙값(ms) | 후속 최대(ms) |
| --- | ---: | ---: | ---: |
| 전국/zoom7 | 910 | 816 | 1,071 |
| 수도권/zoom15/limit1 | 667 | 392 | 1,156 |

공개 HTTPS 별도3회 중앙값은 전국 지도1,744ms, 수도권 지도1,168ms, 시군구 통계1,172ms였다. 내부 측정과 일부 시간이 겹쳤으므로 단일 요청의 최소 비용으로 주장하지 않는다. 배포 전 공개 지도 기준값334/219ms는 통계가 없고 부하 시점도 달라 증가율/회귀 판정의 근거로 쓰지 않는다. 저장 API1초 목표의 공개 경로·고부하 상한은 기존 성능 백로그에서 계속 추적한다.

관리 UI 빌드가 진행되던 첫 측정은 시군구 중앙값1,690ms·전국 지도 최초11,081ms까지 지연됐다. 호스트 load average는10~16이었다. 이후 실행 계획의 시군구 SQL74ms·전국 지도 SQL1,400ms, JIT 없음·shared buffer hit를 확인했다. 첫11초의 단일 원인을 확정하지 않았다.

새 테이블은 autovacuum 통계 갱신을 확인했다(points05:38:18 UTC, daily05:36:34 UTC). 수동 ANALYZE는 states만 완료됐고 points는 앱 연결120초/별도 세션30초 상한에서 취소됐다. 후자는 관측 시 lock 대기 없이 active였다. 추가 반복이나 전역 timeout/JIT/통계 설정 변경은 하지 않았다.

개발 PC의 합성12,000곳/60,000가격 실측은 발행2.74초, 지도 무캐시 중앙값65ms·캐시1.54ms, 시군구6.3ms, Python 추적 최대3.13MiB였다. Python 추적값은 프로세스 RSS·DB 메모리가 아니다. Odroid 초기화 중 backend 컨테이너153.2MiB/CLI RSS 약66MiB의 단회 관측도 최대값이나 전후 절감률로 주장하지 않는다.
