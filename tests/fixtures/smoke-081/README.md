# smoke-081

An overlay on `tests/fixtures/smoke-076` and `smoke-080` (copied over them by tests/rel081 and the engine suite's rel081
group). Its contract adds `POST /notes`, a form whose field limit (32) equals the app's body limit (38 bytes with
`title=`), so every over-long title is refused with 413 Content Too Large, which the contract documents (task-tracker
MF-60). The route is in smoke-076's `src/server.js`; smoke-076's own contract does not list it.
