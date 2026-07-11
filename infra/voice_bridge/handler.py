"""The one Lambda behind the WebSocket API — router and session holder in one.

API Gateway WebSocket integrations are per-*message* invocations: the Lambda
that handles ``$connect`` is not a long-lived process holding the socket. So
the same function runs in two modes (the one-arm64-Lambda design the template
documents):

- **router mode** — invoked by API Gateway per WebSocket event. ``$connect``
  is the approval gate: verify the learn-api-minted voice token FIRST, check
  the concurrency cap, register the session, then async-self-invoke the
  session holder. ``$default`` stores inbound audio frames for the holder;
  ``$disconnect`` cleans up.
- **session mode** — the async self-invocation. Only THIS path ever opens a
  Bedrock connection (relay.open_stream), and it is only reachable after a
  token verified — h7's groundwork is structural, not a scattered check.

Every dependency is injected through ``Deps`` so the gate logic runs under
pytest with zero AWS; ``_default_deps`` builds the boto3-backed production
set lazily on first real invocation.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from . import config, tokens

# One year of TTL grace past the session deadline would hide leaks; one hour
# keeps ghost rows (a crashed holder that never cleaned up) from pinning the
# concurrency cap for longer than an operator would notice.
_TTL_GRACE_SECONDS = 3600


class SessionStore(Protocol):
    """What the handler needs from the voice-sessions table."""

    def count_active(self, now: int) -> int: ...  # noqa: E704

    def put_session(self, connection_id: str, record: dict) -> None: ...  # noqa: E704

    def get_session(self, connection_id: str) -> dict | None: ...  # noqa: E704

    def delete_session(self, connection_id: str) -> None: ...  # noqa: E704

    def store_frame(self, connection_id: str, body: str) -> None: ...  # noqa: E704


@dataclass
class Deps:
    """Injected seams; production values come from ``_default_deps``."""

    secret: str
    max_concurrent: int
    max_session_seconds: int
    sessions: SessionStore
    launch_session: Callable[[dict], Any]
    run_session: Callable[[dict], dict]
    now: Callable[[], int]


def lambda_handler(event: dict, context: Any = None, deps: Deps | None = None) -> dict:
    deps = deps or _default_deps()
    if isinstance(event, dict) and event.get("voiceBridge") == "session":
        return deps.run_session(event)
    request = event.get("requestContext") or {}
    route = request.get("routeKey")
    connection_id = request.get("connectionId", "")
    if route == "$connect":
        return _connect(event, connection_id, deps)
    if route == "$default":
        return _frame(event, connection_id, deps)
    if route == "$disconnect":
        deps.sessions.delete_session(connection_id)
        return {"statusCode": 200}
    return {"statusCode": 400}


def _connect(event: dict, connection_id: str, deps: Deps) -> dict:
    """The bridge entry — h7's gate. Order matters: verify before anything else."""
    token = (event.get("queryStringParameters") or {}).get("token")
    claims = tokens.verify_voice_token(deps.secret, token, now=deps.now())
    if claims is None:
        # No valid approved token -> refuse the upgrade. Nothing was written,
        # nothing was launched, and the Bedrock-opening path (session mode)
        # is unreachable from here.
        return {"statusCode": 401}
    now = deps.now()
    if deps.sessions.count_active(now) >= deps.max_concurrent:
        # Over-cap is a refusal, never degraded service (league's posture).
        return {"statusCode": 429}
    deadline = now + deps.max_session_seconds
    deps.sessions.put_session(
        connection_id,
        {"uid": claims["uid"], "connected_at": now, "deadline": deadline},
    )
    deps.launch_session(
        {
            "voiceBridge": "session",
            "connectionId": connection_id,
            "uid": claims["uid"],
            "deadline": deadline,
        }
    )
    return {"statusCode": 200}


def _frame(event: dict, connection_id: str, deps: Deps) -> dict:
    """Inbound audio frame: forwarded only for a connection that passed the gate."""
    if deps.sessions.get_session(connection_id) is None:
        return {"statusCode": 403}
    deps.sessions.store_frame(connection_id, event.get("body") or "")
    return {"statusCode": 200}


# --- production wiring (boto3; built lazily, unused under pytest) -----------


