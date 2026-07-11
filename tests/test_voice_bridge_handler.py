"""Tests for ``infra/voice_bridge/handler.py`` — approval enforced at the bridge entry.

Spec honesty condition h7's groundwork, verbatim: *no token, no upstream
Bedrock connection*. Every refusal path below asserts two things — the HTTP
status the WebSocket client sees, and that the injected session launcher (the
only code path that ever opens a Bedrock stream) was never called. All
dependencies are injected fakes; no AWS, no network.
"""

from __future__ import annotations

from voice_bridge import handler, tokens

SECRET = "spike-shared-secret"
NOW = 1_800_000_000


class FakeStore:
    """In-memory stand-in for the DynamoDB voice-sessions table."""

    def __init__(self, active: int = 0):
        self.active = active
        self.sessions: dict[str, dict] = {}
        self.frames: list[tuple[str, str]] = []

    def count_active(self, now: int) -> int:
        return self.active + len(self.sessions)

    def put_session(self, connection_id: str, record: dict) -> None:
        self.sessions[connection_id] = record

    def get_session(self, connection_id: str):
        return self.sessions.get(connection_id)

    def delete_session(self, connection_id: str) -> None:
        self.sessions.pop(connection_id, None)

    def store_frame(self, connection_id: str, body: str) -> None:
        self.frames.append((connection_id, body))


def make_deps(*, secret: str = SECRET, active: int = 0, max_concurrent: int = 2):
    store = FakeStore(active=active)
    launched: list[dict] = []
    ran: list[dict] = []
    deps = handler.Deps(
        secret=secret,
        max_concurrent=max_concurrent,
        max_session_seconds=300,
        sessions=store,
        launch_session=launched.append,
        run_session=lambda payload: ran.append(payload) or {"ok": True},
        now=lambda: NOW,
    )
    return deps, store, launched, ran


def connect_event(token: str | None) -> dict:
    query = {"token": token} if token is not None else None
    return {
        "requestContext": {"routeKey": "$connect", "connectionId": "conn-1"},
        "queryStringParameters": query,
    }


def valid_token() -> str:
    return tokens.mint_voice_token(SECRET, uid="20955789", approved=True, ttl_seconds=120, now=NOW)


def test_connect_without_token_is_refused_with_zero_upstream() -> None:
    deps, store, launched, _ = make_deps()
    response = handler.lambda_handler(connect_event(None), None, deps=deps)
    assert response["statusCode"] == 401
    assert launched == []
    assert store.sessions == {}


def test_connect_with_garbage_token_is_refused_with_zero_upstream() -> None:
    deps, store, launched, _ = make_deps()
    response = handler.lambda_handler(connect_event("not.a.token"), None, deps=deps)
    assert response["statusCode"] == 401
    assert launched == []
    assert store.sessions == {}


def test_connect_with_expired_token_is_refused() -> None:
    expired = tokens.mint_voice_token(SECRET, uid="1", approved=True, ttl_seconds=60, now=NOW - 61)
    deps, _store, launched, _ = make_deps()
    response = handler.lambda_handler(connect_event(expired), None, deps=deps)
    assert response["statusCode"] == 401
    assert launched == []


def test_connect_with_session_scope_token_is_refused() -> None:
    """A learn-api session cookie/token must not open the bridge (no cookie reuse)."""
    session_scoped = tokens.mint_voice_token(
        SECRET, uid="1", approved=True, ttl_seconds=120, now=NOW, scope="session"
    )
    deps, _store, launched, _ = make_deps()
    response = handler.lambda_handler(connect_event(session_scoped), None, deps=deps)
    assert response["statusCode"] == 401
    assert launched == []


def test_connect_with_empty_secret_is_refused_even_with_valid_token() -> None:
    """VoiceTokenSecretValue defaults to '' — the deployed-but-unwired bridge stays shut."""
    deps, _store, launched, _ = make_deps(secret="")
    response = handler.lambda_handler(connect_event(valid_token()), None, deps=deps)
    assert response["statusCode"] == 401
    assert launched == []


def test_connect_over_the_concurrency_cap_is_refused_not_degraded() -> None:
    """League's capacity posture: over-cap is a refusal, never degraded service."""
    deps, _store, launched, _ = make_deps(active=2, max_concurrent=2)
    response = handler.lambda_handler(connect_event(valid_token()), None, deps=deps)
    assert response["statusCode"] == 429
    assert launched == []


def test_connect_with_valid_token_registers_and_launches_the_session() -> None:
    deps, store, launched, _ = make_deps()
    response = handler.lambda_handler(connect_event(valid_token()), None, deps=deps)
    assert response["statusCode"] == 200
    assert "conn-1" in store.sessions
    record = store.sessions["conn-1"]
    assert record["uid"] == "20955789"
    assert record["deadline"] == NOW + 300
    assert len(launched) == 1
    payload = launched[0]
    assert payload["voiceBridge"] == "session"
    assert payload["connectionId"] == "conn-1"
    assert payload["uid"] == "20955789"
    assert payload["deadline"] == NOW + 300


def test_default_route_without_a_registered_session_drops_the_frame() -> None:
    deps, store, launched, _ = make_deps()
    event = {
        "requestContext": {"routeKey": "$default", "connectionId": "conn-9"},
        "body": "frame-bytes",
    }
    response = handler.lambda_handler(event, None, deps=deps)
    assert response["statusCode"] == 403
    assert store.frames == []
    assert launched == []


def test_default_route_stores_frames_for_a_registered_session() -> None:
    deps, store, _launched, _ = make_deps()
    handler.lambda_handler(connect_event(valid_token()), None, deps=deps)
    event = {
        "requestContext": {"routeKey": "$default", "connectionId": "conn-1"},
        "body": '{"seq": 1, "audio": "AAAA"}',
    }
    response = handler.lambda_handler(event, None, deps=deps)
    assert response["statusCode"] == 200
    assert store.frames == [("conn-1", '{"seq": 1, "audio": "AAAA"}')]


def test_disconnect_deletes_the_session() -> None:
    deps, store, _launched, _ = make_deps()
    handler.lambda_handler(connect_event(valid_token()), None, deps=deps)
    event = {"requestContext": {"routeKey": "$disconnect", "connectionId": "conn-1"}}
    response = handler.lambda_handler(event, None, deps=deps)
    assert response["statusCode"] == 200
    assert store.sessions == {}


def test_unknown_route_is_a_client_error() -> None:
    deps, _store, _launched, _ = make_deps()
    event = {"requestContext": {"routeKey": "$weird", "connectionId": "conn-1"}}
    response = handler.lambda_handler(event, None, deps=deps)
    assert response["statusCode"] == 400


def test_session_mode_event_routes_to_the_session_runner() -> None:
    """The async self-invoke payload re-enters the same function in holder mode."""
    deps, _store, launched, ran = make_deps()
    payload = {"voiceBridge": "session", "connectionId": "conn-1", "uid": "1", "deadline": NOW}
    response = handler.lambda_handler(payload, None, deps=deps)
    assert response == {"ok": True}
    assert ran == [payload]
    assert launched == []
