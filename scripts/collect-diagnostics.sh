#!/usr/bin/env bash
# Demiurgos - copy diagnostics for support (S6-2, task 9.3).
#
# Packs the version, the platform facts and the persistent logs into one
# tarball the user can attach to a support request. READ-ONLY: it never
# modifies the install, never restarts anything and never touches world data.
#
# PRIVACY: the bundle may contain local paths, hostnames and whatever the
# application wrote to its logs. It is produced for the user to review before
# sharing - the script prints that warning and does not upload anything.
#
# Usage: scripts/collect-diagnostics.sh [output.tar.gz]
set -eu

INSTALL_ROOT="${DEMIURGOS_HOME:-$HOME/.demiurgos}"
LOG_DIR="$INSTALL_ROOT/logs"
OUT="${1:-$PWD/demiurgos-diagnostics-$(date -u +%Y%m%dT%H%M%SZ).tar.gz}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

{
    printf 'collected_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'install_root=%s\n' "$INSTALL_ROOT"
    printf 'uname=%s\n' "$(uname -a 2>/dev/null || echo unknown)"
    printf 'current_target=%s\n' "$(readlink "$INSTALL_ROOT/current" 2>/dev/null || echo unknown)"
    for version_dir in "$INSTALL_ROOT"/app/*; do
        [ -d "$version_dir" ] && printf 'installed_version=%s\n' "$(basename "$version_dir")"
    done
} >"$WORK/system.txt" 2>&1

if [ -d "$LOG_DIR" ]; then
    mkdir -p "$WORK/logs"
    cp -a "$LOG_DIR/." "$WORK/logs/" 2>/dev/null || true
fi

tar -czf "$OUT" -C "$WORK" .
printf 'diagnostics written to %s\n' "$OUT"
printf 'review it before sharing: it may contain local paths and log contents.\n'