class DynamoSessionStore:
    """Sessions + inbound frames in the one PAY_PER_REQUEST table.

    Item shapes: ``PK=SESSION#<connection>``, ``SK=METADATA`` for the session
    row; ``SK=FRAME#<arrival-ms>#<nonce>`` for inbound audio frames (ordering
    is client-``seq`` authoritative — see relay.order_frames; the SK only
    approximates arrival). Every item carries an ``expires_at`` TTL so a
    crashed session leaves nothing behind and storage cost stays ~zero.
    """

    def __init__(self, table: Any):
        self._table = table

    def count_active(self, now: int) -> int:
        # A Scan is O(table), which is fine *because* the concurrency cap
        # keeps this table at a handful of rows by construction; a GSI would
        # be added capacity for no measurable gain at cap=2.
        result = self._table.scan(
            Select="COUNT",
            FilterExpression="SK = :meta AND expires_at > :now",
            ExpressionAttributeValues={":meta": "METADATA", ":now": now},
        )
        return int(result.get("Count", 0))

    def put_session(self, connection_id: str, record: dict) -> None:
        item = {
            "PK": f"SESSION#{connection_id}",
            "SK": "METADATA",
            "expires_at": record["deadline"] + _TTL_GRACE_SECONDS,
            **record,
        }
        self._table.put_item(Item=item)

    def get_session(self, connection_id: str) -> dict | None:
        result = self._table.get_item(Key={"PK": f"SESSION#{connection_id}", "SK": "METADATA"})
        return result.get("Item")

    def delete_session(self, connection_id: str) -> None:
        self._table.delete_item(Key={"PK": f"SESSION#{connection_id}", "SK": "METADATA"})

    def store_frame(self, connection_id: str, body: str) -> None:
        self._table.put_item(
            Item={
                "PK": f"SESSION#{connection_id}",
                "SK": f"FRAME#{int(time.time() * 1000):013d}#{uuid.uuid4().hex[:8]}",
                "body": body,
                "expires_at": int(time.time()) + 120,  # audio staler than 2min is useless
            }
        )

    def consume_frames(self, connection_id: str) -> list[str]:
        """Read-and-delete pending frames (the session holder's inbound poll)."""
        result = self._table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"SESSION#{connection_id}",
                ":prefix": "FRAME#",
            },
            ConsistentRead=True,
        )
        items = result.get("Items", [])
        for item in items:
            self._table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        return [item.get("body", "") for item in items]


def _store():
    import boto3

    table = boto3.resource("dynamodb").Table(os.environ[config.SESSIONS_TABLE_ENV])
    return DynamoSessionStore(table)


def _launch_session(payload: dict) -> None:
    """Fire-and-forget self-invoke: the holder outlives this router invocation."""
    import boto3

    boto3.client("lambda").invoke(
        FunctionName=os.environ[config.SELF_FUNCTION_NAME_ENV],
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def _run_session(payload: dict) -> dict:
    """Session-holder mode: hold the Bedrock stream, pump both directions."""
    import asyncio

    import boto3

    from . import relay

    connection_id = payload["connectionId"]
    store = _store()
    gateway = boto3.client(
        "apigatewaymanagementapi", endpoint_url=os.environ[config.CALLBACK_URL_ENV]
    )

    async def _session() -> dict:
        bedrock = await relay.open_stream(
            os.environ.get(config.MODEL_ID_ENV, config.NOVA_SONIC_MODEL_ID),
            os.environ.get("AWS_REGION", "us-east-1"),
        )

        async def next_frames() -> list[str]:
            return relay.order_frames(store.consume_frames(connection_id))

        def send_downstream(message: dict) -> None:
            gateway.post_to_connection(
                ConnectionId=connection_id, Data=json.dumps(message).encode("utf-8")
            )

        return await relay.pump(
            bedrock,
            next_frames,
            send_downstream,
            now=lambda: int(time.time()),
            deadline=int(payload["deadline"]),
            prompt_name=f"learn-voice-{connection_id}",
            system_prompt=(
                "You are the learn platform's voice tutor. Be brief, warm, and "
                "correct the learner gently."
            ),
        )

    try:
        summary = asyncio.run(_session())
    finally:
        store.delete_session(connection_id)
        try:
            gateway.delete_connection(ConnectionId=connection_id)
        except Exception:  # noqa: BLE001 - client may already be gone; that's fine
            pass
    return summary


def _default_deps() -> Deps:
    return Deps(
        secret=os.environ.get(config.VOICE_TOKEN_SECRET_ENV, ""),
        max_concurrent=int(
            os.environ.get(
                config.MAX_CONCURRENT_SESSIONS_ENV,
                config.DEFAULT_MAX_CONCURRENT_VOICE_SESSIONS,
            )
        ),
        max_session_seconds=int(
            os.environ.get(config.MAX_SESSION_SECONDS_ENV, config.DEFAULT_MAX_SESSION_SECONDS)
        ),
        sessions=_store(),
        launch_session=_launch_session,
        run_session=_run_session,
        now=lambda: int(time.time()),
    )
