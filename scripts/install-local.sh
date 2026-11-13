#!/usr/bin/env bash
# Demiurgos — local install vehicle (this machine only).
#
# Builds THIS checkout and installs it as a real app/<version> under the
# install root, flipping `current` the same way the release installer does —
# but with NO tag, NO publish, NO download and NO signature. It is the fast
# loop for iterating on the Owner's machine: the release channel is untouched.
#
# Design notes
#   - The payload shape is the release payload shape: payload_manifest.json
#     (default-deny allow-list) + the explicit extras the workflow ships +
#     frontend/dist + requirements.lock. What you test locally is what ships.
#   - The version is SemVer build metadata: <base>+local.<sha>[.dirty]. Build
#     metadata never affects precedence, so the updater compares it EQUAL to
#     the same released version and never nags with a bogus "update available".
#   - The venv is created per version with the pinned uv and the hash-locked
#     requirements (the uv cache makes repeats fast). Nothing is shared, so a
#     version dir stays self-contained and rollback keeps working.
#   - Previous versions are never deleted. The launcher's bounded rollback can
#     always fall back to them.
#
# Usage: scripts/install-local.sh [--build|--no-build] [--no-restart]
#                                [--dry-run] [--version LABEL]
set -euo pipefail

fail() {
    printf 'install-local: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: scripts/install-local.sh [options]

Builds this checkout and installs it as a local Demiurgos version, bypassing
the release channel (no tag, no publish, no download, no signature).

Options:
  --build        force the frontend build
  --no-build     never rebuild the frontend (use frontend/dist as-is)
  --no-restart   install and flip `current` without restarting the app
  --dry-run      print the plan and exit without writing anything
  --version V    override the local version label
  -h, --help     show this help

The default label is <base>+local.<sha>[.dirty]: SemVer build metadata, so the
updater compares it equal to the same released version and never nags.
EOF
}

BUILD_MODE=auto
RESTART=1
DRY_RUN=0
VERSION_OVERRIDE=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --build) BUILD_MODE=always ;;
        --no-build) BUILD_MODE=never ;;
        --no-restart) RESTART=0 ;;
        --dry-run) DRY_RUN=1 ;;
        --version)
            [ "$#" -ge 2 ] || fail "--version needs a label"
            VERSION_OVERRIDE="$2"
            shift
            ;;
        --version=*) VERSION_OVERRIDE="${1#--version=}" ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'install-local: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="${DEMIURGOS_HOME:-$HOME/.demiurgos}"
UV_BIN="${UV_BIN:-$INSTALL_ROOT/bin/uv}"
UV_PYTHON_INSTALL_DIR="$INSTALL_ROOT/python"
export UV_PYTHON_INSTALL_DIR

[ -f "$REPO_ROOT/payload_manifest.json" ] \
    || fail "payload_manifest.json is missing at $REPO_ROOT; run it from the checkout"
[ -f "$REPO_ROOT/requirements.lock" ] \
    || fail "requirements.lock is missing at $REPO_ROOT"
[ -d "$REPO_ROOT/frontend" ] \
    || fail "frontend/ is missing at $REPO_ROOT"

# --- version label ---------------------------------------------------------
base="$(git -C "$REPO_ROOT" describe --tags --abbrev=0 2>/dev/null | sed 's/^v//')"
[ -n "$base" ] || fail "no git tag found; cannot derive the base version (git describe failed)"

sha="$(git -C "$REPO_ROOT" rev-parse --short=7 HEAD)"
dirty=""
if [ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=no)" ]; then
    dirty=".dirty"
fi

if [ -n "$VERSION_OVERRIDE" ]; then
    VERSION="$VERSION_OVERRIDE"
else
    VERSION="${base}+local.${sha}${dirty}"
fi

if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\+local\.[0-9a-f]+(\.dirty)?$'; then
    fail "the local version '$VERSION' is not <X.Y.Z>+local.<sha>[.dirty]; the updater would misread it"
fi

APP_DIR="$INSTALL_ROOT/app/$VERSION"

# --- frontend build decision ----------------------------------------------
dist_index="$REPO_ROOT/frontend/dist/index.html"
need_build=0
build_reason=""
case "$BUILD_MODE" in
    always)
        need_build=1
        build_reason="forced by --build"
        ;;
    auto)
        if [ ! -f "$dist_index" ]; then
            need_build=1
            build_reason="frontend/dist is missing"
        elif [ -n "$(find "$REPO_ROOT/frontend/src" -type f -newer "$dist_index" -print -quit 2>/dev/null)" ]; then
            need_build=1
            build_reason="frontend/src is newer than the built bundle"
        else
            build_reason="frontend/dist is up to date"
        fi
        ;;
    never)
        [ -f "$dist_index" ] || fail "--no-build was requested but frontend/dist/index.html does not exist"
        build_reason="forced by --no-build"
        ;;
esac

# --- preflight -------------------------------------------------------------
[ -d "$INSTALL_ROOT/app" ] \
    || fail "$INSTALL_ROOT/app is missing; install Demiurgos normally once before using the local vehicle"
[ -x "$UV_BIN" ] \
    || fail "$UV_BIN is not executable; the pinned uv ships with a normal install"

