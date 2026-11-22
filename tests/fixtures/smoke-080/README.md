# smoke-080

An overlay on `tests/fixtures/smoke-076` (copied over it by tests/rel080 and the engine suite's rel080 group): the
app's compose stack gains a database built FROM the official PostgreSQL image, and the app waits for it before it
listens (task-tracker MF-57). The worker service of smoke-076 is not in this compose file.
