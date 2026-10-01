#!/usr/bin/env bash
# Demiurgos launcher — compatibility alias.
#
# The Linux-only launcher was reshaped into the portable POSIX launcher
# (start-demiurgos.sh, Linux + macOS). The /api/system dispatch
# (api_server.py system_control) and the desktop entry still resolve this
# name until S2b makes the dispatch OS/layout-aware; keep this alias until
# then so every existing caller keeps working.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start-demiurgos.sh" "$@"
