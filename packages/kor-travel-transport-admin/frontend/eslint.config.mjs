import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTypeScript,
  {
    // React Compiler 도입은 별도 작업이며 기존 Hooks 규칙은 유지한다.
    files: ["components/address-refresh.tsx", "components/rail-station-mapping.tsx"],
    rules: { "react-hooks/set-state-in-effect": "off" },
  },
  {
    ignores: ["coverage/**", "playwright-report/**", "test-results/**", "public/maplibre/**"],
  },
];

export default config;
