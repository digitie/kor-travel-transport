# ADR-014: transport 스택을 odroid(192.168.1.13)에서 운영하고 배포 스크립트는 `--host <addr>`를 효과로 검사한다

- **상태**: accepted (→ 진행: `docs/tasks.md` T-046)
- **날짜**: 2026-10-13
- **결정자**: agent + human (교차 저장소 Track 2 설계 "geo·weather·transport를 odroid로 옮긴다" 2026-10-13 최종본;
  소유자 지시 "설계와 각 프로젝트 문서 수정해서 코딩을 할 수 있게 준비")
- **관계**: Manager **ADR-58**(`hosts:` registry·호스트 프로필 Manager·호스트당 Dagster plane/PG·target별 host 플립)이
  상위 결정이고 이 ADR은 그 transport 몫이다. geo ADR-070·weather·Map ADR-110·concierge ADR-50이 같은 설계의 다른 몫이다.
  transport는 geo를 호출하지 않으므로 Track 1(geo 주소 데이터셋 릴리스 대응, T-045)과는 무관하다.
- **원 본문**: 2026-10-13 사실 표(**B1~B11** — 단일 호스트 결박 자리와 `file:line`), odroid 실측 상태, 결정별 명령·체크리스트,
  2026-10-19·10-23 운영 정합 기록은 → 세부: [Odroid 이전 설계 원문](../audits/2026-10-13-odroid-transition-design.md).
  현재 배포 절차는 [배포 런북](../runbooks/deployment.md)("현재 Odroid 정본"·"T-TRN-01 source 배포 계약" 절)과
  [Manager 대조](../audits/2026-10-19-manager-contract-alignment.md)가 정본이다.

### 2026-10-23 운영 방침 갱신

