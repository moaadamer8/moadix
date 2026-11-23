"""0.8.1 (task-tracker MF-60): the statuses a product's contract may document as a refusal of a schema-violating request,
for Schemathesis's ST201 (negative_data_rejection).

ST201 counts a negative request as refused only with 400, 401, 403, 404, 405, 406, 409, 415, 422, 428, 429 or a 5xx. An
app whose body limit refuses an oversized request with 413 Content Too Large (RFC 9110), as its contract documents, so
failed ST201 for every operation with a field limit equal to its body limit. The operator may list such statuses in
.sdlc/config/product-tools.yaml, adopted with ADOPT:

    schemathesis:
      refusal-statuses: [413]

The gate then accepts a listed status as ST201's refusal only for an operation whose OpenAPI responses document that
status (gate/exec/st_config.py writes Schemathesis's per-operation configuration inside the run); every other operation
keeps Schemathesis's own list. Only a 4xx that is not already in that list, at most MAX of them.
"""
DEFAULT = (400, 401, 403, 404, 405, 406, 409, 415, 422, 428, 429)
MAX = 4
KEY = "refusal-statuses"


def from_tools(doc):
    """([status, ...], problems) from a product-tools.yaml mapping; ([], []) when it sets none."""
    s = (doc or {}).get("schemathesis")
    if s is None:
        return [], []
    if not isinstance(s, dict) or any(k != KEY for k in s):
        return [], ["product-tools.yaml schemathesis: may only hold %s (the statuses an operation's contract documents "
                    "as a refusal)" % KEY]
    raw = s.get(KEY)
    if not isinstance(raw, list) or not raw:
        return [], ["schemathesis.%s must be a non-empty list of HTTP statuses" % KEY]
    out, probs = [], []
    for v in raw:
        code = v if isinstance(v, int) and not isinstance(v, bool) else (int(v) if isinstance(v, str) and v.isdigit()
                                                                         else None)
        if code is None or not 400 <= code <= 499:
            probs.append("schemathesis.%s: %r is not a 4xx status (a refusal is a client error)" % (KEY, v))
        elif code in DEFAULT:
            probs.append("schemathesis.%s: %d is already a refusal for Schemathesis" % (KEY, code))
        elif code in out:
            probs.append("schemathesis.%s repeats %d" % (KEY, code))
        else:
            out.append(code)
    if len(raw) > MAX:
        probs.append("schemathesis.%s lists %d statuses; at most %d" % (KEY, len(raw), MAX))
    return ([] if probs else out), probs
