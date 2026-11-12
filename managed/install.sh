#!/bin/bash
# MOADIX machine setup and update (macOS). Run by the operator in a real
# terminal, NOT from inside Claude Code. See docs/INSTALL.md.
#
#   managed/install.sh [--plugin <github-owner/repo>]
#       Fresh install, or an update if MOADIX is already installed.
#       Asks for your macOS password (sudo) once.
#
#   managed/install.sh --dry-run <stand-in-dir> <test-keychain> [--plugin ...]
#       Test mode, no sudo: <stand-in-dir> plays /Library/Application Support/ClaudeCode,
#       <test-keychain> plays your login keychain, and the checker is a test build
#       pinned to both. Used by tests/install/dryrun.py.
#
# Fresh install
#   1. Preconditions: Claude Code >= 2.1.295; no MDM profile for Claude Code
#      and no other managed-settings file (Claude Code uses only the
#      highest-ranked managed source, so either would replace MOADIX's).
#   2. Build the checker and sign it (ad hoc, hardened runtime).
#   3. Install the checker and the gate, root-owned, to <cc-dir>/moadix.
#   4. As you (not root): create the Keychain secrets, show the QR code once.
#   5. Install managed-settings.json (root-owned): hooks, sandbox, deny lists, pin.
#   6. Check it is in effect: the installed gate denies a .sdlc/ write and
#      reads a clean STATUS; then (real mode) a sandboxed Claude Code command
#      must fail to write .sdlc/.
# Update (MOADIX already installed): steps 1-3, 5 and 6, keeping the Keychain
# secrets and the pin. Refused if the checker binary itself changed, because
# the Keychain only lets the exact checker build that created the secrets read
# them; that case needs uninstall + install (a new QR code).
set -euo pipefail

REAL_CC_DIR="/Library/Application Support/ClaudeCode"   # the ONLY place the real path is set
MIN_VERSION="2.1.295"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

MODE=real; CC_DIR="$REAL_CC_DIR"; TEST_KC=""; PLUGIN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) MODE=dry; CC_DIR="${2:?stand-in dir}"; TEST_KC="${3:?test keychain}"; shift 3 ;;
    --plugin)  PLUGIN="${2:?owner/repo}"; shift 2 ;;
    *) echo "usage: install.sh [--plugin owner/repo] [--dry-run <stand-in-dir> <test-keychain>]" >&2; exit 2 ;;
  esac
done
MOADIX_HOME="$CC_DIR/moadix"
POLICY="$CC_DIR/managed-settings.json"
CHECKER="$MOADIX_HOME/bin/moadix-checker"

say()  { printf '\n== %s\n' "$*"; }
fail() { printf '\nMOADIX SETUP FAILED: %s\nNothing further was changed. MOADIX refuses to run until this is fixed.\n' "$*" >&2; exit 1; }

if [[ $MODE == real ]]; then
  SUDO=(sudo); OWN=(-o root -g wheel)
  [[ -t 0 && -t 1 ]] || fail "run this in a real terminal, not from a pipe"
  [[ -n "${CLAUDECODE:-}" ]] && fail "this shell is inside a Claude Code session; open a new terminal window"
