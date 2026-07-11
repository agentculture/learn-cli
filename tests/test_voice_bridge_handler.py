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


# --- DynamoSessionStore: the Query-not-Scan performance fix -----------------
#
# Qodo finding: count_active() used to Scan the whole voice-sessions table,
# and sessions + frames share that table. A Scan reads every item — frames
# included — before filtering, so $connect latency/cost grew with frame
# volume even though the concurrency gate only ever needs the session count.
# The fix stores session-metadata items under a constant partition key
# (PK="ACTIVE") so count_active can Query that one partition instead. The
# fake table below mimics just enough of the boto3 Table-resource surface
# (get_item/put_item/delete_item/query/scan) to prove the new access path
# for real, against DynamoSessionStore itself — not the FakeStore fake the
# rest of this file uses, which never touches boto3-shaped calls.


class FakeDynamoTable:
    """Boto3 Table-resource stand-in — only the calls DynamoSessionStore makes.

    Tracks every scan()/query() call it receives so tests can assert on the
    access *path* (Query on the constant PK, never a table-wide Scan), not
    just the returned count.
    """

    def __init__(self):
        self._items: dict[tuple[str, str], dict] = {}
        self.scan_calls: list[dict] = []
        self.query_calls: list[dict] = []

    def seed(self, item: dict) -> None:
        self._items[(item["PK"], item["SK"])] = item

    def put_item(self, Item: dict) -> None:  # noqa: N803 - boto3's own casing
        self._items[(Item["PK"], Item["SK"])] = Item

    def get_item(self, Key: dict) -> dict:  # noqa: N803
        item = self._items.get((Key["PK"], Key["SK"]))
        return {"Item": item} if item is not None else {}

    def delete_item(self, Key: dict) -> None:  # noqa: N803
        self._items.pop((Key["PK"], Key["SK"]), None)

    def scan(self, **kwargs) -> dict:
        # A real Scan reads every item in the table regardless of partition
        # — record the call (and everything currently stored) so a test can
        # assert this path was never exercised, and the count it *would*
        # have produced, for comparison against the Query path.
        self.scan_calls.append(kwargs)
        return {"Count": len(self._items), "Items": list(self._items.values())}

    def query(self, **kwargs) -> dict:
        self.query_calls.append(kwargs)
        values = kwargs.get("ExpressionAttributeValues", {})
        pk_value = values[":active"]
        now = values[":now"]
        matched = [
            item
            for (pk, _sk), item in self._items.items()
            if pk == pk_value and item.get("expires_at", 0) > now
        ]
        if kwargs.get("Select") == "COUNT":
            return {"Count": len(matched)}
        return {"Items": matched}


def _metadata_item(connection_id: str, expires_at: int) -> dict:
    return {"PK": "ACTIVE", "SK": connection_id, "expires_at": expires_at}


def _frame_item(connection_id: str, seq: int, expires_at: int) -> dict:
    return {
        "PK": f"SESSION#{connection_id}",
        "SK": f"FRAME#{seq:013d}#deadbeef",
        "body": "audio-bytes",
        "expires_at": expires_at,
    }


def test_count_active_queries_the_constant_pk_and_ignores_frame_items() -> None:
    """The Qodo fix: count_active must Query PK=ACTIVE, never Scan the table.

    Seeds three active session-metadata items alongside a thousand frame
    items belonging to those same sessions (the hot path this bug made
    every $connect pay for). The count must equal exactly the metadata
    count, the access path must be a Query keyed on the constant partition,
    and Scan must never be called at all.
    """
    table = FakeDynamoTable()
    store = handler.DynamoSessionStore(table)
    for i in range(3):
        table.seed(_metadata_item(f"conn-{i}", expires_at=NOW + 3600))
    for i in range(1000):
        table.seed(_frame_item(f"conn-{i % 3}", seq=i, expires_at=NOW + 120))

    count = store.count_active(NOW)

    assert count == 3
    assert table.scan_calls == []
    assert len(table.query_calls) == 1
    call = table.query_calls[0]
    assert call["Select"] == "COUNT"
    assert call["ExpressionAttributeValues"][":active"] == "ACTIVE"
    assert "PK" in call["KeyConditionExpression"]
    assert "SK" not in call["KeyConditionExpression"]


def test_count_active_excludes_ttl_expired_metadata() -> None:
    """A crashed session's metadata row must stop pinning the concurrency cap."""
    table = FakeDynamoTable()
    store = handler.DynamoSessionStore(table)
    table.seed(_metadata_item("conn-live", expires_at=NOW + 3600))
    table.seed(_metadata_item("conn-expired", expires_at=NOW - 1))

    assert store.count_active(NOW) == 1


def test_put_get_delete_session_round_trip_under_the_constant_pk() -> None:
    """put_session/get_session/delete_session all key off PK=ACTIVE, SK=connection."""
    table = FakeDynamoTable()
    store = handler.DynamoSessionStore(table)
    store.put_session("conn-1", {"uid": "20955789", "connected_at": NOW, "deadline": NOW + 300})

    stored = table._items[("ACTIVE", "conn-1")]
    assert stored["uid"] == "20955789"
    assert store.get_session("conn-1")["uid"] == "20955789"

    store.delete_session("conn-1")

    assert store.get_session("conn-1") is None
    assert ("ACTIVE", "conn-1") not in table._items


def test_store_frame_keeps_the_per_connection_partition_key() -> None:
    """Frames must stay under PK=SESSION#<connection> — only metadata moved."""
    table = FakeDynamoTable()
    store = handler.DynamoSessionStore(table)

    store.store_frame("conn-1", "audio-bytes")

    ((pk, sk),) = table._items.keys()
    assert pk == "SESSION#conn-1"
    assert sk.startswith("FRAME#")
