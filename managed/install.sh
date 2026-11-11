#!/bin/bash
# MOADIX one-time machine setup (macOS). Run by the operator in a real
# terminal, NOT from Claude Code. Needs sudo once. Written in increment 1 and
# NOT yet run on any machine.
#
#   managed/install.sh <github-owner/moadix>
#
# Steps
#   1. Preconditions: macOS, Claude Code >= 2.1.295, no MDM profile and no
#      existing managed-settings file (either would override or clash with
#      MOADIX's policy: Claude Code uses only the highest-ranked managed source).
#   2. Build the checker and sign it (ad hoc, hardened runtime).
#   3. Install the checker and the gate, root-owned, to
#      /Library/Application Support/ClaudeCode/moadix.
#   4. As YOU (not root): create both Keychain secrets in your login keychain,
#      show the TOTP QR code once, and get the pin.
#   5. Install managed-settings.json (root-owned) with the pin.
#   6. Check the policy is in effect: the active source must be this file, and
#      a canary write to .sdlc/ from a sandboxed command must fail.
set -euo pipefail

REPO_SLUG="${1:-}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="/Library/Application Support/ClaudeCode"
HOME_DIR="$DEST/moadix"
POLICY="$DEST/managed-settings.json"
MIN_VERSION="2.1.295"

say()  { printf '\n== %s\n' "$*"; }
fail() { printf '\nMOADIX SETUP FAILED: %s\nMOADIX refuses to run until this is fixed.\n' "$*" >&2; exit 1; }

[[ -n "$REPO_SLUG" && "$REPO_SLUG" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "usage: install.sh <github-owner/repo>"
[[ "$(uname -s)" == "Darwin" ]] || fail "this installer is for macOS (Linux: see docs, increment 6)"
[[ -t 0 && -t 1 ]] || fail "run this in a real terminal, not from Claude Code or a pipe"
[[ -n "${CLAUDECODE:-}" ]] && fail "this shell is inside a Claude Code session; open a new terminal"

# ---- 1. preconditions --------------------------------------------------------
say "1/6 Preconditions"
ver="$(claude --version 2>/dev/null | awk '{print $1}')" || fail "claude not found on PATH"
/usr/bin/python3 -c 'import sys; v=lambda s: tuple(int(x) for x in s.split("."));sys.exit(v(sys.argv[1]) < v(sys.argv[2]))' "$ver" "$MIN_VERSION" || fail "Claude Code $ver is older than $MIN_VERSION (onFailure: block)"
echo "Claude Code $ver"

if defaults read "/Library/Managed Preferences/com.anthropic.claudecode" >/dev/null 2>&1 \
   || defaults read "/Library/Managed Preferences/$USER/com.anthropic.claudecode" >/dev/null 2>&1; then
  fail "an MDM profile configures Claude Code (com.anthropic.claudecode). It outranks the managed-settings file, so MOADIX's policy would be ignored."
fi
if profiles list 2>/dev/null | grep -qi anthropic; then
  fail "a configuration profile mentions Anthropic; remove it or merge MOADIX into it"
fi
[[ -e "$POLICY" ]] && fail "$POLICY already exists; merge MOADIX's fragment by hand instead of overwriting another policy"
[[ -d "$DEST/managed-settings.d" ]] && fail "$DEST/managed-settings.d exists; merge by hand"
echo "no MDM profile, no existing managed settings"

# ---- 2. build the checker ----------------------------------------------------
say "2/6 Building the checker"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
"$HERE/checker/build.sh" "$work/moadix-checker"

# ---- 3. install root-owned ---------------------------------------------------
say "3/6 Installing to $HOME_DIR (sudo)"
sudo /bin/mkdir -p "$HOME_DIR/bin" "$HOME_DIR/gate"
sudo /usr/bin/install -o root -g wheel -m 0755 "$work/moadix-checker" "$HOME_DIR/bin/moadix-checker"
for f in "$HERE"/gate/*.py; do
  sudo /usr/bin/install -o root -g wheel -m 0644 "$f" "$HOME_DIR/gate/$(basename "$f")"
done
sudo /usr/sbin/chown root:wheel "$DEST" "$HOME_DIR" "$HOME_DIR/bin" "$HOME_DIR/gate"
sudo /bin/chmod 0755 "$DEST" "$HOME_DIR" "$HOME_DIR/bin" "$HOME_DIR/gate"

# ---- 4. secrets (as the user, into the login keychain) ------------------------
say "4/6 Creating the approval secret and the ledger key in your login keychain"
out="$("$HOME_DIR/bin/moadix-checker" init)" || fail "checker init: $out"
uri="$(sed -nE 's/^OK uri=([^ ]+) pin=.*/\1/p' <<<"$out")"
pin="$(sed -nE 's/.* pin=([0-9a-f]{32})$/\1/p' <<<"$out")"
[[ -n "$uri" && -n "$pin" ]] || fail "unexpected checker output"
echo
echo "Scan this into Microsoft Authenticator (Add account > Other account). It is shown ONCE."
if command -v qrencode >/dev/null; then
  qrencode -t ansiutf8 "$uri"
else
  echo "(qrencode not installed: brew install qrencode to get a QR code. Manual entry:)"
  echo "  Account: MOADIX operator    Key: $(sed -nE 's/.*secret=([A-Z2-7]+).*/\1/p' <<<"$uri")    Type: time based"
fi
unset uri out
read -r -p "Press Enter once the account shows in the app... " _
printf '\033[2J\033[3J\033[H'   # clear the screen and scrollback

# ---- 5. managed settings ------------------------------------------------------
say "5/6 Installing managed settings"
sed -e "s|__PIN__|$pin|" -e "s|__MARKETPLACE_REPO__|$REPO_SLUG|g" "$HERE/managed/managed-settings.json" > "$work/managed-settings.json"
/usr/bin/python3 -m json.tool "$work/managed-settings.json" >/dev/null || fail "generated policy is not valid JSON"
sudo /usr/bin/install -o root -g wheel -m 0644 "$work/managed-settings.json" "$POLICY"

# ---- 6. policy in effect -----------------------------------------------------
say "6/6 Checking the policy is in effect"
st="$("$HOME_DIR/bin/moadix-checker" state)" || fail "checker cannot verify its secrets against the pin: $st"
echo "checker: $st"

canary="$(mktemp -d "$HOME/moadix-canary.XXXXXX")"
git -C "$canary" init -q
/usr/bin/python3 "$HOME_DIR/gate/sdlc_init.py" "$canary" canary >/dev/null
( cd "$canary" && claude -p "Run this exact shell command once with the Bash tool, then report its output verbatim: sh -c 'echo x > .sdlc/canary-probe'" \
    --allowedTools Bash --max-turns 3 >"$work/canary.txt" 2>&1 ) || true
if [[ -e "$canary/.sdlc/canary-probe" ]]; then
  cat "$work/canary.txt"
  fail "a sandboxed command wrote .sdlc/ - the managed policy is NOT in effect (another source outranks it, or the sandbox is off)"
fi
echo "canary write to .sdlc/ was refused"
rm -rf "$canary"

cat <<EOF

MOADIX is installed.
  - In any Claude Code session run /status: 'Setting sources' must list
    'Enterprise managed settings (file)'. If it names anything else, MOADIX's
    policy is not the one in effect.
  - After 3 wrong codes approvals lock. Unlock at the Mac, in a terminal:
      "$HOME_DIR/bin/moadix-checker" unlock --code <current code>
    macOS asks for your password; a process without you at the keyboard cannot answer.
  - Start a product: /usr/bin/python3 "$HOME_DIR/gate/sdlc_init.py" <repo> <product-id>
EOF
