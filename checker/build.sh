#!/bin/bash
# Build and ad-hoc sign the checker with the hardened runtime
# (no DYLD_* injection, no debugger attach without root).
#   build.sh <out>                      production: default (login) keychain
#   build.sh <out> --test <keychain> <pinfile>
#        test build: pinned test keychain and pin file;
#        skips the root-ownership check on the pin file
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; out="$1"; shift
defs=()
if [[ "${1:-}" == "--test" ]]; then defs=(-DMOADIX_TEST "-DMOADIX_KEYCHAIN=\"$2\"" "-DMOADIX_PINFILE=\"$3\""); fi
clang -O2 -Wall -Wextra -Wno-unused-parameter ${defs[@]+"${defs[@]}"} -framework Security -framework CoreFoundation \
  -o "$out" "$here/moadix-checker.c"
codesign -s - -o runtime -f --identifier com.moadix.checker "$out" 2>/dev/null
codesign -dv "$out" 2>&1 | grep -E 'Identifier|flags|CDHash'
