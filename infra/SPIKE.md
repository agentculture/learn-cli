# Voice-bridge spike: Lambda ↔ Bedrock Nova Sonic 2 bidirectional stream

Task t4 of the consent-tutoring plan (spec claims c15/h7 groundwork, hosting
decision c27; plan risks r1/r3). Ran 2026-07-11 against live AWS, us-east-1,
**read-only API probing only** — nothing deployed, nothing created. No
credential value appears in this document; probes below show the secret as
`${AWS_BEDROCK_API_KEY_SECRET}` (the env var name from `.env`), and the
SigV4 probes used locally configured AWS credentials.

## Verdict

| Path | Auth | Verdict | Evidence |
| --- | --- | --- | --- |
| `InvokeModelWithBidirectionalStream` (Nova Sonic 2, voice) | Bedrock API key (Bearer) | **NO-GO** | HTTP 403 `{"Message":"This operation does not support API Keys"}` — the service rejects the operation for API keys outright |
| `InvokeModelWithBidirectionalStream` (Nova Sonic 2, voice) | SigV4 (role/env credentials) | **GO** | Full audio round trip from a plain Python 3.12 process: real speech in, transcript + spoken answer streamed back on the same HTTP/2 connection |
| `/openai/v1/chat/completions` (Nova Pro, text) | Bedrock API key (Bearer) | **NO-GO (today, us-east-1)** | Auth passes, but both `amazon.nova-pro-v1:0` and `us.amazon.nova-pro-v1:0` return 404 `model_not_found` — the OpenAI-compat surface does not serve Nova models here |
| `/model/us.amazon.nova-pro-v1%3A0/converse` (Nova Pro, text) | Bedrock API key (Bearer) | **GO** | HTTP 200, completion `"Pong."`, `usage: {inputTokens: 8, outputTokens: 3}` |

**Production shape (recommended, and what `infra/template.yaml` builds):**
the voice bridge authenticates to Bedrock with its **Lambda execution role
(SigV4)** — the API-key NO-GO costs nothing, because the role is the natural
serverless credential anyway. The Bedrock API key stays useful for the text
path (t15), **but t15's spec assumption needs a correction**: point
`INFERENCE_URL` at the native `/converse` endpoint (or keep the broker
OpenAI-shaped and translate), not at `/openai/v1/chat/completions`, which
does not serve Nova Pro in us-east-1 today.

## What was actually observed

All runtime probes hit `https://bedrock-runtime.us-east-1.amazonaws.com`
(Nova home region — first and only region tried; every question answered
there). Every probe negotiated **HTTP/2** (curl `--write-out '%{http_version}'`
reported `2`), which the bidirectional protocol requires.

### 1. Bearer key against the bidirectional operation — definitive NO-GO

```console
$ curl --http2 -X POST \
    -H "Authorization: Bearer ${AWS_BEDROCK_API_KEY_SECRET}" \
    -H "Content-Type: application/vnd.amazon.eventstream" \
    https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.nova-2-sonic-v1:0/invoke-with-bidirectional-stream
HTTP 403 via HTTP/2
{"Message":"This operation does not support API Keys"}
```

Not a signature or permission failure — the operation itself refuses API-key
auth. This is the clean answer the task anticipated: bidirectional is
SigV4/SDK-only.

### 2. SigV4 + experimental SDK — full audio round trip (GO)

Tooling: `aws_sdk_bedrock_runtime` 0.7.0 (AWS's experimental Smithy Python
SDK — today the only Python client for this operation; boto3 cannot open
bidirectional streams), Python 3.12, awscrt HTTP/2 underneath. Input audio
was real speech synthesized by Polly (`aws polly synthesize-speech
--output-format pcm --sample-rate 16000 --text "What is two plus two?
Answer briefly."`), streamed as base64 `audioInput` events at roughly
real-time pacing, followed by 1 s of silence for end-of-turn detection:

```text
STREAM ESTABLISHED
  <- userSpeechStart: {"inputAudioOffsetMs": 0, ...}
sent 28 audioInput chunks (110782 pcm bytes incl. silence)
  <- completionStart: {...}
  <- userSpeechEnd: {"inputAudioDetectionOffsetMs": 3080, ...}
  <- textOutput: 'what is two plus two? answer briefly.'   # ASR of our audio
  <- textOutput: 'Two plus two equals four.'               # the model's reply
event tally: {'usageEvent': 12, 'userSpeechStart': 1, 'completionStart': 1,
              'userSpeechEnd': 1, 'contentStart': 3, 'textOutput': 2,
              'contentEnd': 3, 'audioOutput': 19}
AUDIO BACK: 19 audioOutput events, 78720 pcm bytes (~1.64s at 24kHz)
VERDICT full-audio-round-trip: GO
```

A plain Python process held the stream, sent audio up, and received the
model's speech back on the same connection — exactly what the Lambda session
holder does. Total spike model spend: a few hundred speech tokens, well under
one cent.

