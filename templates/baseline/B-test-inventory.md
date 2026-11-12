# Test inventory (as-is): {{product name}}

<!-- MOADIX phase B. The existing tests, how they run, and what they cover. The suite runs in a
TEST environment (loopback or a test host), never against production. -->

## Test command

`{{npm test}}`

## Test environment

{{Where the suite runs, e.g. http://127.0.0.1:4173 with a throwaway database. Never a production URL.}}

## Suites

| Suite | Kind (unit / integration / ui) | Code |
|-------|--------------------------------|------|
| {{name}} | {{unit}} | {{tests/x.test.js:1-80}} |

## Coverage

| Acceptance criterion | Test |
|----------------------|------|
| US-001/AC-1 | {{tests/x.test.js:12, or none}} |
