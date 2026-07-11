"""Shared fixtures for the subject-registry and conformance-gate tests.

The fake subject CLIs under ``tests/fixtures/subjects/`` stand in for real
subject console scripts: the conformance gate drives them purely as external
subprocesses over ``--json``. These fixtures make one executable and hand the
tests a helper that installs a temporary registry (via the
``LEARN_SUBJECTS_REGISTRY`` env override) — so a test can register a subject
with zero source changes, exactly as a real subject would register with a data
entry.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

# The voice-bridge Lambda package lives under infra/ (outside the learn/
# package on purpose — see infra/template.yaml), so tests import it by path.
_INFRA_DIR = Path(__file__).resolve().parent.parent / "infra"
if str(_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_INFRA_DIR))

FIXTURE_SUBJECTS = Path(__file__).parent / "fixtures" / "subjects"
CONFORMANT_SCRIPT = FIXTURE_SUBJECTS / "conformant_subject.py"
DRIFTED_SCRIPT = FIXTURE_SUBJECTS / "drifted_subject.py"


def _make_executable(path: Path) -> str:
    """Ensure a fixture script is executable (git may not preserve the bit)."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def entry(
    name: str,
    argv_prefix: list[str],
    *,
    contract_version: str = "1.0",
) -> dict[str, Any]:
    """A registry entry dict with sensible defaults for the metadata fields."""
    return {
        "name": name,
        "display_name": name.replace("-", " ").title(),
        "description": f"Fixture subject {name}.",
        "repo": f"https://github.com/agentculture/{name}-cli",
        "argv_prefix": argv_prefix,
        "contract_version": contract_version,
    }


@pytest.fixture
def conformant_prefix() -> list[str]:
    """argv_prefix that runs the conformant fixture as an executable script."""
    return [_make_executable(CONFORMANT_SCRIPT)]


@pytest.fixture
def drifted_prefix() -> list[str]:
    """argv_prefix that runs the drifted fixture as an executable script."""
    return [_make_executable(DRIFTED_SCRIPT)]


@pytest.fixture
def install_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[list[dict[str, Any]]], Path]:
    """Return a callable that writes a temp registry and activates it via env."""

    def _install(entries: list[dict[str, Any]]) -> Path:
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({"subjects": entries}), encoding="utf-8")
        monkeypatch.setenv("LEARN_SUBJECTS_REGISTRY", os.fspath(path))
        return path

    return _install


# --- profile store + fake learn-api fixtures --------------------------------


@pytest.fixture
def profile_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the cross-subject profile store (ledger/auth/sync) at a temp dir."""
    home = tmp_path / "learn_cli_home"
    monkeypatch.setenv("LEARN_CLI_HOME", os.fspath(home))
    return home


class FakeLearnApi:
    """A minimal threaded ``http.server`` standing in for ``workers/learn-api``.

    Register canned responses per ``(method, path)`` via :meth:`on`, where the
    handler is either a static ``(status, payload)`` tuple or a callable
    ``(body: dict) -> (status, payload)`` for stateful behavior (device-flow
    pending → complete, a sync push that fails partway). Every request is
    recorded in :attr:`requests` so a test can assert exactly what the CLI
    sent — or that it sent nothing at all.
    """

    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], Any] = {}
        self.requests: list[dict[str, Any]] = []
        fake_self = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # silence default stderr logging
                pass

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    body = {}
                fake_self.requests.append(
                    {
                        "method": method,
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": body,
                    }
                )
                handler = fake_self._responses.get((method, self.path))
                if handler is None:
                    status, payload = 404, {"message": f"no fake route for {method} {self.path}"}
                elif callable(handler):
                    status, payload = handler(body)
                else:
                    status, payload = handler
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
                self._handle("GET")

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
                self._handle("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def on(self, method: str, path: str, handler: Any) -> None:
        self._responses[(method, path)] = handler

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch):
    """A running :class:`FakeLearnApi`, wired in via ``LEARN_API_URL``."""
    api = FakeLearnApi()
    monkeypatch.setenv("LEARN_API_URL", api.base_url)
    try:
        yield api
    finally:
        api.close()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Fail loudly on any outbound HTTP call — proves a path never touches the network."""

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network should not be touched on this path")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
