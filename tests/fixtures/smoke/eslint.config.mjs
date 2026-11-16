import js from "@eslint/js";

export default [
  js.configs.recommended,
  {
    files: ["src/**/*.js", "tests/**/*.js"],
    languageOptions: { sourceType: "commonjs", globals: { require: "readonly", module: "writable" } },
  },
];
