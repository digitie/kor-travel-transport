import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // vworld-map-web(vendor tarball)은 ESM dist에서 maplibre-gl과 그 CSS를 import한다. inline해야
  // 컴포넌트 테스트의 maplibre-gl 대역이 라이브러리 안까지 닿는다.
  test: { environment: "node", exclude: ["e2e/**", "node_modules/**"], server: { deps: { inline: ["vworld-map-web"] } } },
  resolve: { alias: { "@": path.resolve(__dirname, ".") } },
});
