# 주변 유가 MCP Apps UI

같은 Transport API의 인증된 MCP 리소스로 제공하는 독립 브라우저 UI다. 기존 fuel의 팔레트를 재사용한다. 별도 서버·Node 런타임·사용자 위치 저장소는 없다.

Node26.13.1/npm12.0.1에서 `npm ci --engine-strict`, `npm run type-check`, `npm test`, `npm run build` 순서로 실행한다. 빌드는 `backend/app/fuel_widget/index.html` 한 파일을 만들고 추적하지 않는다. 운영 Dockerfile/CI가 고정 lock에서 생성한다.

`node node_modules/@playwright/test/cli.js test`는 로컬 포트12861의 엄격한 sandbox 시험 호스트를 사용한다. fixture 가격·좌표·타일은 운영 자료가 아니다. 실제 ChatGPT는 표준 MCP Apps 브리지로 초기화·도구 호출을 수행한다. UI가 없는 클라이언트에도 기존 MCP 데이터 도구는 그대로 제공한다.

인증 토큰·VWorld 키·실제 위치를 소스/빌드 인자/URL에 넣지 않는다. 자세한 계약은 [보고서](../../docs/reports/2026-11-28-fuel-mcp-app-ui.md)를 따른다.
