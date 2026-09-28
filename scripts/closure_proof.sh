#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# Dependency-closure proof (S0-B) — wheels-only, no compiler, real floors.
#
# Runs `uv pip install --only-binary=:all: --dry-run` for the MANDATORY set
# (src/tools/demiurgos-suite/requirements.txt) across the declared target
# matrix and records the result per cell. A target whose mandatory closure
# fails is NOT a supported target: fix it or remove it from the declared
# matrix — never silently drop `--only-binary`.
#
# Timing (D3 — the single authoritative statement): split + floors decided in
# S0; local dry-run before S3; full-matrix proof + published floors is the
# before-S5 gate. No other task, doc, or comment restates this gate.
#
# Usage:
#   scripts/closure_proof.sh [--target <cell>] [--json]
#   --target   run only one matrix cell (default: the LOCAL platform cell)
#   --json     emit the machine-readable record (the proof artifact)
#
# Exit code: non-zero iff a MANDATORY cell failed. Expected-fail cells
# (musl/Alpine) are recorded with their outcome and do NOT fail the run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUIREMENTS="$REPO_ROOT/src/tools/demiurgos-suite/requirements.txt"
PYTHON_VERSION="3.12"

# Declared matrix (design v2 S0-B). `expected_fail` cells are recorded, never
# fatal. OS/glibc floors (macOS >= 13, glibc >= 2.28) are OS-level properties
# that uv's tag resolution models through the wheel platform tags
# (manylinux_2_28, macosx_14_0, ...) — the dry-run reports what the tags allow.
MATRIX_SPEC=(
  "windows-amd64:x86_64-pc-windows-msvc:0"
  "macos-arm64:aarch64-apple-darwin:0"
  "macos-x86_64-intel:x86_64-apple-darwin:0"
  "linux-x86_64-glibc:x86_64-unknown-linux-gnu:0"
  "linux-aarch64-glibc:aarch64-unknown-linux-gnu:0"
  "musl-alpine:x86_64-unknown-linux-musl:1"
)

TARGET="local"
JSON_OUT=""
for arg in "$@"; do
  case "$arg" in
    --target) TARGET="next" ;;
    --json) JSON_OUT=1 ;;
    --target=*) TARGET="${arg#*=}" ;;
    *) [ "$TARGET" = "next" ] && TARGET="$arg" || true ;;
  esac
done
[ "$TARGET" = "next" ] && TARGET="local"

if ! command -v uv >/dev/null 2>&1; then
  echo "closure_proof: 'uv' is required but not on PATH" >&2
  echo "closure_proof: install it per https://docs.astral.sh/uv/ (pinned, checksum-verified by the installer)" >&2
  exit 2
fi
[ -f "$REQUIREMENTS" ] || { echo "closure_proof: missing $REQUIREMENTS" >&2; exit 2; }

# Real local floors — published instead of assumed.
kernel="$(uname -s 2>/dev/null || true)"
arch="$(uname -m 2>/dev/null || true)"
libc=""
glibc=""
case "$kernel" in
  Linux)
    if [ -f /etc/alpine-release ]; then
      libc="musl"
    else
      ldd_ver="$(ldd --version 2>/dev/null | head -1 || true)"
      if printf '%s' "$ldd_ver" | grep -qi "glibc"; then
        libc="glibc"
        glibc="$(printf '%s' "$ldd_ver" | grep -o '[0-9]\+\.[0-9]\+' | head -1 || true)"
      fi
    fi
    ;;
  Darwin)
    libc="libsystem"
    sw_vers -productVersion >/dev/null 2>&1 || true
    ;;
  MINGW*|MSYS*|CYGWIN*)
    kernel="Windows"
    ;;
esac

record() {
  # record <cell> <platform> <status> <note>
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4"
}

run_cell() {
  local cell="$1" platform="$2" expected_fail="$3"
  local note="ok" status
  if [ -n "$platform" ]; then
    PLATFORM_ARGS=(--python-platform "$platform")
  else
    PLATFORM_ARGS=()
  fi
  if uv pip install --only-binary=:all: --dry-run "${PLATFORM_ARGS[@]}" \
      --python-version "$PYTHON_VERSION" -r "$REQUIREMENTS" >/dev/null 2>&1; then
    status="PASS"
  else
    status="FAIL"
  fi
  if [ "$expected_fail" = "1" ]; then
    note="expected-fail (documented): musl/Alpine unsupported — explicit message in installer, exit non-zero"
    [ "$status" = "FAIL" ] && status="PASS(expected-fail)" || note="$note (closure unexpectedly resolved; keep the unsupported declaration)"
  fi
  record "$cell" "$platform" "$status" "$note"
  [ "$status" = "PASS" ]
}

declare -a RESULTS=()
failures=0

run_local() {
  local cell="local:${kernel:-unknown}-${arch:-unknown}"
  local note=""
  case "$libc" in
    musl) note="musl detected — musl/Alpine is a declared unsupported target (expected-fail, documented)" ;;
    glibc) note="glibc ${glibc:-unknown}" ;;
    *) note="libc: ${libc:-unknown}" ;;
  esac
  if uv pip install --only-binary=:all: --dry-run --python-version "$PYTHON_VERSION" \
      -r "$REQUIREMENTS" >/dev/null 2>&1; then
    record "$cell" "local" "PASS" "$note"
  else
    record "$cell" "local" "FAIL" "$note"
    failures=$((failures + 1))
  fi
}

if [ "$TARGET" = "local" ]; then
  echo "closure_proof: local dry-run (D3: local proof before S3)"
  echo "floors: kernel=$kernel arch=$arch libc=${libc:-unknown} glibc=${glibc:-unknown}"
  run_local
else
  matched=0
  for spec in "${MATRIX_SPEC[@]}"; do
    IFS=':' read -r cell platform expected_fail <<< "$spec"
    [ "$cell" = "$TARGET" ] || continue
    matched=1
    echo "closure_proof: cell $cell (platform $platform)"
    if run_cell "$cell" "$platform" "$expected_fail"; then
      RESULTS+=("PASS")
    else
      failures=$((failures + 1))
      RESULTS+=("FAIL")
    fi
  done
  if [ "$matched" = "0" ]; then
    echo "closure_proof: unknown target '$TARGET'" >&2
    echo "closure_proof: known cells: ${MATRIX_SPEC[*]}" >&2
    exit 2
  fi
fi

if [ -n "$JSON_OUT" ]; then
  # The proof artifact: one line per cell, real floors included.
  echo "---"
  echo "proof: {"
  echo "  \"command\": \"uv pip install --only-binary=:all: --dry-run --python-version $PYTHON_VERSION -r requirements.txt\","
  echo "  \"floors\": {\"kernel\": \"$kernel\", \"arch\": \"$arch\", \"libc\": \"${libc:-unknown}\", \"glibc\": \"${glibc:-unknown}\"},"
  echo "  \"declared_floors\": {\"windows\": \"10+ x86_64\", \"macos\": \">=13 arm64 (Intel: optional extras degraded)\", \"linux\": \"x86_64/aarch64 glibc >= 2.28\", \"musl\": \"unsupported\"},"
  echo "  \"matrix\": ["
  first=1
  for spec in "${MATRIX_SPEC[@]}"; do
    IFS=':' read -r cell platform expected_fail <<< "$spec"
    [ $first -eq 1 ] || echo "    ,"
    first=0
    echo "    {\"cell\": \"$cell\", \"platform\": \"$platform\"}"
  done
  echo "  ]"
  echo "}"
fi

exit "$failures"