공용 Dagster daemon은 RUNNING을 유지하고, transport 배포의 일시 중지는 이 location의 instigator에만 걸었다가 되돌린다.
→ 세부: [배포 런북 "T-TRN-01 source 배포 계약"](../runbooks/deployment.md#t-trn-01-source-배포-계약2026-10-17)

### 2026-10-19 당시 운영 정합

현재 Odroid 운영·소비자 GET·UI 수용을 근거로 accepted로 정산했다(모든 후속 task 완료를 뜻하지 않는다).
→ 세부: [설계 원문](../audits/2026-10-13-odroid-transition-design.md), [Manager 대조](../audits/2026-10-19-manager-contract-alignment.md)

### 컨텍스트

소유자 목표는 geo·weather·transport와 그 PostgreSQL을 odroid(ODROID M1S, aarch64 A55 ×4, RAM 약 7.5 GiB, NVMe)에서 돌리고,
n150의 Map/PinVi/concierge와 OPNsense HAProxy는 **REST로만** 호출하게 하는 것이다. 포트·URL·컨테이너명·compose project·
디렉터리 규칙은 n150과 같고 호스트만 바뀐다. 데이터 보존·롤백은 비범위(소스에서 재적재)다.
이 저장소는 배포 스크립트가 n150 주소를 리터럴로 대조·거부하고, env 파일명·export allow-list·운영 UI Dagster 링크·
compose 메모리 한도 부재 등 여러 자리에서 단일 호스트에 결박돼 있었다(B1~B11). odroid는 Plex·Samba 등이 상주하는 가정용
미디어 호스트이고 메모리가 n150의 절반이며, 주소는 DHCP 예약(OPNsense)을 전제한다.

### 결정

1. **배포 스크립트는 `--host <addr>`(필수, 기본값 없음)를 받고 리터럴이 아니라 효과로 검사한다.** ① 원격 IPv4 집합이
   `<addr>`을 포함하고 ② Manager가 설치돼 있고 ③ Manager registry가 계산한 `targets.transport.host`(hosts 키)의
   `hosts.<키>.addr`가 `<addr>`과 같아야 한다. 하나라도 어긋나면 복사·Docker 변경 전에 멈춘다. 이 저장소는 host 목록 파일이나
   키→주소 표를 두지 않는다(주소의 정본은 Manager registry 한 곳). 운영 UI 배포 스크립트도 같은 키로 같은 검사를 한다(별도
   target을 만들지 않는다). env 파일은 `.env.server14` → `.env.prod`로 바꾸고, **원격 단계의 실행 사용자와 `.env.prod` 소유는
   n150과 같은 `digitie:digitie 0600`**이다(설계의 root 0600은 배포 기제와 양립하지 않아 채택하지 않음 — 후속 "열린 결정 A").
   → 세부: [배포 런북 "T-TRN-01 source 배포 계약"](../runbooks/deployment.md#t-trn-01-source-배포-계약2026-10-17)
2. **loopback URL은 불변, 그 URL에 붙는 자격증명만 호스트별이다.** PG·RustFS·Dagster plane이 호스트마다 로컬에 있으므로
   DSN·내부 URL·`require` 검사는 odroid에서도 같은 문자열이다. 호스트마다 다른 비밀(공용 Dagster PG 앱 비밀번호, RustFS 키)은
   그 호스트의 Manager에서 가져온다.
3. **`DAGSTER_POSTGRES_URL`은 env로만 남기고 DB는 만들지 않는다.** backend는 읽지 않고 compose 보간·원격 검사만 만족시키는
   모양의 값이다. legacy-dagster profile은 odroid에서 띄우지 않는다.
4. **호스트에 묶인 env는 규칙으로 파생한다.** TrustedHost·CORS의 LAN 항목 = 배포 host 주소. export allow-list
   (`SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`) = loopback + Map이 있는 n150 — [ADR-013](013-internal-service-exports-for-map.md)의
   토큰 + peer 주소 이중 잠금은 호출자가 LAN peer가 돼도 그대로 성립한다.
5. **운영 UI Dagster 링크는 기존 변수 `NEXT_PUBLIC_TRANSPORT_DAGSTER_URL`을 build arg로 넘긴다**(설계의
   `TRANSPORT_DAGSTER_PUBLIC_ORIGIN` 부활 대신; build 시점 값이라 plane host가 바뀌면 재build).
6. **legacy odroid 자산은 두 단계로 걷어낸다.** (a) "13번에서 Docker 금지" 계열 문구를 먼저 "odroid 작업은 배포 런북·ADR-014를
   따른다"로 바꾸고, (b) odroid 배포 게이트가 초록인 뒤 legacy 자산 집합 **M**(fail-closed 마커 포함, 원문 참조)을 삭제한다.
   odroid의 legacy `parking-radar` 스택·`pr2`는 폐기 대상, Plex·Samba 등 다른 상주 서비스는 공존 대상이다.
7. **이미지는 arm64 odroid 현지 빌드다**(레지스트리 없음). Playwright Chromium이 arm64에서 실패하면 fallback은
   `OPINET_BROWSER_ENABLED=false`(유가만 끔)이고, provider 전체를 끄는 `TRANSPORT_COLLECTION_ENABLED=false`는 쓰지 않는다.
8. **전환은 n150 수집을 먼저 멈춘다(이중 수집 금지).** 같은 원천 키로 두 호스트가 수집하면 일일 한도를 2배 쓴다. 공개 HAProxy
   경로는 odroid health·첫 스냅샷 뒤 선전환해 공개 outage를 피한다(Manager 일반 순서와의 차이는 원문·Manager 대조 참조).
   데이터는 fresh 재적재하고 n150 이력은 보존하지 않는다.
9. **백업은 odroid Manager standalone backup이 맡는다**(n150 cron에서 이동). 이전 자체에는 백업·복원이 없다.
10. **공용 Dagster plane 합류는 배포보다 먼저다.** 원격 단계의 "공용 webserver workspace에 location이 없으면 거부" 가드는
    파일 검사로 낮추지 않고 유지하며, 대신 plane/workspace 반영을 배포 앞에 둔다. 전제 두 가지(① 배포 전 location이 `absent`가
    아님 ② code-server healthy 뒤 location이 다시 실림)는 첫 odroid 배포에서 실측한다. 현재 명령은 Manager의
    `dagster-plane converge`다([Manager 대조](../audits/2026-10-19-manager-contract-alignment.md)).
11. **메모리·swap 한도는 이 저장소 compose의 리터럴로 둔다**(두 호스트 동일, `memswap_limit == mem_limit`). 한도는 compose를 가진
    이 저장소만 걸 수 있고, Manager의 등록은 측정일 뿐이다. 값은 설계 예산에서 출발해 실측으로 조정한다(T-TRN-05).

### 근거

- **리터럴 대신 효과 검사(결정 1)**: 호스트가 둘이 되면 `.14` 리터럴은 Manager registry와 두 번째 정본이 된다. registry에서 계산된
  키·주소와 "원격 IPv4 ∋ addr"을 대조하면 스크립트가 주소 목록 없이 잘못된 호스트 배포를 막는다. host 목록 파일은 정본을 둘로
  만들어 기각했고, `--host`를 키로 받는 대안은 같은 출력을 요구해 인자 모양만 다르다.
- **`.env.prod` digitie 소유(결정 1)**: 원격 `source`·`awk`·`--env-file`·토큰 스크립트가 모두 digitie로 돈다. root 0600은 세 스크립트를
  `sudo -n`으로 올리는 코드 변경을 부르고 n150과 운영 모양이 갈린다.
- **loopback 불변(결정 2)**이 핵심 단순화다 — compose·DSN·검사가 호스트 이전에서 바뀌지 않는다. n150 PG를 LAN으로 여는 대안은
  pg_hba 개방·gRPC 무인증 LAN 노출을 요구해 기각했다.
- **값만 남긴 env(결정 3)**: 보간·검사를 걷어내는 것은 legacy-dagster profile(되돌리기 수단)을 함께 없애는 별개 결정이다.
- **allow-list에 n150만 추가(결정 4)**: odroid 호스트 방화벽이 적용되기 전에는 토큰 + peer 이중 잠금이 경계다.
- **기존 변수 재사용(결정 5)**: 코드가 이미 읽는 변수에 build arg 한 줄을 더하는 쪽이 새 이름을 되살리는 것보다 작다.
- **Opinet만 비활성(결정 7)**: Chromium은 유가 수집 한 경로에만 쓰이므로 arm64 실패가 고속도로 소통·돌발·Map export까지 막을
  이유가 없다.
- **가드를 바꾸지 않고 순서를 바꾼다(결정 10)**: 가드는 code-server만 공용 instance로 가고 옛 daemon이 schedule을 쏘는 이중 발화를
  막는 효과 검사다. 순서 변경은 코드 변경이 0이다.
- **메모리 한도는 compose 소유자가(결정 11)**: transport code-server·backend는 Manager compose 밖에 있다. 한도가 없으면 설계의 최악
  창 메모리 산식이 성립하지 않고, Chromium 피크 때 호스트 OOM이 PG를 고를 수 있다.

### 결과 (긍정)

- compose·DSN·probe·plane 버전 검사·plane 합류 가드가 호스트 이전에서 불변이다. 바뀌는 것은 배포 스크립트의 host 검사, `.env`
  값(LAN 주소·allow-list·Dagster 링크·호스트별 비밀), compose 메모리 한도뿐이다.
- odroid의 legacy 스택과 fail-closed 마커가 사라져 "같은 서비스가 두 호스트에" 상태가 끝난다.
- n150에서 transport의 PG·CPU·메모리 부하가 빠진다.

### 결과 (부정)

- 전환 중 수집 공백(이중 수집 금지의 대가)과 고속도로 이력 포기 — 통계 화면이 전환 직후 빈다.
- Map의 transport 호출이 loopback 대신 LAN timeout을 본다. odroid 시계(NTP 영속화)가 깨지면 Map의 돌발 시계 검사가 응답을 거부한다.
- A55에서 Opinet Chromium·KRIC XLSX 적재가 n150보다 느리다.
- 운영 UI Dagster 링크는 build 시점 값이라 plane host가 바뀌면 재build가 필요하다.
- `DAGSTER_POSTGRES_URL`이 "존재하지 않는 DB"를 가리키는 변수로 남는다.
- odroid `.env.prod`(digitie 0600)는 Samba `[homes]`로 digitie SMB 자격을 가진 LAN 클라이언트에게 읽힌다(열린 결정 A).
- DHCP 임대가 바뀌면 스택은 돌지만 Map export·HAProxy·TrustedHost만 조용히 실패한다 — OPNsense 예약이 전제인 이유다.
- 메모리 한도에 닿으면 run FAILURE다(swap 없음). OOM이 보이면 한도보다 Opinet 배치 크기를 먼저 본다.

### 후속

- **교차 저장소 계약**: Manager `targets validate --json`은 `targets.<id>.host`(resolve된 hosts 키 — `host:`를 생략한 target 포함)와
  `hosts.<키>.addr`를 함께 실어야 한다. 비거나 없으면 Manager 쪽 결함으로 보고 거부한다.
- **열린 결정**(소유자, Manager ADR-58 "열린 결정" 번호): legacy 폐기 범위, odroid plane 공개 host 이름(결정 5의 값), 백업 대상,
  odroid IP 고정(DHCP 예약), 방화벽 정책 등. **열린 결정 A**: `.env.prod` = `digitie:digitie 0600`(설계 root 0600 대신) — 기각되면
  원격·운영 UI·토큰 스크립트를 `sudo -n`으로 올리는 범위가 더해진다.
- **설계에서 이탈한 것**(소유자 확인 대상): Dagster 링크 변수(결정 5), `.env.prod` 소유(결정 1), plane 합류 순서(결정 10), HAProxy
  선전환(결정 8), 메모리 한도를 이 저장소 compose에(결정 11), 수용 검사를 bats 대신 pytest 계약 테스트로.
- 구현 단위(T-TRN-01~05)와 남은 작업은 `docs/tasks.md` T-046이 관리한다. 항목별 원래 수용 조건은
  [설계 원문](../audits/2026-10-13-odroid-transition-design.md)의 "후속" 절에 있다.
