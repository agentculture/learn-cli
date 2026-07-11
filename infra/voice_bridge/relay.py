"""The bidirectional pump: learner audio up to Nova Sonic 2, model audio back.

This is the code path the spike proved live end-to-end (infra/SPIKE.md): a
plain Python 3.12 process holding Bedrock's InvokeModelWithBidirectionalStream
over HTTP/2 via the experimental ``aws_sdk_bedrock_runtime`` SDK, real speech
in, recognized transcript + spoken answer back.

``pump`` is written against three injected seams so the whole loop runs under
pytest with zero AWS:

- a *bedrock* object (``send_event``/``receive_event``/``close``),
- ``next_frames`` — an async callable draining inbound base64 audio chunks
  (production: the DynamoDB frame rows the $default route wrote),
- ``send_downstream`` — a callable receiving ``{"kind", "content"}`` dicts
  (production: PostToConnection back through the WebSocket).

``open_stream`` is the only untested seam: a direct transcription of the
working spike script, including the two traps it found (the credentials
resolver MUST be set explicitly or the SDK's auth failure is swallowed into a
forever-pending await; ``EnvironmentCredentialsResolver`` is exactly how a
Lambda execution role's credentials surface).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

# 16 kHz, 16-bit mono LPCM in; 24 kHz out — the exact shapes the spike used.
AUDIO_INPUT_CONFIGURATION = {
    "mediaType": "audio/lpcm",
    "sampleRateHertz": 16000,
    "sampleSizeBits": 16,
    "channelCount": 1,
    "audioType": "SPEECH",
    "encoding": "base64",
}
AUDIO_OUTPUT_CONFIGURATION = {
    "mediaType": "audio/lpcm",
    "sampleRateHertz": 24000,
    "sampleSizeBits": 16,
    "channelCount": 1,
    "voiceId": "matthew",
    "encoding": "base64",
    "audioType": "SPEECH",
}
AUDIO_CONTENT_NAME = "learner-audio"


def setup_events(prompt_name: str, *, system_prompt: str) -> list[dict]:
    """The session-opening event sequence, exactly as the spike sent it."""
    return [
        {
            "event": {
                "sessionStart": {
                    "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7}
                }
            }
        },
        {
            "event": {
                "promptStart": {
                    "promptName": prompt_name,
                    "textOutputConfiguration": {"mediaType": "text/plain"},
                    "audioOutputConfiguration": AUDIO_OUTPUT_CONFIGURATION,
                }
            }
        },
        {
            "event": {
                "contentStart": {
                    "promptName": prompt_name,
                    "contentName": "system",
                    "type": "TEXT",
                    "interactive": True,
                    "role": "SYSTEM",
                    "textInputConfiguration": {"mediaType": "text/plain"},
                }
            }
        },
        {
            "event": {
                "textInput": {
                    "promptName": prompt_name,
                    "contentName": "system",
                    "content": system_prompt,
                }
            }
        },
        {"event": {"contentEnd": {"promptName": prompt_name, "contentName": "system"}}},
        {
            "event": {
                "contentStart": {
                    "promptName": prompt_name,
                    "contentName": AUDIO_CONTENT_NAME,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": AUDIO_INPUT_CONFIGURATION,
                }
            }
        },
    ]


def audio_input_event(prompt_name: str, b64: str) -> dict:
    return {
        "event": {
            "audioInput": {
                "promptName": prompt_name,
                "contentName": AUDIO_CONTENT_NAME,
                "content": b64,
            }
        }
    }


def order_frames(bodies: list[str]) -> list[str]:
    """Order inbound WS frame bodies by their client-assigned ``seq``.

    $default invocations can land concurrently, so arrival order is only
    approximate — the browser numbers each frame (``{"seq": n, "audio":
    base64}``) and this puts them back in order. Malformed bodies are dropped,
    never fatal: one bad frame must not kill a live conversation.
    """
    parsed: list[tuple[int, str]] = []
    for body in bodies:
        try:
            frame = json.loads(body)
            parsed.append((int(frame["seq"]), str(frame["audio"])))
        except (ValueError, KeyError, TypeError):
            continue
    return [audio for _seq, audio in sorted(parsed)]


async def pump(
    bedrock: Any,
    next_frames: Callable[[], Awaitable[list[str]]],
    send_downstream: Callable[[dict], Any],
    *,
    now: Callable[[], int],
    deadline: int,
    prompt_name: str,
    system_prompt: str,
    idle_sleep: float = 0.05,
) -> dict:
    """Relay until the deadline, the stream closing, or the caller's cancel.

    The deadline is the per-session cap (MaxSessionSeconds, enforced again by
    the Lambda timeout as a backstop) — the session ends *by construction*,
    it does not rely on the client hanging up.
    """
    for event in setup_events(prompt_name, system_prompt=system_prompt):
        await bedrock.send_event(event)

    queue: asyncio.Queue = asyncio.Queue()

    async def _receiver() -> None:
        while True:
            event = await bedrock.receive_event()
            await queue.put(event)
            if event is None:
                return

    receiver = asyncio.create_task(_receiver())
    frames_sent = 0
    events_received = 0
    ended = "deadline"
    try:
        while True:
            if now() >= deadline:
                ended = "deadline"
                break
            for b64 in await next_frames():
                await bedrock.send_event(audio_input_event(prompt_name, b64))
                frames_sent += 1
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=idle_sleep if idle_sleep > 0 else 0.01
                )
            except asyncio.TimeoutError:
                continue
            if event is None:
                ended = "stream-closed"
                break
            events_received += 1
            body = event.get("event", {})
            name = next(iter(body), "")
            if name == "audioOutput":
                send_downstream(
                    {"kind": "audio", "content": body["audioOutput"].get("content", "")}
                )
            elif name == "textOutput":
                send_downstream({"kind": "text", "content": body["textOutput"].get("content", "")})
    finally:
        receiver.cancel()
        try:
            await bedrock.send_event({"event": {"promptEnd": {"promptName": prompt_name}}})
            await bedrock.send_event({"event": {"sessionEnd": {}}})
        except Exception:  # noqa: BLE001 - a closed stream must not mask the summary
            pass
        await bedrock.close()
    return {"ended": ended, "frames_sent": frames_sent, "events_received": events_received}


class BedrockStream:
    """Thin adapter from the experimental SDK's stream to pump's three seams."""

    def __init__(self, stream: Any, receiver: Any):
        self._stream = stream
        self._receiver = receiver

    async def send_event(self, payload: dict) -> None:
        from aws_sdk_bedrock_runtime.models import (
            BidirectionalInputPayloadPart,
            InvokeModelWithBidirectionalStreamInputChunk,
        )

        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=json.dumps(payload).encode("utf-8"))
        )
        await self._stream.input_stream.send(chunk)

    async def receive_event(self):
        result = await self._receiver.receive()
        if result is None:
            return None
        part = getattr(result, "value", None)
        raw = getattr(part, "bytes_", None) if part else None
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    async def close(self) -> None:
        await self._stream.input_stream.close()


async def open_stream(model_id: str, region: str) -> BedrockStream:
    """Open the live bidirectional stream — the spike script, verbatim.

    Lazy imports: the experimental SDK exists only in the deployed Lambda
    bundle (infra/voice_bridge/requirements.txt), never in learn-cli's venv.
    """
    from aws_sdk_bedrock_runtime.client import (
        BedrockRuntimeClient,
        InvokeModelWithBidirectionalStreamOperationInput,
    )
    from aws_sdk_bedrock_runtime.config import Config
    from smithy_aws_core.identity import EnvironmentCredentialsResolver

    config = Config(
        endpoint_uri=f"https://bedrock-runtime.{region}.amazonaws.com",
        region=region,
        # Spike finding: omit this and the SDK swallows its auth error into a
        # never-resolving await. The env resolver reads the standard AWS_*
        # variables — exactly how the Lambda execution role's SigV4
        # credentials arrive (API keys are NOT accepted by this operation).
        aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
    )
    client = BedrockRuntimeClient(config=config)
    stream = await client.invoke_model_with_bidirectional_stream(
        InvokeModelWithBidirectionalStreamOperationInput(model_id=model_id)
    )
    output = await stream.await_output()
    return BedrockStream(stream, output[1])
