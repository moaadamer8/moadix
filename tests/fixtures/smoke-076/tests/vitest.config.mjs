// Imports vitest, as task-tracker's tests/vitest.unit.config.ts does: Stryker's sandbox must resolve it
// (task-tracker MF-53).
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["tests/**/*.test.js"], pool: "forks" },
});
