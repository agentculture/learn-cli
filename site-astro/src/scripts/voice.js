// voice.js — the voice-session page (t16; spec c15/h7). Loaded ONLY on
// src/pages/voice/index.astro's own <script> block — like consent.js, this is
// NOT imported by Layout.astro, so no other page pays for it, and it is a
// third separately-audited fetch surface: scripts/check-static-auth.mjs
// parses this exact file and asserts its only fetch() targets are
// ${API_BASE}/me and ${API_BASE}/voice/token — nothing wider (no /progress,
// /record, /admin, and never the inference-spending broker route this site
// calls nowhere at all).
//
// h7, the client half: the ONLY WebSocket this file can open is created by
// the openBridgeSocket seam, whose ONLY call site sits inside startSession
// strictly AFTER the POST /api/voice/token mint returned ok — every non-ok
// mint (401 signed-out, 403 consent/approval, 429 budget, 503 unconfigured)
// returns before the socket line is reachable. No token, no WebSocket, no
// audio byte toward the bridge. The server enforces the same gate
// independently at BOTH ends (the Worker refuses to mint below "approved";
// the bridge's $connect refuses an unverified token) — this file's ordering
// is UX honesty, not the security boundary. check-static-auth.mjs and
// tests/test_voice_page.py both assert this structure statically.
//
// Audio contract (t4's spike-proven shapes, infra/voice_bridge/relay.py):
//   upstream    16 kHz / 16-bit / mono LPCM, base64, client-sequenced frames
//               {"seq": n, "audio": "<b64>"} — seq is ordering-authoritative
//               (API GW $default invocations can land out of order);
//   downstream  24 kHz LPCM in {"kind": "audio", "content": "<b64>"} frames,
//               plus {"kind": "text", ...} transcript lines.
//
// Gate states (driven by toggling `hidden` on [data-state] blocks under
// [data-voice-root], same technique as consent.js):
//   signed-out     — default, visible with no JS at all: the sign-in link.
//   consent-needed — signed in, but consent is pending or stale (t6).
//   not-approved   — consented, but the admin hasn't granted the tier (t9).
//   ready          — approved: the mic UI (start/stop, timer, limits,
//                    transcript, status).
//   error          — an unexpected failure; never a silent dead page.

import { API_BASE } from "../lib/api.js";

// t4's client audio contract — see infra/voice_bridge/relay.py's
// AUDIO_INPUT_CONFIGURATION / AUDIO_OUTPUT_CONFIGURATION.
const UPSTREAM_SAMPLE_RATE = 16000;
const DOWNSTREAM_SAMPLE_RATE = 24000;
// 4096 samples per capture callback, downsampled ~3x from the hardware rate:
// ~1365 samples ≈ 2.7 KB PCM ≈ 3.6 KB base64 per frame — comfortably inside
// API Gateway's 32 KB frame limit (the spike's own margin).
const CAPTURE_BUFFER_SAMPLES = 4096;
// The bridge (or a future revision of it) refuses a bad/expired token with a
// 4001 close; a refused $connect usually surfaces as 1006 before open.
const WS_CLOSE_UNAUTHORIZED = 4001;

const root = document.querySelector("[data-voice-root]");

function showState(name) {
  if (!root) return;
  root.querySelectorAll("[data-state]").forEach((el) => {
    el.hidden = el.getAttribute("data-state") !== name;
  });
}

function setField(selector, text) {
  if (!root) return;
  const el = root.querySelector(selector);
  if (el) el.textContent = text;
}

function setStatus(text) {
  setField("[data-voice-status]", text || "");
}

function appendTranscript(text) {
  if (!root || !text) return;
  const box = root.querySelector("[data-voice-transcript]");
  if (!box) return;
  const line = document.createElement("p");
  line.textContent = text;
  box.appendChild(line);
  box.hidden = false;
  box.scrollTop = box.scrollHeight;
}

// --- LPCM16 encode/decode ---------------------------------------------------