else
  SUDO=(); OWN=()
  [[ "$CC_DIR" == /Library/* || "$CC_DIR" == /etc/* ]] && fail "--dry-run must not point at a system path"
fi
as_root() { if [[ ${#SUDO[@]} -gt 0 ]]; then "${SUDO[@]}" "$@"; else "$@"; fi; }
put()     { as_root /usr/bin/install ${OWN[@]+"${OWN[@]}"} -m "$1" "$2" "$3"; }   # mode src dst

UPDATE=0
if [[ -d "$MOADIX_HOME" ]]; then
  grep -q '"MOADIX_PIN"' "$POLICY" 2>/dev/null || fail "$MOADIX_HOME exists but $POLICY is not MOADIX's; run managed/uninstall.sh first"
  UPDATE=1
fi

# ---- 1. preconditions --------------------------------------------------------
say "1/6 Checking this Mac ($([[ $UPDATE == 1 ]] && echo update || echo fresh install), mode: $MODE)"
ver="$(claude --version 2>/dev/null | awk '{print $1}')" || true
[[ -n "$ver" ]] || fail "claude not found on PATH"
/usr/bin/python3 -c 'import sys; v=lambda s: tuple(int(x) for x in s.split(".")); sys.exit(v(sys.argv[1]) < v(sys.argv[2]))' "$ver" "$MIN_VERSION" \
  || fail "Claude Code $ver is older than $MIN_VERSION"
echo "Claude Code $ver"
if defaults read "/Library/Managed Preferences/com.anthropic.claudecode" >/dev/null 2>&1 \
   || defaults read "/Library/Managed Preferences/$USER/com.anthropic.claudecode" >/dev/null 2>&1 \
   || profiles list 2>/dev/null | grep -qi anthropic; then
  fail "an MDM profile configures Claude Code; it outranks MOADIX's managed-settings file, so MOADIX would be ignored"
fi
echo "no MDM profile for Claude Code"
if [[ $UPDATE == 0 ]]; then
  [[ -e "$POLICY" ]] && fail "$POLICY already exists (another policy); MOADIX will not overwrite it"
  [[ -e "$CC_DIR/managed-settings.d" ]] && fail "$CC_DIR/managed-settings.d exists (another policy)"
  echo "no other managed settings"
fi

# ---- 2. build ------------------------------------------------------------------
say "2/6 Building the checker"
if [[ $MODE == real ]]; then work="$(mktemp -d "${TMPDIR:-/tmp}/moadix-install.XXXXXX")"; else work="$(mktemp -d "$(dirname "$CC_DIR")/work.XXXXXX")"; fi
canary=""
cleanup() { rm -rf "$work"; [[ -n "$canary" ]] && rm -rf "$canary"; return 0; }
trap cleanup EXIT
if [[ $MODE == real ]]; then
  "$HERE/checker/build.sh" "$work/moadix-checker"
else
  "$HERE/checker/build.sh" "$work/moadix-checker" --test "$TEST_KC" "$POLICY"
fi
cdhash() { codesign -dvvv "$1" 2>&1 | sed -n 's/^CDHash=//p'; }
if [[ $UPDATE == 1 && "$(cdhash "$work/moadix-checker")" != "$(cdhash "$CHECKER")" ]]; then
  fail "the checker binary changed in this version. The Keychain secrets can only be read by the build that created them, so this update needs: managed/uninstall.sh, then managed/install.sh (new QR code)"
fi

# ---- 3. install root-owned -------------------------------------------------------
say "3/6 Installing the gate to $MOADIX_HOME$([[ $MODE == real ]] && echo ' (sudo asks for your macOS password)')"
created_cc=0; [[ -d "$CC_DIR" ]] || created_cc=1
[[ $UPDATE == 1 ]] && created_cc="$(sed -n 's/^created_cc_dir=//p' "$MOADIX_HOME/install-record" 2>/dev/null || echo 0)"
as_root /bin/mkdir -p "$MOADIX_HOME/bin"
as_root /bin/rm -rf "$MOADIX_HOME/gate"
as_root /bin/mkdir -p "$MOADIX_HOME/gate/v1" "$MOADIX_HOME/gate/config"
put 0755 "$work/moadix-checker" "$CHECKER"
for f in "$HERE"/gate/*.py; do put 0644 "$f" "$MOADIX_HOME/gate/$(basename "$f")"; done
# increment 2: the ported v1 validators and the gate's own config (registry, policies)
for f in "$HERE"/gate/v1/*.py; do put 0644 "$f" "$MOADIX_HOME/gate/v1/$(basename "$f")"; done
for f in "$HERE"/gate/config/*.yaml "$HERE"/gate/config/*.toml "$HERE"/gate/config/*.ini; do
  put 0644 "$f" "$MOADIX_HOME/gate/config/$(basename "$f")"
done
# increment 5: the gate-run tools' own configs (semgrep rules, redocly config, the k6 wrapper)
for sub in semgrep redocly k6; do
  as_root /bin/mkdir -p "$MOADIX_HOME/gate/config/$sub"
  for f in "$HERE"/gate/config/"$sub"/*; do put 0644 "$f" "$MOADIX_HOME/gate/config/$sub/$(basename "$f")"; done
done
# increment 5: the pinned tools, root-owned, straight into $MOADIX_HOME/tools (a venv cannot be
# moved). Every download is checked against its sha256 pin; npm runs with --ignore-scripts and
# uv installs wheels only, so no package code runs as root. Kept across updates (idempotent).
if [[ $MODE == real ]]; then
  say "3b/6 Fetching the pinned gate-run tools (gate/config/tools.yaml) into $MOADIX_HOME/tools"
  as_root /usr/bin/env npm_config_cache="$work/npm-cache" /usr/bin/python3 -I "$HERE/managed/fetch_tools.py" \
    "$MOADIX_HOME/tools" || fail "a pinned tool could not be fetched or did not match its sha256 (output above)"
  pwcli="$MOADIX_HOME/tools/playwright-mcp-0.0.83/node_modules/playwright/cli.js"
  /opt/homebrew/bin/node "$pwcli" install chromium >/dev/null || fail "Playwright's Chromium could not be installed"
  echo "tools: $(ls "$MOADIX_HOME/tools" | tr '\n' ' ')"
else
  echo "(dry run: the pinned tools are not fetched; tests/tools/run.py uses ~/.cache/moadix-tools)"
fi
[[ -e "$MOADIX_HOME/gate/_testguard.py" ]] && fail "a test guard is in the installed gate; it must never be installed"
printf 'created_cc_dir=%s\ninstalled=%s\nsource=%s\n' "$created_cc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)" > "$work/install-record"
put 0644 "$work/install-record" "$MOADIX_HOME/install-record"
if [[ $MODE == real ]]; then
  as_root /usr/sbin/chown root:wheel "$CC_DIR" "$MOADIX_HOME" "$MOADIX_HOME/bin" "$MOADIX_HOME/gate" \
    "$MOADIX_HOME/gate/v1" "$MOADIX_HOME/gate/config" "$MOADIX_HOME/gate/config/semgrep" \
    "$MOADIX_HOME/gate/config/redocly" "$MOADIX_HOME/gate/config/k6"
fi
as_root /bin/chmod 0755 "$CC_DIR" "$MOADIX_HOME" "$MOADIX_HOME/bin" "$MOADIX_HOME/gate" \
  "$MOADIX_HOME/gate/v1" "$MOADIX_HOME/gate/config" "$MOADIX_HOME/gate/config/semgrep" \
  "$MOADIX_HOME/gate/config/redocly" "$MOADIX_HOME/gate/config/k6"

# ---- 4. secrets ------------------------------------------------------------------
if [[ $UPDATE == 0 ]]; then
  say "4/6 Creating the approval secret and the ledger key in your $([[ $MODE == real ]] && echo login keychain || echo test keychain)"
  out="$("$CHECKER" init)" || fail "checker init: $out"
  uri="$(sed -nE 's/^OK uri=([^ ]+) pin=.*/\1/p' <<<"$out")"
  pin="$(sed -nE 's/.* pin=([0-9a-f]{32})$/\1/p' <<<"$out")"
  [[ -n "$uri" && -n "$pin" ]] || fail "unexpected checker output"
  key="$(sed -nE 's/.*secret=([A-Z2-7]+).*/\1/p' <<<"$uri")"
  echo
  echo "Add this to Microsoft Authenticator now. It is shown ONCE."
  if command -v qrencode >/dev/null; then
    qrencode -t ansiutf8 "$uri"
    echo "Or enter it by hand:"
  else
    echo "(Install qrencode with 'brew install qrencode' to get a QR code here. Enter it by hand instead:)"
  fi
  echo "    Account name: MOADIX operator"
  echo "    Secret key:   $key"
  echo "    Type:         time based, 6 digits"
  unset uri out key
  read -r -p "Press Enter once MOADIX shows a 6-digit code in the app... " _
  [[ $MODE == real ]] && printf '\033[2J\033[3J\033[H'   # clear screen and scrollback
else
  say "4/6 Keeping the existing Keychain secrets (update)"
  pin="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["env"]["MOADIX_PIN"])' "$POLICY")"
  if [[ -z "$PLUGIN" ]]; then
    PLUGIN="$(/usr/bin/python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("extraKnownMarketplaces",{}).get("moadix",{}).get("source",{}).get("repo","none"))' "$POLICY")"
  fi
fi

# ---- 5. managed settings --------------------------------------------------------
say "5/6 Installing managed settings to $POLICY"
/usr/bin/python3 "$HERE/managed/render_policy.py" "$HERE/managed/managed-settings.json" "$CC_DIR" "$MOADIX_HOME" "$pin" "${PLUGIN:-none}" \
  > "$work/managed-settings.json" || fail "could not render the policy"
put 0644 "$work/managed-settings.json" "$POLICY"

# ---- 6. in effect? ----------------------------------------------------------------
say "6/6 Checking MOADIX is in effect"
st="$("$CHECKER" state)" || fail "the checker cannot verify its secrets against the pin: $st"
echo "checker: $st"
if [[ $MODE == real ]]; then canary="$(mktemp -d "$HOME/moadix-canary.XXXXXX")"; else canary="$(mktemp -d "$(dirname "$CC_DIR")/canary.XXXXXX")"; fi
git -C "$canary" init -q
/usr/bin/python3 "$MOADIX_HOME/gate/sdlc_init.py" "$canary" canary >/dev/null
hook() { /usr/bin/python3 "$MOADIX_HOME/gate/hook.py" "$1"; }
d="$(printf '{"tool_name":"Write","tool_input":{"file_path":".sdlc/ledger.jsonl","content":"x"},"cwd":"%s"}' "$canary" | hook pretool)"
grep -q '"permissionDecision": "deny"' <<<"$d" || fail "the installed gate did not deny a .sdlc/ write: $d"
echo "installed gate denies a .sdlc/ write"
s="$(printf '{"prompt":"STATUS","cwd":"%s"}' "$canary" | hook prompt)"
grep -q 'INTEGRITY OK' <<<"$s" || fail "the installed gate's STATUS is not clean: $s"
echo "installed gate STATUS: integrity OK"
if [[ $MODE == real ]]; then
  # Three probes through a real Claude Code session under the new policy:
  #   docs/canary-ok.txt  must be written  (positive control: commands do run)
  #   sh probe.sh         must NOT write .sdlc/  (the hook cannot see inside the script: tests the SANDBOX rule)
  #   sh -c '... .sdlc/'  must NOT write .sdlc/  (tests the HOOK)
  mkdir -p "$canary/docs"
  printf 'echo x > .sdlc/canary-sandbox\n' > "$canary/probe.sh"
  ( cd "$canary" && claude -p "Run these three shell commands with the Bash tool, one call each, in this order, and report each output verbatim. Do not retry or change them. 1) echo ok > docs/canary-ok.txt 2) sh probe.sh 3) sh -c 'echo x > .sdlc/canary-hook'" \
      --max-turns 6 > "$work/canary.txt" 2>&1 ) || true
  if [[ ! -e "$canary/docs/canary-ok.txt" ]]; then
    cat "$work/canary.txt"
    fail "the Claude Code canary ran no command (positive control missing), so the policy could not be verified. Output above."
  fi
  if [[ -e "$canary/.sdlc/canary-sandbox" ]]; then
    cat "$work/canary.txt"
    fail "a sandboxed command wrote .sdlc/: the sandbox rule for .sdlc is NOT in effect"
  fi
  if [[ -e "$canary/.sdlc/canary-hook" ]]; then
    cat "$work/canary.txt"
    fail "a command naming .sdlc/ wrote it: MOADIX's hooks are NOT in effect"
  fi
  echo "Claude Code canary: commands run; the sandbox and the hooks both stopped .sdlc/ writes"
else
  echo "(dry run: the live Claude Code canary is skipped; the stand-in path is not a policy location)"
fi

cat <<EOF

MOADIX is $([[ $UPDATE == 1 ]] && echo updated || echo installed).
  Policy:  $POLICY
  Gate:    $MOADIX_HOME
Next: open Claude Code, run /status, and check 'Setting sources' lists
'Enterprise managed settings (file)'. See docs/INSTALL.md.
EOF