Two SDK traps found (both now encoded in `voice_bridge/relay.open_stream`):

- **`aws_credentials_identity_resolver` must be set explicitly** on the
  `Config`. Passing raw `aws_access_key_id=...` kwargs looks accepted but the
  auth resolver never finds them — and the failure is *swallowed into a
  background task*, so the open call awaits forever instead of raising
  (`SmithyIdentityError` surfaced only via "Task exception was never
  retrieved"). A production timeout around stream-open is mandatory.
- `EnvironmentCredentialsResolver` reads the standard `AWS_*` env vars —
  which is exactly how a Lambda execution role delivers credentials, so the
  spike's auth path and production's are the same code.

### 3. Runtime choice: python3.12 stays (no Node needed)

The task allowed switching the Lambda to Node if the spike proved the relay
needed the JS SDK's bidirectional support. It did not: the experimental
Python SDK held the stream end-to-end. python3.12 matches league's
convention; `awscrt` (the SDK's one native dependency) ships manylinux
aarch64 wheels, so arm64 Lambda packaging is a plain `requirements.txt`
build. The SDK is pre-1.0 and its `Config` API has already changed shape
between published samples — pinned `>=0.7,<1` in `infra/requirements.txt`.

### 4. Bearer key intel for the text path (t15, not this task)

- `GET /openai/v1/models` → 404 `<UnknownOperationException/>` (operation
  not offered in us-east-1).
- `POST /openai/v1/chat/completions` with `amazon.nova-micro-v1:0`, then
  `us.amazon.nova-pro-v1:0` → 404 `model_not_found` both times. The bearer
  key *authenticates* (no 401/403), but the OpenAI-compat surface does not
  serve Nova models in us-east-1 today.
- `POST /model/us.amazon.nova-pro-v1%3A0/converse` with the same bearer key
  → **HTTP 200**, `"Pong."`. The key is live and authorizes Nova Pro on the
  native Converse API.

Also confirmed via `list-foundation-models`: **Nova Sonic 2's model id is
`amazon.nova-2-sonic-v1:0`** (SPEECH,TEXT modalities, us-east-1); v1 remains
available as `amazon.nova-sonic-v1:0`.

## API Gateway WebSocket constraints that shaped the design (risk r3)

- **Per-message invocation model** — the biggest one. An API GW WebSocket
  Lambda integration invokes the function once *per frame*; no invocation
  holds the client socket. So one function runs in two modes
  (`voice_bridge/handler.py`): the router (per-frame, verifies the token at
  `$connect`, buffers inbound audio in DynamoDB) async-self-invokes the same
  function as a session holder, which owns the Bedrock stream and pushes
  audio back via the `@connections` PostToConnection API.
- **32 KB max frame** — audio chunks are ~4 KB of PCM (~5.5 KB base64), an
  8x margin. Client frames carry `{"seq": n, "audio": base64}`; `$default`
  invocations can land out of order, so ordering is client-`seq`
  authoritative (`relay.order_frames`).
- **10 min idle timeout / 2 h connection cap** — both far above the 300 s
  `MaxSessionSeconds` cap, so the session budget, not the transport, ends
  every session.
- **Lambda 15 min max runtime** — the absolute ceiling on any one-holder
  session design; the 300 s cap + 360 s function timeout sit comfortably
  inside it.

## Cost observations feeding the template comments

- Spike-measured: ~150 speech tokens for ~3.5 s of input audio → **~43
  speech tokens/second**. At published Nova Sonic rates (~$0.0034/1k in,
  ~$0.0136/1k out) that is **~1–2 cents per conversation-minute combined** —
  the dominant cost line by ~5x over all plumbing together.
- A 300 s max session ≈ $0.10 of model tokens + ~$0.02 of plumbing (DynamoDB
  frame writes ~$0.018, Lambda ~$0.002, API GW messages ~$0.005).
- The $20 ceiling therefore affords ~200 max-length sessions/month;
  2 concurrent sessions bound saturated abuse to ~$2.4/hour, inside what the
  Budgets forecast alarm catches same-day. Rotating `VoiceTokenSecretValue`
  is the instant kill switch.

## Open questions handed to t16

1. **Minting**: learn-api mints the voice token (session.js-symmetric HMAC
   format, `scope: "voice"`, `approved: true`, short TTL — see
   `voice_bridge/tokens.py` and its tests for the exact contract) only for
   admin-approved learners, and passes it as `?token=` on the wss URL.
2. **Client audio**: 16 kHz/16-bit/mono LPCM up (base64, client-sequenced
   frames), 24 kHz LPCM down — the shapes `relay.py` pins.
3. **Per-learner budget**: the bridge caps per-session seconds and global
   concurrency; a per-learner monthly allowance (t16's server-side cap)
   belongs in learn-api where approval lives.
4. **Deploy** happens later under supervision (`sam build && sam deploy`
   with `BudgetAlertEmail` supplied); nothing was deployed in this task.