/** Float32 [-1, 1] -> 16-bit signed LPCM. */
function floatToPcm16(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

/** Naive decimation to the upstream rate — adequate for speech-band input. */
function downsampleTo(float32, fromRate, toRate) {
  if (fromRate === toRate) return float32;
  const ratio = fromRate / toRate;
  const length = Math.floor(float32.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    out[i] = float32[Math.floor(i * ratio)];
  }
  return out;
}

function pcm16ToB64(int16) {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

/** base64 16-bit LPCM -> Float32 [-1, 1] for WebAudio playback. */
function b64ToFloat32(b64) {
  const bin = atob(b64);
  const out = new Float32Array(Math.floor(bin.length / 2));
  for (let i = 0; i < out.length; i += 1) {
    let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
    if (v >= 0x8000) v -= 0x10000;
    out[i] = v / 0x8000;
  }
  return out;
}

// --- the one WebSocket seam (h7 client half) ---------------------------------

/**
 * The ONLY place this page constructs a WebSocket. `wssUrl` is always the
 * `wss_url` the Worker returned from POST /api/voice/token (the configured
 * VOICE_BRIDGE_URL plus ?token=); the injectable factory keeps the function
 * pure for tests — no ambient DOM or network is touched deciding WHETHER to
 * connect, only the caller's already-minted grant.
 */
export function openBridgeSocket(wssUrl, socketFactory) {
  const factory = socketFactory || ((url) => new WebSocket(url));
  return factory(wssUrl);
}

// --- session lifecycle --------------------------------------------------------

let active = null; // at most one live session per page

function mintFailureMessage(status, body) {
  const code = body && body.error;
  if (status === 401) return "Your sign-in expired — sign in again to start a voice session.";
  if (code === "consent_required") {
    return "The Terms/Privacy need (re-)accepting before voice sessions — see the consent page.";
  }
  if (code === "approval_required") {
    return "Voice sessions are not enabled for your account — the admin grants the tutoring tier.";
  }
  if (status === 429) {
    return "Your monthly voice allowance is used up — the meter resets next month (UTC).";
  }
  if (status === 503) return "The voice bridge isn't configured yet — check back soon.";
  return "Couldn't start a voice session — please try again.";
}

function renderLimits(limits) {
  if (!limits) return;
  const perSession = Math.round(limits.max_session_seconds / 60);
  const left = Math.max(0, Math.round(limits.monthly_seconds_remaining / 60));
  setField(
    "[data-voice-limits]",
    `Up to ${perSession} min per session · about ${left} min of voice left this month.`,
  );
}

function formatClock(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function setButtons(running) {
  if (!root) return;
  const start = root.querySelector("[data-voice-start]");
  const stop = root.querySelector("[data-voice-stop]");
  if (start) start.disabled = running;
  if (stop) stop.disabled = !running;
}

function stopSession(session, reason) {
  if (!session || session.stopped) return;
  session.stopped = true;
  if (session.timer) clearInterval(session.timer);
  if (session.processor) session.processor.disconnect();
  if (session.source) session.source.disconnect();
  if (session.media) session.media.getTracks().forEach((t) => t.stop());
  if (session.captureCtx && session.captureCtx.state !== "closed") session.captureCtx.close();
  if (session.playbackCtx && session.playbackCtx.state !== "closed") session.playbackCtx.close();
  if (
    session.socket &&
    (session.socket.readyState === WebSocket.OPEN ||
      session.socket.readyState === WebSocket.CONNECTING)
  ) {
    session.socket.close(1000, "client stopped");
  }
  if (active === session) active = null;
  setButtons(false);
  setStatus(reason || "Voice session ended.");
}

/** Mic -> downsample -> LPCM16 -> base64 -> {"seq", "audio"} frames. */
async function startCapture(session) {
  const media = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      sampleRate: UPSTREAM_SAMPLE_RATE, // browsers may ignore; we downsample below
      echoCancellation: true,
      noiseSuppression: true,
    },
  });
  session.media = media;
  const ctx = new AudioContext();
  session.captureCtx = ctx;
  const source = ctx.createMediaStreamSource(media);
  const processor = ctx.createScriptProcessor(CAPTURE_BUFFER_SAMPLES, 1, 1);
  processor.onaudioprocess = (event) => {
    if (session.stopped || session.socket.readyState !== WebSocket.OPEN) return;
    const raw = event.inputBuffer.getChannelData(0);
    const pcm = floatToPcm16(downsampleTo(raw, ctx.sampleRate, UPSTREAM_SAMPLE_RATE));
    session.seq += 1;
    session.socket.send(JSON.stringify({ seq: session.seq, audio: pcm16ToB64(pcm) }));
  };
  source.connect(processor);
  processor.connect(ctx.destination);
  session.source = source;
  session.processor = processor;
}

