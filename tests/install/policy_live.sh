#!/bin/bash
# Live check of the 0.5.2 policy (local overlay hosts; the GitHub CLI outside the sandbox), AFTER managed/install.sh.
# Run it with Claude Code's Bash tool in a fresh session (so it runs inside the sandbox), not in Terminal:
#     bash tests/install/policy_live.sh
# The hosts come from your local overlay (~/.config/moadix/overlay.json, or $MOADIX_OVERLAY); nothing
# product-specific is in this repository. The guard checks (git push main, PR merges, ...) are separate
# Bash-tool calls: see the "Main-branch guard" section of docs/INSTALL.md.
set -u
fails=0
ok()  { printf 'PASS  %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }

# Any HTTP status (even 401/403/404) means the request left the sandbox and got an answer from
# the real host. 000 means the connection never happened (sandbox proxy denial, DNS, timeout).
reach() {
  local code
  code="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "https://$1/" 2>/dev/null)"
  if [[ "$code" != "000" && -n "$code" ]]; then ok "$1 reachable from the sandbox (HTTP $code)"
  else bad "$1 NOT reachable from the sandbox (HTTP ${code:-none})"; fi
}
overlay="${MOADIX_OVERLAY:-$HOME/.config/moadix/overlay.json}"
if [[ -f "$overlay" ]]; then
  hosts="$(/usr/bin/python3 -c 'import json,sys; print("\n".join(h.replace("*.", "", 1) for h in json.load(open(sys.argv[1])).get("extra_network_hosts") or []))' "$overlay")"
  if [[ -z "$hosts" ]]; then echo "SKIP  the overlay lists no extra hosts"; fi
  while IFS= read -r h; do [[ -n "$h" ]] && reach "$h"; done <<<"$hosts"
else
  echo "SKIP  no local overlay at $overlay: no extra hosts to check"
fi

# Negative control: a host NOT on the allowlist must still be refused.
code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' https://example.com/ 2>/dev/null)"
if [[ "$code" == "000" ]]; then ok "negative control: example.com is still refused by the sandbox"
else bad "negative control: example.com answered HTTP $code, so the allowlist is not in effect"; fi

echo
echo "$fails failed"
echo "Now run the GitHub CLI checks in docs/INSTALL.md as separate Bash calls (typed directly)."
exit $((fails > 0))
