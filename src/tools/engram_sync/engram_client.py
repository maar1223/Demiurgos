"""Fixed-argv Engram CLI wrapper: typed errors, bounded retries, fail-closed
authz. Errors never carry content, prompts, raw tokens, or environment values.

The installed CLI exposes flat commands (``engram search``, ``engram save``)
with human-readable output; some builds return JSON. The client calls the
flat commands and tolerates both output shapes, preferring structured JSON
when present. The flat search output omits the ``topic`` field, so adapters
match remote rows by title and ENGRAM_ONLY discovery is best-effort.
"""

import json
import re
import subprocess
import time
from typing import Any, Callable, Sequence

from .models import Action, AuthorizedOperation

_TIMEOUT = 15.0
MAX_ATTEMPTS = 3
BACKOFFS = (1.0, 4.0)
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_ACTIONS = frozenset({a.value for a in Action})

_FOUND = re.compile(r"\s*Found \d+ memories?")
_EMPTY = re.compile(r"\s*No memories? found")
_FLAT_HEADER = re.compile(r"^\[\d+\] #(\d+) \(([^)]*)\) \u2014 (.*)$")
_FLAT_FOOTER = re.compile(
    r"^\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| project: \S+ \| scope: \S+$")
_SAVED_ID = re.compile(r"#(\d+)")


class EngramError(Exception):
    """Typed client failure; message never contains content or tokens."""


class EngramBinaryMissing(EngramError): pass


class EngramExitError(EngramError):
    def __init__(self, result_code: int) -> None:
        self.result_code = result_code
        super().__init__(f"engram exited with code {result_code}")


class EngramTimeout(EngramError): pass


class EngramMalformedOutput(EngramError): pass


class EngramSearchTruncated(EngramError): pass


class EngramUnauthorized(EngramError): pass


class EngramClient:
    """Read-only by default; writes need mode='read-write' plus authorization."""

    def __init__(self, cmd: str = "engram", timeout: float = _TIMEOUT,
                 sleep: Callable[[float], Any] = time.sleep,
                 mode: str = "read") -> None:
        self._cmd = cmd
        self._timeout = timeout
        self._sleep = sleep
        self._mode = mode

    def search(self, project: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or not 0 < limit <= 10_000:
            raise ValueError("search limit must be between 1 and 10000")
        stdout = self._run((self._cmd, "search", query, "--project", project,
                            "--limit", str(limit)))
        data = self._json(stdout)
        if data is None:
            rows = _parse_flat(stdout)
            if rows is None:
                raise EngramMalformedOutput("engram returned invalid search output")
            reported = _reported_count(stdout)
            if reported is not None and reported > len(rows):
                raise EngramSearchTruncated("engram search returned incomplete results")
            return rows
        return _parse_json_search(data, limit)

    def save(self, authorized: AuthorizedOperation, *, project: str, topic: str,
             title: str, content: str) -> dict[str, Any]:
        """Persist one observation; runs only in write mode with valid authz."""
        if self._mode != "read-write":
            raise EngramUnauthorized("client is read-only")
        self._authorize(authorized, project, topic)
        stdout = self._run((self._cmd, "save", title, content, "--project", project,
                            "--topic", topic))
        data = self._json(stdout)
        if data is None:
            match = _SAVED_ID.search(stdout)
            return {"id": match.group(1)} if match else {}
        return data if isinstance(data, dict) else {}

    def _authorize(self, op: AuthorizedOperation, project: str, topic: str) -> None:
        checks = (("action", getattr(op.action, "value", op.action) in _ACTIONS),
                  ("project", bool(_SAFE.fullmatch(project))),
                  ("topic", bool(_SAFE.fullmatch(topic))),
                  ("operation identity", bool(op.domain and op.item_key and op.source_revision)))
        invalid = [name for name, ok in checks if not ok]
        if invalid:
            raise EngramUnauthorized("refusing write: invalid " + ", ".join(invalid))

    def _json(self, stdout: str) -> Any:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return None

    def _run(self, argv: Sequence[str]) -> str:
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._once(argv)
            except (EngramTimeout, EngramExitError) as err:
                if attempt == MAX_ATTEMPTS - 1:
                    raise err
                self._sleep(BACKOFFS[attempt])

    def _once(self, argv: Sequence[str]) -> str:
        try:
            proc = subprocess.run(list(argv), capture_output=True, encoding="utf-8",
                                  timeout=self._timeout, check=False)
        except FileNotFoundError as err:
            raise EngramBinaryMissing(f"engram binary not found: {self._cmd}") from err
        except subprocess.TimeoutExpired as err:
            raise EngramTimeout("engram operation timed out") from err
        if proc.returncode != 0:
            raise EngramExitError(proc.returncode)
        return proc.stdout


def _parse_flat(stdout: str) -> list[dict[str, Any]] | None:
    """Parse the flat CLI's human-readable search output into rows.

    Returns None when the output does not look like the flat format, so the
    caller can raise EngramMalformedOutput for genuinely unknown output.
    """
    if _EMPTY.match(stdout):
        return []
    if not _FOUND.match(stdout):
        return None
    rows, current, content = [], None, []
    for line in stdout.splitlines():
        header = _FLAT_HEADER.match(line)
        if header:
            if current is not None:
                rows.append(_flat_row(current, content))
            current = {"id": int(header.group(1)), "title": header.group(3),
                       "type": header.group(2)}
            content = []
        elif current is not None:
            if _FLAT_FOOTER.match(line):
                rows.append(_flat_row(current, content))
                current = None
            else:
                content.append(line)
    if current is not None:
        rows.append(_flat_row(current, content))
    return rows


def _parse_json_search(data: Any, limit: int) -> list[dict[str, Any]]:
    """Validate and parse the structured search response."""
    if not isinstance(data, dict) or "result" not in data:
        raise EngramMalformedOutput("engram returned invalid search output")

    raw = data["result"]
    if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
        raise EngramMalformedOutput("engram returned invalid search output")

    reported = data.get("total")
    if reported is not None and (isinstance(reported, bool) or
                                 not isinstance(reported, int) or reported < 0):
        raise EngramMalformedOutput("engram returned invalid search output")
    if isinstance(reported, int) and reported > len(raw):
        raise EngramSearchTruncated("engram search returned incomplete results")
    if len(raw) >= limit and reported is None:
        raise EngramSearchTruncated("engram search reached its explicit safety limit")
    return raw


def _reported_count(stdout: str) -> int | None:
    match = re.search(r"^Found (\d+) memories?:", stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def _flat_row(meta: dict[str, Any], content: list[str]) -> dict[str, Any]:
    if content and content[0].startswith("    "):
        content[0] = content[0][4:]
    row: dict[str, Any] = {"id": meta["id"], "title": meta["title"],
                           "content": "\n".join(content).rstrip()}
    if meta["type"]:
        row["type"] = meta["type"]
    return row