if [ "$need_build" = 1 ] && [ "$DRY_RUN" = 0 ]; then
    [ -d "$REPO_ROOT/frontend/node_modules" ] \
        || fail "frontend/node_modules is missing; run 'npm ci' in frontend/ first"
    command -v npm >/dev/null 2>&1 || fail "npm is not on PATH but a frontend build is needed"
fi

payload_count="$(
    python3 - "$REPO_ROOT/payload_manifest.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print(len(data["payload"]))
PY
)"

printf 'install-local: version      %s\n' "$VERSION"
printf 'install-local: checkout     %s\n' "$REPO_ROOT"
printf 'install-local: install root %s\n' "$INSTALL_ROOT"
printf 'install-local: app dir      %s\n' "$APP_DIR"
printf 'install-local: payload      %s manifest entries + extras + frontend/dist\n' "$payload_count"
printf 'install-local: frontend     %s\n' "$build_reason"
printf 'install-local: restart      %s\n' "$([ "$RESTART" = 1 ] && echo yes || echo no)"

if [ "$DRY_RUN" = 1 ]; then
    printf 'install-local: dry run — nothing was written\n'
    exit 0
fi

# --- frontend build --------------------------------------------------------
if [ "$need_build" = 1 ]; then
    printf 'install-local: building the frontend...\n' >&2
    (cd "$REPO_ROOT/frontend" && npm run build) \
        || fail "the frontend build failed; nothing was installed"
fi
[ -f "$dist_index" ] || fail "frontend/dist/index.html is missing after the build"

# --- stage the payload -----------------------------------------------------
mkdir -p "$INSTALL_ROOT/.staging"
STAGE_DIR="$INSTALL_ROOT/.staging/local-$$"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
trap 'rm -rf "$STAGE_DIR"' EXIT

while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    if [ ! -f "$REPO_ROOT/$rel" ]; then
        printf 'install-local: warn: manifest entry missing, skipped: %s\n' "$rel" >&2
        continue
    fi
    mkdir -p "$STAGE_DIR/$(dirname "$rel")"
    cp "$REPO_ROOT/$rel" "$STAGE_DIR/$rel"
done < <(
    python3 - "$REPO_ROOT/payload_manifest.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print("\n".join(data["payload"]))
PY
)

for rel in \
    install.sh install.ps1 start-api.ps1 start-gateway.ps1 \
    scripts/start-demiurgos.sh scripts/install-demiurgos.sh \
    scripts/install-demiurgos.ps1 scripts/provision-hermes.sh \
    scripts/provision-hermes.ps1 scripts/collect-diagnostics.sh \
    scripts/lib/verify_checksum.sh scripts/lib/verify_checksum.ps1 \
    scripts/lib/desktop-shortcut.ps1 third-party/hermes/LICENSE \
    desktop/Demiurgos.desktop \
    "docs/Logos-Demiurgos/dorado/01_svg_dorado/letra-D-6tonos.svg" \
    "docs/Logos-Demiurgos/dorado/03_ico_dorado/demiurgos.ico" \
    requirements.lock requirements-optional.txt LICENSE; do
    if [ ! -f "$REPO_ROOT/$rel" ]; then
        printf 'install-local: warn: extra missing, skipped: %s\n' "$rel" >&2
        continue
    fi
    mkdir -p "$STAGE_DIR/$(dirname "$rel")"
    cp "$REPO_ROOT/$rel" "$STAGE_DIR/$rel"
done

if [ -f "$REPO_ROOT/start-demiurgos.ps1" ]; then
    mkdir -p "$STAGE_DIR/scripts"
    cp "$REPO_ROOT/start-demiurgos.ps1" "$STAGE_DIR/scripts/start-demiurgos.ps1"
fi

mkdir -p "$STAGE_DIR/frontend/dist"
cp -R "$REPO_ROOT/frontend/dist/." "$STAGE_DIR/frontend/dist/"

# --- venv ------------------------------------------------------------------
printf 'install-local: creating the venv (uv cache makes repeats fast)...\n' >&2
"$UV_BIN" venv --python 3.12 "$STAGE_DIR/.venv" \
    || fail "uv venv failed; nothing was installed"
"$UV_BIN" pip install --python "$STAGE_DIR/.venv/bin/python" \
    --require-hashes --only-binary=:all: \
    -r "$REPO_ROOT/requirements.lock" \
    || fail "dependency install failed; nothing was installed"

# --- commit + flip ---------------------------------------------------------
rm -rf "$APP_DIR"
mv "$STAGE_DIR" "$APP_DIR" \
    || fail "cannot move the staged app into app/$VERSION; re-run"
trap - EXIT
ln -sfn "app/$VERSION" "$INSTALL_ROOT/current" \
    || fail "cannot flip current -> app/$VERSION; the previous version is untouched"

printf 'install-local: installed %s at %s/current\n' "$VERSION" "$INSTALL_ROOT" >&2

# --- restart ---------------------------------------------------------------
if [ "$RESTART" = 1 ]; then
    printf 'install-local: restarting the launcher...\n' >&2
    if ! "$INSTALL_ROOT/current/scripts/start-demiurgos.sh" restart; then
        fail "the launcher restart failed; the previous version is still installed and rollback stays available"
    fi
else
    printf 'install-local: restart skipped; start it with %s/current/scripts/start-demiurgos.sh start\n' \
        "$INSTALL_ROOT" >&2
fi
