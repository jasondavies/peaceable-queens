#!/bin/sh
# Download, check (SHA-256) and build drat-trim at commit 2e3b2dc0ecf938addbd779d42877b6ed69d9a985,
# the DRUP/DRAT proof checker used by code/sat_check.py.  It is built in tools/ (git-ignored); nothing is
# installed elsewhere.  Idempotent.  Set DRATTRIM_TARBALL to use a local copy of the tarball.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$ROOT/tools
mkdir -p "$T"
DT_COMMIT=2e3b2dc0ecf938addbd779d42877b6ed69d9a985
DT_URL=https://github.com/marijnheule/drat-trim/archive/$DT_COMMIT.tar.gz
DT_SHA=a75e5a2072fa5a5493ee8504067661c6b452d45a32f889ac5b2c9470c227b58c
TB=$T/drat-trim-$DT_COMMIT.tar.gz
if [ ! -x "$T/drat-trim" ]; then
  if [ -n "${DRATTRIM_TARBALL:-}" ]; then cp "$DRATTRIM_TARBALL" "$TB"
  elif [ ! -f "$TB" ]; then curl -sSfL -o "$TB.part" "$DT_URL" && mv "$TB.part" "$TB"; fi
  echo "$DT_SHA  $TB" | sha256sum -c --quiet - || { echo "SHA-256 mismatch for $TB" >&2; rm -f "$TB"; exit 1; }
  rm -rf "$T/drat-trim-src" && mkdir "$T/drat-trim-src"
  tar -xzf "$TB" -C "$T/drat-trim-src" --strip-components=1
  # -D_DEFAULT_SOURCE declares getc_unlocked under -std=c99 (GCC 14 makes implicit declarations an error)
  (cd "$T/drat-trim-src" && gcc drat-trim.c -std=c99 -D_DEFAULT_SOURCE -O2 -o drat-trim)
  cp "$T/drat-trim-src/drat-trim" "$T/drat-trim"
fi
echo "drat-trim $DT_COMMIT (tarball SHA-256 $DT_SHA)"
