# ADR-017 — 웹 production runner의 non-root와 역할별 예외

- 상태: 소스 결정 수용, 실제 새 이미지 QA 미완
- 날짜: 2026-11-13
- 범위: Transport 공개·관리자 Next 웹 runner. backend/CS/gateway의 UID 변경은 제외

## 배경

공통 CI-33은 production 멀티스테이지와 최종 non-root를 규정한다.
기존 공개 Dockerfile은 builder 자체로 실행했고 관리자 runner에도 USER가 없었다.
공개·관리자의 Compose/start 계약과 런타임 파일 접근을 보존하면서 이 차이를 해소한다.

## 결정

두 웹 이미지는 dependencies/builder와 구분된 production runner에서 USER node(1000:1000)로 실행한다.
기존 Node22.23.1 Alpine digest/npm12.0.1과 npm start, 공개 shared Compose의 직접 next start 명령을 유지한다.
호스트 chmod·root ENV·volume·공유 DB·다른 역할은 변경하지 않는다.

| 경로 | 내용과 권한 |
|---|---|
| /app/package.json·lock·.npmrc | 기존 start/설치 메타데이터. root 소유, node 읽기 |
| /app/node_modules | 기존 lock의 전체 설치 산출물. root 소유, node 읽기/필요 파일 실행 |
| /app/.next | 빌드 산출물. node 소유; 서버의 cache/재검증 쓰기 계약 보존 |
| /app/public | node 읽기. 공개는 tracked public이 없어 builder가 빈 디렉터리를 명시 생성; 관리자는 기존 worker·정적 자산 복사 |
| /app/next.config.ts·tsconfig.json | node 읽기. 실제 Next loader로 검증 |
| /app/proxy.ts | 관리자 기존 파일을 그대로 복사. 실제 인증/proxy 동작은 HTTP/browser QA로 별도 확인 |
| /home/node/.npm·.cache | 이미지 안에서만 생성·node 소유. HOME/npm/XDG cache 위치를 명시 |

standalone은 이번 필수 조건이 아니다. 현재 Next config는 TypeScript이며 설치된 Next loader는
tsconfig와 SWC/native binding을 읽는 경로가 있다. Compose는 공개의 직접 next binary와
관리자의 npm start를 사용한다. 관리자 parking-ui는 install-links=true로 설치된 package를
transpile하며 기존 worker는 prebuild가 생성한 두 public 파일을 함께 요구한다.
이를 별도 tracing 검증 없이 server.js/의존성 prune으로 바꾸지 않는다.
전체 node_modules 보존은 이 런타임 호환 결정이며 크기 절감 완료라는 주장은 하지 않는다.
원본 UI·config 내용·인증 정책·공통 C11 bytes·공유 frontend root context는 유지한다.

## backend/CS/gateway의 역할별 처리

backend/CS는 같은 Python 이미지를 사용한다. 현재 entrypoint·이미지 내 bootstrap과 collector-state/
backup·root 소유 bind config 읽기 계약이 별도로 있다. migrate는 이 이미지의 one-shot 역할이다.
이들의 USER를 웹과 함께 바꾸거나 host 권한을 넓히지 않는다.
비활성 LEGACY Dagster nginx gateway Dockerfile은 시작 때 /etc/nginx/.htpasswd를 작성하고 master를 실행한다.
현재 관리자 API gateway는 별도 외부 nginx pinned ID + 추적 template/공식 SDK508 paired-role 선택이다.
비활성 소유 Dagster gateway를 현재 API gateway coverage로 세지 않는다.

이 역할들은 이번 웹 CI-33 반영으로 non-root가 되었다고 표시하지 않는다.
현재 root 역할을 유지하는 명시적 범위 예외이며 향후 해당 역할의 최소 권한·bootstrap/state/backup/
config·nginx 포트/파일 계약을 검증한 변경이 필요하다. 다른 역할 또는 공용 daemon 전체 변경 권한을 뜻하지 않는다.
정상 build-only wrapper는 migration/downgrade/운영 lifecycle을 실행하지 않는다.

## 검증과 적용 조건

소스 검사는 final runner 선택과 실제 image Config.User=node를 요구한다.
이미지에 포함한 verify-web-runtime.cjs는 해당 이미지의 기본 USER로 실행해야 하며
관측 uid/gid·Node/npm·baked release·config/manifest/entry 파일·parking package·worker 원본 hash·
cache의 실제 쓰기/삭제를 검사한다. 실제 Next production loader도 실행한다.
원문 config/ENV/key나 compiled JS는 출력하지 않는다. probe의 PASS는 파일/config/cache 범위다.

별도 새 amd64/arm64 이미지에서 정상 start·기존 Compose command·HTTP health·공개 proxy·
관리자 로그인fixture/보호 경로·logout·SSR·worker 실행/browser를 검증해야 한다.
권한을 가짜로 넘기거나 --user root로 실행한 결과는 non-root 수용으로 쓰지 않는다.
기존 native QA/2db의100PASS는 새 Docker 이미지 수용으로 소급하지 않는다.
Common 실제 guard ref·원2리뷰·exact CI·머지 source의 새 이미지·공식 SDK 수용 전에는 적용하지 않는다.
