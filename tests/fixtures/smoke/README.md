# Smoke fixture

A tiny product that every executing gate can run against: `tests/confined-engine/run.py` (group `smoke`)
copies it into a throwaway git repository and runs each gate once through `check_exec.run_gate`, with
the real pinned tools and the real runner settings. `package-lock.json` pins the product's own tools
(ESLint, TypeScript, Stryker); regenerate it with `npm install --package-lock-only` if they change.
