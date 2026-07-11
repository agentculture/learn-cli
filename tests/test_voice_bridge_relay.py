"""Tests for ``infra/voice_bridge/relay.py`` — the bidirectional pump, on fakes.

The pump is the code the spike proved live (see infra/SPIKE.md): Nova Sonic 2's
event protocol over InvokeModelWithBidirectionalStream. Here it runs against
injected fakes — the SDK wiring (``open_stream``) is the only untested seam,
and it is a direct transcription of the working spike script.
"""

from __future__ import annotations

import asyncio
import json

from voice_bridge import relay

NOW = 1_800_000_000


def run(coro):
    return asyncio.run(coro)


class FakeBedrock:
    """Duck-typed stand-in for the opened bidirectional stream seams."""

    def __init__(self, responses):
        self.sent: list[dict] = []
        self.responses = list(responses)
        self.closed = False

    async def send_event(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive_event(self):
        if self.responses:
            return self.responses.pop(0)
        await asyncio.sleep(3600)  # simulate an idle stream: nothing more to say

    async def close(self) -> None:
        self.closed = True


def audio_output_event(b64: str) -> dict:
    return {"event": {"audioOutput": {"content": b64}}}


def test_setup_events_carry_the_session_prompt_and_audio_config() -> None:
    events = relay.setup_events("prompt-1", system_prompt="Be terse.")
    names = [next(iter(event["event"])) for event in events]
    assert names == [
        "sessionStart",
        "promptStart",
        "contentStart",
        "textInput",
        "contentEnd",
        "contentStart",
    ]
    audio_start = events[5]["event"]["contentStart"]
    assert audio_start["type"] == "AUDIO"
    assert audio_start["audioInputConfiguration"]["sampleRateHertz"] == 16000


def test_pump_relays_frames_up_and_audio_down_until_deadline() -> None:
    bedrock = FakeBedrock([audio_output_event("UExDTQ==")])
    frames = [["QUJD", "REVG"], []]
    downstream: list[dict] = []

    async def next_frames():
        return frames.pop(0) if frames else []

    clock = iter([NOW, NOW, NOW + 1, NOW + 400, NOW + 400, NOW + 400])
    summary = run(
        relay.pump(
            bedrock,
            next_frames,
            downstream.append,
            now=lambda: next(clock),
            deadline=NOW + 300,
            prompt_name="prompt-1",
            system_prompt="Be terse.",
            idle_sleep=0,
        )
    )
    sent_names = [next(iter(event["event"])) for event in bedrock.sent]
    assert sent_names.count("audioInput") == 2
    audio_in = [e["event"]["audioInput"] for e in bedrock.sent if "audioInput" in e["event"]]
    assert [chunk["content"] for chunk in audio_in] == ["QUJD", "REVG"]
    assert sent_names[-2:] == ["promptEnd", "sessionEnd"]
    assert bedrock.closed is True
    assert summary["ended"] == "deadline"
    assert summary["frames_sent"] == 2
    assert downstream == [{"kind": "audio", "content": "UExDTQ=="}]


def test_pump_stops_when_the_stream_closes() -> None:
    bedrock = FakeBedrock([None])

    async def no_frames():
        return []

    summary = run(
        relay.pump(
            bedrock,
            no_frames,
            lambda _e: None,
            now=lambda: NOW,
            deadline=NOW + 300,
            prompt_name="p",
            system_prompt="s",
            idle_sleep=0,
        )
    )
    assert summary["ended"] == "stream-closed"
    assert bedrock.closed is True


def test_pump_forwards_text_output_as_transcript_events() -> None:
    bedrock = FakeBedrock(
        [
            {"event": {"textOutput": {"content": "two plus two equals four."}}},
            None,
        ]
    )
    downstream: list[dict] = []

    async def no_frames():
        return []

    run(
        relay.pump(
            bedrock,
            no_frames,
            downstream.append,
            now=lambda: NOW,
            deadline=NOW + 300,
            prompt_name="p",
            system_prompt="s",
            idle_sleep=0,
        )
    )
    assert downstream == [{"kind": "text", "content": "two plus two equals four."}]


def test_frame_bodies_decode_client_seq_ordering() -> None:
    """Inbound WS frame bodies are client-sequenced JSON; the relay orders by seq."""
    bodies = [
        json.dumps({"seq": 2, "audio": "Qg=="}),
        json.dumps({"seq": 1, "audio": "QQ=="}),
    ]
    ordered = relay.order_frames(bodies)
    assert ordered == ["QQ==", "Qg=="]


def test_order_frames_drops_malformed_bodies() -> None:
    ordered = relay.order_frames(["not-json", json.dumps({"seq": 1, "audio": "QQ=="}), "{}"])
    assert ordered == ["QQ=="]
