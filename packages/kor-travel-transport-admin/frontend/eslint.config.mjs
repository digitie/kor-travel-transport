import nextPlugin from "@next/eslint-plugin-next";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y-x";

// ESLint 10을 지원하는 플러그인만 사용한다. React Compiler 적용은 별도 결정이다.
export default [
  { ignores: [".next/**", "coverage/**", "playwright-report/**", "test-results/**", "public/maplibre/**", "next-env.d.ts"] },
  ...tseslint.configs.recommended,
  jsxA11y.configs.recommended,
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    plugins: { "@next/next": nextPlugin, "react-hooks": reactHooks },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
    settings: { next: { rootDir: "." } },
  },
];
