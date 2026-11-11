#!/bin/bash
# Remove MOADIX from this Mac and leave it as it was before install.sh.
# Run by the operator in a real terminal, NOT from inside Claude Code.
#
#   managed/uninstall.sh                          real (asks for your macOS password once)
#   managed/uninstall.sh --dry-run <stand-in-dir> <test-keychain>    test mode, no sudo
#
# Removes:
#   - <cc-dir>/managed-settings.json   (only if it is MOADIX's: it carries MOADIX_PIN)
#   - <cc-dir>/moadix                  (the root-owned gate copy and checker)
#   - <cc-dir> itself, if install.sh created it and it is now empty
#   - the Keychain items: moadix-totp, moadix-ledger-key, moadix-state, every moadix-anchor
#   - real mode: the moadix plugin and marketplace from Claude Code's user config, if present
# Keeps: each product repo's .sdlc/ (your data). They are listed at the end.
set -euo pipefail

REAL_CC_DIR="/Library/Application Support/ClaudeCode"   # the ONLY place the real path is set
MODE=real; CC_DIR="$REAL_CC_DIR"; KC=()
if [[ "${1:-}" == "--dry-run" ]]; then
  MODE=dry; CC_DIR="${2:?stand-in dir}"; KC=("${3:?test keychain}")
  [[ "$CC_DIR" == /Library/* || "$CC_DIR" == /etc/* ]] && { echo "--dry-run must not point at a system path" >&2; exit 2; }
elif [[ $# -gt 0 ]]; then
  echo "usage: uninstall.sh [--dry-run <stand-in-dir> <test-keychain>]" >&2; exit 2
fi
MOADIX_HOME="$CC_DIR/moadix"
POLICY="$CC_DIR/managed-settings.json"
if [[ $MODE == real ]]; then
  SUDO=(sudo)
  [[ -n "${CLAUDECODE:-}" ]] && { echo "Run this in a terminal outside Claude Code." >&2; exit 1; }
else
  SUDO=()
fi
as_root() { if [[ ${#SUDO[@]} -gt 0 ]]; then "${SUDO[@]}" "$@"; else "$@"; fi; }
say() { printf '\n== %s\n' "$*"; }

say "1/4 Managed settings"
if [[ -f "$POLICY" ]]; then
  if grep -q '"MOADIX_PIN"' "$POLICY"; then
    as_root /bin/rm -f "$POLICY"
    echo "removed $POLICY"
  else
    echo "left $POLICY alone: it is not MOADIX's"
  fi
else
  echo "no $POLICY"
fi

say "2/4 Gate copy and checker"
created_cc=0
if [[ -d "$MOADIX_HOME" ]]; then
  created_cc="$(sed -n 's/^created_cc_dir=//p' "$MOADIX_HOME/install-record" 2>/dev/null || echo 0)"
  as_root /bin/rm -rf "$MOADIX_HOME"
  echo "removed $MOADIX_HOME"
else
  echo "no $MOADIX_HOME"
fi
if [[ "$created_cc" == 1 && -d "$CC_DIR" ]]; then
  if [[ -z "$(ls -A "$CC_DIR")" ]]; then
    as_root /bin/rmdir "$CC_DIR"
    echo "removed $CC_DIR (install.sh had created it)"
  else
    echo "left $CC_DIR: it now holds other files"
  fi
fi

say "3/4 Keychain items"
del() { security delete-generic-password -s "$1" ${2:+-a "$2"} ${KC[@]+"${KC[@]}"} >/dev/null 2>&1; }
for svc in moadix-totp moadix-ledger-key moadix-state; do
  if del "$svc" operator; then echo "deleted $svc"; else echo "no $svc"; fi
done
n=0; while del moadix-anchor; do n=$((n + 1)); [[ $n -lt 10000 ]] || break; done
echo "deleted $n moadix-anchor item(s)"

say "4/4 Claude Code plugin"
if [[ $MODE == real ]]; then
  if claude plugin list 2>/dev/null | grep -q 'moadix@moadix'; then
    claude plugin uninstall moadix@moadix >/dev/null 2>&1 && echo "uninstalled plugin moadix@moadix" || echo "could not uninstall moadix@moadix; run: claude plugin uninstall moadix@moadix"
  else
    echo "plugin moadix@moadix not installed"
  fi
  if claude plugin marketplace list 2>/dev/null | grep -qw moadix; then
    claude plugin marketplace remove moadix >/dev/null 2>&1 && echo "removed marketplace moadix" || echo "could not remove marketplace moadix"
  else
    echo "marketplace moadix not configured"
  fi
else
  echo "(dry run: Claude Code's plugin config is not touched)"
fi

echo
echo "MOADIX is removed. Product repos keep their .sdlc/ (your records); delete them by hand if you want."