/** 24 kHz LPCM chunks scheduled back-to-back on a WebAudio cursor. */
function playDownstream(session, float32) {
  if (!float32.length) return;
  if (!session.playbackCtx) session.playbackCtx = new AudioContext();
  const ctx = session.playbackCtx;
  const buffer = ctx.createBuffer(1, float32.length, DOWNSTREAM_SAMPLE_RATE);
  buffer.copyToChannel(float32, 0);
  const node = ctx.createBufferSource();
  node.buffer = buffer;
  node.connect(ctx.destination);
  const at = Math.max(session.playCursor || 0, ctx.currentTime);
  node.start(at);
  session.playCursor = at + buffer.duration;
}

async function startSession() {
  if (active) return;
  setButtons(true);
  setStatus("Requesting a voice session…");

  // TOKEN FIRST (h7): every failure below returns before any WebSocket line
  // is reachable — a learner the Worker refuses can never touch the bridge.
  let res;
  try {
    res = await fetch(`${API_BASE}/voice/token`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    setButtons(false);
    setStatus("Network error — couldn't request a voice session.");
    return;
  }
  let grant = null;
  try {
    grant = await res.json();
  } catch {
    grant = null;
  }
  if (!res.ok || !grant || !grant.token || !grant.wss_url) {
    setButtons(false);
    setStatus(mintFailureMessage(res.status, grant));
    return;
  }

  renderLimits(grant.limits);
  const session = {
    seq: 0,
    stopped: false,
    opened: false,
    startedAt: 0,
    maxSeconds:
      grant.limits && grant.limits.max_session_seconds ? grant.limits.max_session_seconds : 300,
    playCursor: 0,
  };
  active = session;
  setStatus("Connecting to the voice bridge…");
  const socket = openBridgeSocket(grant.wss_url);
  session.socket = socket;

  socket.onopen = async () => {
    session.opened = true;
    session.startedAt = Date.now();
    setStatus("Connected — speak when ready.");
    session.timer = setInterval(() => {
      const elapsed = Math.floor((Date.now() - session.startedAt) / 1000);
      setField("[data-voice-timer]", `${formatClock(elapsed)} / ${formatClock(session.maxSeconds)}`);
      // The bridge enforces this server-side; stopping client-side too keeps
      // the UI honest instead of dying mid-sentence at the server deadline.
      if (elapsed >= session.maxSeconds) stopSession(session, "Session time limit reached.");
    }, 1000);
    try {
      await startCapture(session);
    } catch {
      stopSession(session, "Microphone access was refused — allow the mic and try again.");
    }
  };

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return; // one malformed frame must not kill a live conversation
    }
    if (message.kind === "audio" && message.content) {
      playDownstream(session, b64ToFloat32(message.content));
    } else if (message.kind === "text" && message.content) {
      appendTranscript(message.content);
    }
  };

  socket.onclose = (event) => {
    if (session.stopped) return;
    let why = "The voice session ended.";
    if (event.code === WS_CLOSE_UNAUTHORIZED) {
      why = "The bridge refused the session token (unauthorized) — start again for a fresh one.";
    } else if (!session.opened) {
      why = "Couldn't reach the voice bridge — the token may have expired, or it refused the connection.";
    }
    stopSession(session, why);
  };

  socket.onerror = () => {
    if (!session.stopped && !session.opened) {
      stopSession(session, "Couldn't connect to the voice bridge.");
    }
  };
}

function wireSession() {
  if (!root) return;
  const start = root.querySelector("[data-voice-start]");
  const stop = root.querySelector("[data-voice-stop]");
  if (start) start.addEventListener("click", startSession);
  if (stop) stop.addEventListener("click", () => stopSession(active, "You ended the session."));
  setButtons(false);
}

// --- gate flow ---------------------------------------------------------------

async function bootstrap() {
  let me;
  try {
    const res = await fetch(`${API_BASE}/me`, { credentials: "include" });
    if (res.status === 401) {
      showState("signed-out");
      return;
    }
    if (!res.ok) {
      showState("error");
      return;
    }
    me = await res.json();
  } catch {
    showState("error");
    return;
  }

  if (!me.authenticated) {
    showState("signed-out");
    return;
  }
  if (me.pending_consent || me.reconsent_required) {
    showState("consent-needed");
    return;
  }
  if (!me.learner || me.learner.approved !== true) {
    showState("not-approved");
    return;
  }

  wireSession();
  showState("ready");
}

bootstrap();
