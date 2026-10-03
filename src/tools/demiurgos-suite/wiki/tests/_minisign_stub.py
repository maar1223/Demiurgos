# -*- coding: utf-8 -*-
"""Harness helper: a stub ``minisign`` for the signed-channel cells (S5b).

Why this exists
---------------
S5b made the installers verify the channel manifest signature BEFORE any
checksum (fail-closed). The integration harness therefore needs a signer. The
first cut gated those cells on a REAL ``minisign`` being on ``PATH``, so on any
machine without it they silently skipped (93 passed / 14 skipped locally where
the report claimed 102 / 5).

This module provisions a dependency-free stub ``minisign`` and puts it on
``PATH`` **when no real one is installed**, so the install -> boot cells run
everywhere and still exercise the installer's ORDERING and FAIL-CLOSED logic
(a tampered, mismatched or absent signature aborts the install).

What the stub does NOT prove
----------------------------
It is not Ed25519 — it only emulates the CLI surface. ``HAS_REAL_MINISIGN``
records whether a real binary was present BEFORE the stub was installed; the
tests that prove the actual cryptographic round-trip stay gated on it (CI
installs the real minisign).

Importing this module has the side effect of provisioning the stub.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

STUB_DIR = Path(tempfile.gettempdir()) / "demiurgos-minisign-stub" / "bin"

# Evaluated BEFORE the stub is provisioned: the real-crypto tests gate on it.
HAS_REAL_MINISIGN = shutil.which("minisign") is not None

_STUB_SOURCE = '''#!/usr/bin/env python3
# Stub minisign for the Demiurgos harness (S5b). CLI surface only:
#   -G -W -s <key> -p <pub>   generate a placeholder keypair
#   -Sm <file> -s <key>       write <file>.minisig as "stub-minisig:<sha256>"
#   -Vm <file> -P <pubkey>    exit 0 only when <file>.minisig matches
# It performs NO cryptography: it exists so the installer wiring can be
# exercised without a system minisign. The real round-trip is proven by the
# real-minisign-gated tests (CI installs minisign).
import hashlib
import pathlib
import sys


def _opt(args, flag):
    try:
        return args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main(argv):
    args = argv[1:]
    if "-G" in args:
        key, pub = _opt(args, "-s"), _opt(args, "-p")
        if not key or not pub:
            return 2
        pathlib.Path(key).write_text("stub-secret\\n")
        pathlib.Path(pub).write_text("RWSSTUB-PUBLIC-KEY-NOT-REAL\\n")
        return 0
    if "-Sm" in args:
        target = _opt(args, "-Sm")
        if not target:
            return 2
        pathlib.Path(target + ".minisig").write_text(
            "stub-minisig:" + _sha(target) + "\\n")
        return 0
    if "-Vm" in args:
        target = _opt(args, "-Vm")
        if not target:
            return 2
        sig = pathlib.Path(target + ".minisig")
        if not sig.is_file():
            return 1
        return 0 if sig.read_text().strip() == "stub-minisig:" + _sha(target) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
'''


def provision() -> None:
    """Idempotently write the stub and prepend its dir to PATH when there is no
    real ``minisign``. Safe to call repeatedly."""
    if HAS_REAL_MINISIGN:
        return
    STUB_DIR.mkdir(parents=True, exist_ok=True)
    stub = STUB_DIR / "minisign"
    if not stub.is_file():
        stub.write_text(_STUB_SOURCE, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    current = os.environ.get("PATH", "")
    if str(STUB_DIR) not in current.split(os.pathsep):
        os.environ["PATH"] = str(STUB_DIR) + os.pathsep + current


provision()
