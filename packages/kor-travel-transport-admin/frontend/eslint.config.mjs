import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTypeScript,
  {
    ignores: ["coverage/**", "playwright-report/**", "test-results/**", "public/maplibre/**"],
  },
];

export default config;
