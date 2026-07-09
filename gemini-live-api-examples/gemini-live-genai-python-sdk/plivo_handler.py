"""
Plivo Voice <-> Gemini Live bridge.

Handles:
- Plivo bidirectional Audio Streaming WebSocket (mulaw 8kHz)
- Audio conversion: mulaw 8kHz <-> PCM 16kHz (Gemini input) / PCM 24kHz (Gemini output)
- Bridges the two in real-time, with 20ms-paced outbound frames + barge-in (clearAudio)
- Pure Python audio conversion (no audioop, works on Python 3.13+)

Plivo media-stream protocol (JSON text frames):
  inbound  start : {"event":"start","start":{"streamId","callId","mediaFormat":{...}},"extra_headers":"k=v,k=v"}
  inbound  media : {"event":"media","media":{"payload":"<base64 mulaw>","track":"inbound"}}
  inbound  stop  : {"event":"stop", ...}
  outbound play  : {"event":"playAudio","streamId":"<id>","media":{"contentType":"audio/x-mulaw","sampleRate":8000,"payload":"<b64>"}}
  outbound clear : {"event":"clearAudio","streamId":"<id>"}   <- barge-in
Modeled on gvox-voice-proxy/app/plivo_protocol.py.
"""

import asyncio
import array
import base64
import json
import logging
import math
import os
import re
import struct
import time
from urllib.parse import unquote

try:
    from starlette.websockets import WebSocketState
except ImportError:          # pragma: no cover - starlette always ships with FastAPI
    WebSocketState = None

logger = logging.getLogger(__name__)

from gemini_live import _SILENT_SCHEDULING
# On the server (google-genai >= 2.x) record_rsvp is SILENT — its result never forces a turn, so there
# is no "filler" turn to suppress; the only risk is a mute record, which we nudge. On <2.x this is None
# and we keep the blocking-path forced-turn suppression.
_RSVP_SILENT = _SILENT_SCHEDULING is not None

# Mutual-goodbye detection: after the agent's goodbye + end_call, a caller who just
# says "bye / thanks / okay" is WRAPPING UP — we should let the hangup proceed, not
# cancel it and re-engage (which restarts the whole grace cycle and drags the call
# out to 10-16s). A real follow-up (a question / new info) still cancels the hangup.
_QUESTION_RE = re.compile(
    r"[?]|\b(what|whats|when|where|who|whom|which|how|why|can i|could|would you|"
    r"is it|are|do you|does|will|actually|wait|hold on|one (thing|sec|second|"
    r"question|more)|but|sorry|hello|hi)\b", re.I)
_GOODBYE_RE = re.compile(
    r"\b(bye+|goodbye|good ?bye|tata|ta ta|thanks|thank you|thankyou|cheers|"
    r"that'?s all|that is all|nothing else|nothing|i'?m done|we'?re done|see you|"
    r"good ?night|great|perfect|okay bye|ok bye|done)\b", re.I)

# "Hold on / give me a minute" means STAY on THIS call — not a sign-off and not a callback.
# When the caller says one of these we keep the line open for a grace window (see _hold_until).
_HOLD_RE = re.compile(
    r"\b(hold on|hold please|please hold|hang on|bear with me|one moment|just a "
    r"(sec|second|minute|moment)|give me (a|one|two|a couple|a few)|one (sec|second|minute|moment)|"
    r"two (secs|seconds|minutes)|a (minute|moment|sec|second)|wait)\b", re.I)

# Post-goodbye: only a genuine question / new info should re-open the call. A bare "hello", "okay",
# "yeah", "hmm" must NOT re-engage the model (that made it re-read its whole invitation). This is a
# POSITIVE "is there a real follow-up?" test — used only during the pending-hangup grace window.
_REAL_FOLLOWUP_RE = re.compile(
    r"[?]|\b(what|whats|when|where|who|which|how|why|can i|could|would|is it|are you|do you|does|"
    r"will|register|registration|bring|time|venue|address|dress|kids?|child|children|wife|husband|"
    r"family|parents?|mother|father|sister|brother|change|cancel|question|but)\b", re.I)


def _looks_like_goodbye(text: str) -> bool:
    """True only for a short caller sign-off with no real follow-up/question."""
    t = (text or "").strip().lower()
    if not t or _QUESTION_RE.search(t):
        return False
    if len(re.findall(r"[a-z']+", t)) > 7:          # too long to be a simple sign-off
        return False
    return bool(_GOODBYE_RE.search(t))


# Within-turn repeat guard: if the agent repeats itself inside ONE turn (the fusion / spiral
# loop), we stop feeding the duplicate audio. Two paths: (1) a known closing marker voiced twice,
# and (2) a GENERAL verbatim phrase-loop — any run of words repeated in the turn — which catches
# callback/goodbye closings ("I'll give you a call back… speak soon!") the marker list misses.
_CLOSING_MARKERS = (
    "see you on the", "so glad you", "we'll miss you", "we will miss you",
    "drop all the details", "receive all the details", "details on the whatsapp",
    "details on your whatsapp", "on the whatsapp group",
    "anything else i can help", "look forward to seeing you",
)


def _has_closing_repeat(turn_text: str) -> bool:
    t = re.sub(r"[^a-z0-9 ]", " ", (turn_text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    if any(t.count(m) >= 2 for m in _CLOSING_MARKERS):
        return True
    # General loop: any run of 6 consecutive words that appears twice in the same turn = spiralling.
    words = t.split()
    if len(words) < 12:
        return False
    seen = set()
    for i in range(len(words) - 5):
        g = " ".join(words[i:i + 6])
        if g in seen:
            return True
        seen.add(g)
    return False

# ===== Mulaw codec tables (ITU-T G.711) =====

# Mulaw -> Linear PCM16 decode table (256 entries)
_MULAW_DECODE = array.array("h")  # signed short
for _i in range(256):
    _v = ~_i
    _sign = _v & 0x80
    _exponent = (_v >> 4) & 0x07
    _mantissa = _v & 0x0F
    _sample = ((_mantissa << 3) + 0x84) << _exponent
    _sample -= 0x84
    if _sign:
        _sample = -_sample
    _MULAW_DECODE.append(max(-32768, min(32767, _sample)))

# Linear PCM16 -> Mulaw encode
_MULAW_BIAS = 0x84
_MULAW_CLIP = 32635
_MULAW_EXP_TABLE = [0, 0, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3,
                     4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
                     5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
                     5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
                     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
                     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
                     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
                     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
                     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7]


def _pcm16_to_mulaw_sample(sample: int) -> int:
    """Encode one PCM16 sample to mulaw byte."""
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample
    if sample > _MULAW_CLIP:
        sample = _MULAW_CLIP
    sample += _MULAW_BIAS
    exponent = _MULAW_EXP_TABLE[(sample >> 7) & 0xFF]
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


# ===== Audio conversion functions =====

def mulaw_to_pcm16k(mulaw_bytes: bytes) -> bytes:
    """Convert mulaw 8kHz (Plivo) -> PCM 16-bit 16kHz (Gemini input)."""
    samples_8k = [_MULAW_DECODE[b] for b in mulaw_bytes]
    # Upsample 8kHz -> 16kHz by linear interpolation
    samples_16k = []
    for i in range(len(samples_8k)):
        samples_16k.append(samples_8k[i])
        if i + 1 < len(samples_8k):
            samples_16k.append((samples_8k[i] + samples_8k[i + 1]) >> 1)
        else:
            samples_16k.append(samples_8k[i])
    return struct.pack(f"<{len(samples_16k)}h", *samples_16k)


# Squares of the decode table: energy of a frame is a pure table-lookup sum (runs on
# every inbound 20ms frame, so it must be cheap).
_MULAW_SQ = [int(v) * int(v) for v in _MULAW_DECODE]

# Full PCM16 -> mulaw byte lookup (indexed by the sample's unsigned 16-bit pattern).
# Turns the per-sample encode (the hottest loop: every agent sample at 24kHz) into one
# bytes-index. Built once at import (~65k cheap calls).
_PCM_TO_ULAW = bytes(
    _pcm16_to_mulaw_sample(_u - 65536 if _u >= 32768 else _u) for _u in range(65536)
)


def _mulaw_frame_meansquare(mulaw_bytes: bytes) -> float:
    """Cheap energy of one inbound mulaw frame (mean of squared PCM16 samples).
    Pure-Python (table lookups only), no sqrt, no numpy/audioop — used as a
    real-time voice-activity gate so silence/comfort-noise frames don't count as speech."""
    n = len(mulaw_bytes)
    if not n:
        return 0.0
    return sum(map(_MULAW_SQ.__getitem__, mulaw_bytes)) / n


def pcm24k_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert PCM 16-bit 24kHz (Gemini output) -> mulaw 8kHz (Plivo). Downsample 3:1 with a cheap
    3-tap average (a low-pass) instead of naive decimation, so frequencies above 4kHz don't alias
    into a metallic/robotic tone — this also makes the agent's LIVE voice clearer to the caller."""
    n_samples = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{n_samples}h", pcm_bytes)
    lut = _PCM_TO_ULAW
    return bytes(lut[((samples[i] + samples[i + 1] + samples[i + 2]) // 3) & 0xFFFF]
                 for i in range(0, n_samples - 2, 3))


# 20ms of mulaw @ 8kHz = 160 bytes per frame
ULAW_FRAME_BYTES = 160
ULAW_FRAME_S = 0.020

# 20ms of digital silence as PCM16 @ 16kHz (320 samples × 2 bytes) — what the noise
# squelch feeds Gemini in place of a below-gate frame (substitute, never drop).
_SILENCE_20MS_16K = bytes(640)


def _env_float(name, default):
    """One env-float parser for every tunable in this file."""
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


# Soft "on hold" melody to fill the 2-4s of dead air after the caller answers but before Gemini
# produces the greeting. A gentle major-pentatonic phrase with a music-box/celesta timbre (each
# note swells then fades, so it chimes rather than beeps) — looped until the agent's first audio
# arrives. Deliberately NOT a single repeating tone (that read like a countdown/alarm). Built once.
_HOLD_MUSIC_FRAMES = None


def _hold_music_frames():
    """One loop of the soft connect melody as a list of 20ms mulaw frames (built once, cached)."""
    global _HOLD_MUSIC_FRAMES
    if _HOLD_MUSIC_FRAMES is not None:
        return _HOLD_MUSIC_FRAMES
    rate = 8000

    def note(freq, dur, amp=0.24):
        # sine + a soft 2nd harmonic for warmth, with an ~8ms attack then exponential decay so each
        # note rings like a music box and settles to silence instead of clicking on/off.
        n = int(rate * dur)
        atk = max(1, int(rate * 0.008))
        out = []
        for i in range(n):
            env = (i / atk) if i < atk else math.exp(-3.2 * (i - atk) / n)
            s = math.sin(2 * math.pi * freq * i / rate) + 0.25 * math.sin(2 * math.pi * 2 * freq * i / rate)
            out.append(int(amp * env * 32767 * s / 1.25))
        return out

    def rest(dur):
        return [0] * int(rate * dur)

    C5, D5, E5, G5, A5 = 523.25, 587.33, 659.25, 783.99, 880.00   # warm mid-band, phone-safe
    b = 0.34
    phrase = [(E5, b), (G5, b), (A5, b), (G5, b), (E5, b), (D5, b), (C5, 2 * b)]
    pcm = []
    for f, d in phrase:
        pcm += note(f, d)
    pcm += rest(b)                                                # a small breath before the loop repeats
    if len(pcm) % ULAW_FRAME_BYTES:
        pcm += [0] * (ULAW_FRAME_BYTES - len(pcm) % ULAW_FRAME_BYTES)
    ulaw = bytes(_pcm16_to_mulaw_sample(s) for s in pcm)
    _HOLD_MUSIC_FRAMES = [ulaw[i:i + ULAW_FRAME_BYTES] for i in range(0, len(ulaw), ULAW_FRAME_BYTES)]
    return _HOLD_MUSIC_FRAMES


class PlivoMediaBridge:
    """Bridges a Plivo bidirectional Audio Stream WebSocket with a Gemini Live session."""

    def __init__(self, websocket, gemini_client, text_trigger, on_event=None,
                 resolve_identity=None):
        self.ws = websocket
        self.gemini = gemini_client
        self.stream_id = None
        self.call_id = ""
        self.caller = ""
        self.generation = 0
        self.text_trigger = text_trigger
        self.on_event = on_event  # async callback for live transcript
        # (call_id, header_caller, header_name) -> (caller, first_name). Lets the
        # bridge personalise the greeting even when Plivo drops extraHeaders.
        self.resolve_identity = resolve_identity

        # Queues for Gemini. The audio queue is BOUNDED (drop-oldest on overflow) so a
        # stalled Gemini send can never buffer minutes of stale audio — live > complete.
        self.audio_input_queue = asyncio.Queue(
            maxsize=max(10, int(_env_float("EO_AUDIO_INPUT_QUEUE_FRAMES", 150))))
        self.video_input_queue = asyncio.Queue()
        self.text_input_queue = asyncio.Queue()

        # Outbound (to Plivo) paced 20ms mulaw frames
        self._out_frames = asyncio.Queue()
        self._residual = bytearray()
        self._started = False
        self._call_end_emitted = False
        self._pending_hangup_task = None
        self._ending = False                     # hangup scheduled → drop any further agent audio (no re-greet)
        # Connect ringback: soft tone that fills the post-answer / pre-greeting gap,
        # stopped the instant the agent's first audio arrives.
        self._agent_audio_started = False
        self._connect_tone_task = None
        # Auto-hangup signals (so the call ends even if the agent never calls end_call):
        self._rsvp_recorded = False              # set True once record_rsvp fires
        self._last_activity = time.monotonic()   # last time either party spoke / a turn ended
        self._turn_text = ""                     # accumulated agent transcript for the current turn
        self._suppress_turn = False              # drop the rest of this turn's audio (repeat detected)
        # Stray forced-turn guard: record_rsvp is a BLOCKING tool, so its result forces one more model
        # turn. When the agent already spoke its closing, that turn is filler ("Your turn completed." /
        # "I've noted that down.") — drop its audio until the caller next speaks. Keyed on caller VAD
        # (not turn_complete) to dodge the turn_complete-vs-tool_call race and preserve mute-proofing.
        self._spoke_since_user = False           # agent emitted real audio since the caller last voiced
        self._suppress_post_record = False       # drop the forced post-record turn's audio
        self._did_suppress_audio = False         # a stray was actually dropped (gates the turn_complete clear)
        self._suppress_post_record_at = 0.0      # monotonic arm time (watchdog so the flag can never latch)
        # Real-time caller voice-activity (leads the laggy transcription "user" events) so we never
        # cut the caller off mid-sentence. Starts at 0.0 (epoch) so it reads "stale" until real speech.
        self._last_caller_audio = 0.0            # monotonic ts of the last VOICED inbound frame
        self._hold_until = 0.0                   # don't idle-hangup while now < this (caller asked to hold)
        self.first_name = ""                     # resolved member first name (for personalised nudges)
        self._hangup_done = False                # dialer.hangup_call already issued for this call
        self._last_user_event = 0.0              # monotonic ts of the last "user" transcription event
        self._last_agent_audio = 0.0             # monotonic ts of the last agent audio chunk
        self._turn_open = False                  # a model turn is being generated (first audio may lag)
        self._silence_nudged = False             # "are you still there?" asked for the current quiet spell
        self._silence_nudge_at = 0.0             # when the nudge was injected
        self._silence_wrapup_at = 0.0            # when the wrap-up nudge was injected (0 = not yet)
        self._soft_end_at = 0.0                  # when a NON-muting hangup was scheduled (0 = none)
        # Noise squelch (EO_NOISE_GATE, default OFF): frames below the gate are replaced by
        # digital silence before Gemini hears them — NEVER dropped (the server VAD must
        # still hear ~silence_duration_ms of quiet to close a turn; a gap just stalls it).
        self._gate_on = os.getenv("EO_NOISE_GATE", "false").strip().lower() in ("1", "true", "yes", "on")
        self._gate_thr = _env_float("EO_NOISE_GATE_RMS", 250) ** 2
        self._gate_thr_low = self._gate_thr / 4  # hysteresis: sustained speech stays open above this
        self._gate_hangover = _env_float("EO_NOISE_GATE_HANGOVER_S", 0.6)
        self._gate_voiced_at = 0.0               # last frame above the gate (hysteresis anchor)
        self._gate_frames = 0                    # total inbound frames (squelch-ratio log)
        self._gate_squelched = 0                 # frames replaced with silence
        try:
            self._vad_ms_threshold = float(os.getenv("EO_VAD_RMS_THRESHOLD", "500")) ** 2
        except ValueError:
            self._vad_ms_threshold = 500.0 ** 2
        # Call recording: mix inbound (caller) + outbound (agent) mulaw into one mono 8k PCM16
        # timeline, written to a WAV at call end. Behind a flag; tees are guarded so a recording
        # failure can never affect the live call.
        self._rec_on = os.getenv("EO_RECORD_CALLS", "true").strip().lower() not in ("0", "false", "no", "off")
        self._rec_t0 = None
        self._rec = array.array("h")             # mono 8kHz PCM16 mix (sample-indexed timeline)
        try:
            self._rec_max_samples = int(float(os.getenv("EO_RECORD_MAX_SECONDS", "420")) * 8000)
        except ValueError:
            self._rec_max_samples = 420 * 8000

    def _rec_add(self, mulaw_bytes):
        """Mix one ~20ms mulaw frame (either direction) into the recording timeline at its
        real-time offset. Guarded — never raises into the live audio path."""
        if not self._rec_on or not mulaw_bytes:
            return
        try:
            now = time.monotonic()
            if self._rec_t0 is None:
                self._rec_t0 = now
            start = int((now - self._rec_t0) * 8000)
            if start > self._rec_max_samples:
                return                            # cap runaway recordings
            dec = _MULAW_DECODE
            buf = self._rec
            n = len(buf)
            if n < start:                         # silence gap since the last frame
                buf.frombytes(bytes(2 * (start - n)))   # append (start-n) zero int16 samples
                n = start
            for i, b in enumerate(mulaw_bytes):
                s = dec[b]
                idx = start + i
                if idx < n:                       # overlap (barge-in) — AVERAGE (no clip) not raw sum
                    v = (buf[idx] + s) >> 1       # -6dB mix keeps both voices in-range, no distortion
                    buf[idx] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
                else:
                    buf.append(s)
        except Exception:
            pass

    def _write_recording(self):
        """Flush the mixed timeline to a mono/8kHz/16-bit WAV keyed by call_sid. Guarded."""
        if not self._rec_on or not self._rec or not self.call_id:
            return
        try:
            import wave
            import store
            path = store.recording_path(self.call_id)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(self._rec.tobytes())
            logger.info(f"Saved call recording: {path} ({len(self._rec) / 8000:.0f}s)")
        except Exception as e:
            logger.warning(f"Failed to write call recording: {e}")

    # ---- outbound (Gemini -> Plivo) ----

    async def _play_connect_tone(self):
        """Fill the gap between the caller answering and the agent's first words with a soft
        music-box melody, so they never hear dead air. Loops the phrase until the agent starts
        speaking or a safety cap elapses (in case Gemini never produces audio)."""
        try:
            cap_s = min(float(os.getenv("EO_CONNECT_TONE_MAX_S", "8")), 15.0)
        except ValueError:
            cap_s = 8.0
        frames = _hold_music_frames()
        started = time.monotonic()
        i = 0
        try:
            while not self._agent_audio_started and (time.monotonic() - started) < cap_s:
                if self.stream_id:
                    await self._out_frames.put(frames[i % len(frames)])
                i += 1
                await asyncio.sleep(ULAW_FRAME_S)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"connect-tone error: {e}")

    def _stop_connect_tone(self):
        """Agent audio is starting (or the call is ending): stop the ringback and drop any
        of its frames still queued, so the greeting plays immediately with no tail."""
        self._agent_audio_started = True
        if self._connect_tone_task and not self._connect_tone_task.done():
            self._connect_tone_task.cancel()
        try:
            while True:
                self._out_frames.get_nowait()
        except asyncio.QueueEmpty:
            pass

    async def audio_output_callback(self, data: bytes):
        """Gemini produced audio (24k PCM16). Convert to mulaw 8k and chunk into 20ms frames."""
        if not self.stream_id:
            return
        if not self._agent_audio_started:
            self._stop_connect_tone()            # first real agent audio → cut the connect ringback
        if self._ending:
            return                               # call is wrapping up — never play a re-greet / extra audio
        if self._suppress_turn:
            return                               # a repeated closing was detected — drop the duplicate audio
        if self._suppress_post_record:
            # record_rsvp fired after the agent already spoke → this forced tool-result turn is filler.
            # Drop it. Watchdog: if it somehow stays armed too long, fall through rather than stay muted.
            if time.monotonic() - self._suppress_post_record_at <= 4.0:
                self._did_suppress_audio = True
                return
            self._suppress_post_record = False
        now_a = time.monotonic()
        if not self._spoke_since_user:
            # First agent audio since the caller last voiced = start of the reply the caller
            # actually hears. Log the turn latency so prod can quantify + tune it.
            if self._last_caller_audio > 0.0:
                since_voice = now_a - self._last_caller_audio
                since_text = (now_a - self._last_user_event) if self._last_user_event > 0.0 else -1.0
                logger.info(f"TURN LATENCY: first agent audio {since_voice:.2f}s after caller's last "
                            f"voiced frame ({since_text:.2f}s after their transcription)")
        self._last_agent_audio = now_a
        # NOTE: _silence_nudged is deliberately NOT reset here — the nudge's own audio
        # would clear it and the agent would re-ask forever instead of escalating.
        # Only VOICED CALLER audio clears it (see handle_plivo_messages).
        self._spoke_since_user = True            # a genuine agent frame is going out this "since-caller" window
        try:
            self._residual.extend(pcm24k_to_mulaw(data))
            while len(self._residual) >= ULAW_FRAME_BYTES:
                frame = bytes(self._residual[:ULAW_FRAME_BYTES])
                del self._residual[:ULAW_FRAME_BYTES]
                await self._out_frames.put(frame)
        except Exception as e:
            logger.error(f"Error queuing audio for Plivo: {e}")

    def _ws_connected(self) -> bool:
        """Best-effort: is the Plivo WebSocket still open in both directions?"""
        if WebSocketState is None:
            return True
        try:
            return (self.ws.client_state == WebSocketState.CONNECTED
                    and self.ws.application_state == WebSocketState.CONNECTED)
        except Exception:
            return True

    async def _outbound_sender(self):
        """Send queued mulaw frames to Plivo, paced at 20ms for smooth playout.

        This task is the ONLY consumer of _out_frames, so it must survive transient send
        errors (a single failure here used to silently mute the agent for the rest of the
        call). A transient error is logged and skipped; a closed socket — or a burst of
        consecutive failures — ends the task, which ends the bridge (run() waits on us)."""
        next_t = None
        failures = 0
        try:
            while True:
                frame = await self._out_frames.get()
                if not self.stream_id:
                    continue
                try:
                    payload = base64.b64encode(frame).decode("ascii")
                    await self.ws.send_json({
                        "event": "playAudio",
                        "streamId": self.stream_id,
                        "media": {
                            "contentType": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "payload": payload,
                        },
                    })
                    failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    failures += 1
                    if not self._ws_connected():
                        logger.info(f"Plivo socket closed while sending audio ({e}); ending bridge")
                        break
                    if failures >= 25:             # ~0.5s of continuous failures on an "open" socket
                        logger.error(f"Plivo outbound sender: {failures} consecutive send failures "
                                     f"({e}); ending bridge")
                        break
                    logger.warning(f"Plivo outbound send failed (transient, #{failures}): {e}")
                    # keep the frame cadence on failures too — otherwise a burst of raising
                    # sends burns the 25-failure budget in microseconds instead of ~0.5s
                    await asyncio.sleep(ULAW_FRAME_S)
                    continue
                self._rec_add(frame)               # record what the caller heard (agent side)
                now = time.monotonic()
                self._last_agent_audio = now       # PLAYOUT time (paced) — silence timers key on this
                next_t = (next_t or now) + ULAW_FRAME_S
                delay = next_t - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                elif delay < -0.1:
                    next_t = time.monotonic()  # fell behind, resync
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Plivo outbound sender error: {e}")

    def _drain_outbound(self):
        self._residual.clear()
        try:
            while True:
                self._out_frames.get_nowait()
        except asyncio.QueueEmpty:
            pass

    async def audio_interrupt_callback(self):
        """Barge-in: drop queued agent audio + tell Plivo to flush its playout."""
        if not self.stream_id:
            return
        self._drain_outbound()
        try:
            await self.ws.send_json({"event": "clearAudio", "streamId": self.stream_id})
        except Exception:
            pass

    # ---- inbound (Plivo -> Gemini) ----

    @staticmethod
    def _extract_header(data: dict, start: dict, name: str) -> str:
        name = name.lower()
        raw = (data.get("extra_headers") or data.get("extraHeaders")
               or start.get("extra_headers") or start.get("extraHeaders"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                if str(k).strip().lower() == name:
                    return unquote(str(v))
            return ""
        if isinstance(raw, str) and raw:
            for pair in raw.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    if k.strip().lower() == name:
                        return unquote(v.strip())
        return ""

    async def handle_plivo_messages(self):
        """Receive messages from the Plivo Audio Stream WebSocket."""
        try:
            while True:
                message = await self.ws.receive_text()
                data = json.loads(message)
                event = str(data.get("event") or data.get("type") or "").lower()

                if event == "start":
                    start = data.get("start") if isinstance(data.get("start"), dict) else data
                    self.stream_id = str(start.get("streamId") or start.get("stream_id")
                                         or data.get("streamId") or "")
                    self.call_id = str(start.get("callId") or start.get("call_id") or "")
                    self.caller = self._extract_header(data, start, "x-caller")
                    header_name = self._extract_header(data, start, "x-caller-name")
                    gen_raw = self._extract_header(data, start, "x-callback-gen")
                    try:
                        self.generation = int(gen_raw) if gen_raw else 0
                    except ValueError:
                        self.generation = 0
                    # Resolve caller + first name BEFORE emitting call_start (which may
                    # pop the pending-call metadata the resolver relies on).
                    first_name = ""
                    if self.resolve_identity:
                        try:
                            caller, first_name = self.resolve_identity(
                                self.call_id, self.caller, header_name)
                            self.caller = caller or self.caller
                        except Exception as e:
                            logger.warning(f"resolve_identity failed: {e}")
                    self.first_name = first_name or ""
                    logger.info(f"Plivo stream started: stream_id={self.stream_id}, "
                                f"call={self.call_id}, caller={self.caller}, "
                                f"named={'yes' if first_name else 'no'}, gen={self.generation}")
                    if not self._started:
                        self._started = True
                        await self._emit({"type": "call_start", "call_sid": self.call_id or "",
                                          "caller": self.caller or "",
                                          "generation": self.generation})
                        # Start the soft connect ringback (once per call) so the caller isn't
                        # met with silence while Gemini spins up the greeting.
                        if not self._agent_audio_started:
                            self._connect_tone_task = asyncio.create_task(self._play_connect_tone())
                        # Trigger the AI to start talking — personalised by first name when known.
                        # INSIDE the once-only guard: a duplicate Plivo `start` must NOT re-send this,
                        # or the agent re-reads its whole opening mid-call.
                        if first_name:
                            trigger = (f"[The guest has just answered. Their first name is {first_name}. "
                                       f"Begin THE OPENING: your first turn is EXACTLY "
                                       f'"Hello! Am I speaking to {first_name}?" — say ONLY that, then STOP '
                                       f"and wait. Do NOT give the invitation or introduce yourself until "
                                       f"you know who answered. Use the name naturally, never overuse it.]")
                        else:
                            trigger = self.text_trigger
                        await self.text_input_queue.put(trigger)
                    else:
                        logger.info("Duplicate Plivo 'start' ignored (greeting already sent) — "
                                    "not re-triggering the opening")

                elif event == "media":
                    media = data.get("media") or {}
                    payload = media.get("payload")
                    if payload:
                        mulaw_bytes = base64.b64decode(payload)
                        # Real-time VAD: stamp caller activity the instant a VOICED inbound frame
                        # arrives — long before Gemini transcribes it — so the idle guard / hangup
                        # never fire while the caller is actually talking. Energy-gated so continuous
                        # silence/comfort-noise frames (Plivo streams ~20ms frames non-stop) don't count.
                        track = str(media.get("track") or "inbound").lower()
                        if track == "inbound":
                            self._rec_add(mulaw_bytes)   # record the caller side (all frames)
                            frame_ms = _mulaw_frame_meansquare(mulaw_bytes)
                            now_m = time.monotonic()
                            if frame_ms >= self._vad_ms_threshold:
                                self._last_caller_audio = now_m
                                self._last_activity = now_m
                                # Caller is speaking now: the agent's next audio is a genuine reply, not
                                # forced-turn filler. Clear the stray guard (VAD leads the reply audio, so
                                # the reply is never clipped) and reset the "agent spoke" signal.
                                self._spoke_since_user = False
                                self._suppress_post_record = False
                                self._did_suppress_audio = False
                                self._silence_nudged = False
                                self._silence_wrapup_at = 0.0
                            if self._gate_on:
                                # Squelch: SUBSTITUTE silence for below-gate frames (same frame cadence —
                                # Gemini's VAD needs to HEAR the quiet). Hysteresis: opens at the gate,
                                # stays open on sustained speech above gate/4, then a hangover window so
                                # onsets/tails and inter-word gaps are never clipped.
                                if frame_ms >= self._gate_thr or (
                                        frame_ms >= self._gate_thr_low
                                        and (now_m - self._gate_voiced_at) <= self._gate_hangover):
                                    self._gate_voiced_at = now_m
                                self._gate_frames += 1
                                if (now_m - self._gate_voiced_at) <= self._gate_hangover:
                                    self._put_audio(mulaw_to_pcm16k(mulaw_bytes))
                                else:
                                    self._gate_squelched += 1
                                    self._put_audio(_SILENCE_20MS_16K)
                            else:
                                self._put_audio(mulaw_to_pcm16k(mulaw_bytes))
                        else:
                            self._put_audio(mulaw_to_pcm16k(mulaw_bytes))

                elif event == "dtmf":
                    pass

                elif event == "stop":
                    logger.info("Plivo stream stopped")
                    break

        except Exception as e:
            # WebSocket close 1000 is a normal caller hangup, not an error — log it quietly.
            code = e.args[0] if getattr(e, "args", None) else None
            if code == 1000:
                logger.info("Plivo stream closed by caller (hangup)")
            else:
                logger.error(f"Plivo receive error: {e}")

    def _put_audio(self, chunk: bytes):
        """Enqueue one PCM chunk for Gemini, dropping the OLDEST frame when full — if the
        Gemini send ever stalls, staying live matters more than replaying stale audio."""
        q = self.audio_input_queue
        while True:
            try:
                q.put_nowait(chunk)
                return
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass

    async def _emit(self, event):
        """Send event to live transcript watchers."""
        if self.on_event:
            try:
                await self.on_event(event)
            except Exception:
                pass

    async def _drain_then_hangup(self):
        """Hang up gently: wait until the paced outbound buffer (the goodbye) has
        been STABLY empty (so trailing audio is fully sent, never cut mid-word),
        then give Plivo's own playout a gentle beat to finish before hanging up."""
        import dialer
        try:
            # hard-capped at 1.0s so a stale .env can't drag out the hangup
            grace = min(float(os.getenv("CALL_HANGUP_GRACE_SECONDS", "1.0")), 1.0)
        except ValueError:
            grace = 1.0
        # If the agent hasn't yet replied to the caller's last utterance (its farewell is
        # still being GENERATED — first audio can lag 1-3s), give it a bounded head start;
        # otherwise a fast grace window hangs up between "bye" and the agent's reply.
        try:
            farewell_wait = min(float(os.getenv("EO_FAREWELL_WAIT_SECONDS", "4")), 8.0)
        except ValueError:
            farewell_wait = 4.0
        waited = 0.0
        # Only when a reply is actually expected: the caller HAS spoken (_last_user_event
        # set) and the mute isn't armed (armed → no audio can ever arrive → pure dead air).
        while (waited < farewell_wait and not self._ending
               and self._last_user_event > 0.0
               and self._out_frames.empty() and not self._residual
               and self._last_agent_audio <= self._last_user_event):
            await asyncio.sleep(0.05)
            waited += 0.05
        stable = 0
        for _ in range(600):                       # up to ~12s
            if self._out_frames.empty() and not self._residual:
                stable += 1
                if stable >= 10:                   # ~0.2s of continuous silence sent
                    break
            else:
                stable = 0                         # more audio arrived; keep waiting
            await asyncio.sleep(0.02)
        await asyncio.sleep(grace)                 # let Plivo finish playing + a natural pause
        # Last-instant save: if the caller is voicing RIGHT NOW (audio arrived but transcription
        # hasn't produced a "user" event yet), don't cut them off — abort and keep the line up.
        if self._caller_voiced_recently():
            logger.info("Caller voiced within abort window; ABORTING hangup (mid-speech save)")
            self._pending_hangup_task = None
            self._ending = False                 # the call continues — the agent must be audible
            self._soft_end_at = 0.0
            return
        if self.call_id:
            self._hangup_done = True
            await dialer.hangup_call(self.call_id)

    def _caller_voiced_recently(self) -> bool:
        """True if the caller produced VOICE within the abort window — used to cancel a
        pending hangup so we never cut someone off who's just started talking. Keyed on
        inbound-only audio, so the agent's own goodbye can never trigger it."""
        try:
            window = float(os.getenv("EO_HANGUP_ABORT_WINDOW_SECONDS", "1.2"))
        except ValueError:
            window = 1.2
        return (time.monotonic() - self._last_caller_audio) <= window

    async def _max_duration_guard(self):
        """Safety net: hang up a call that runs longer than CALL_MAX_SECONDS."""
        try:
            max_s = int(os.getenv("CALL_MAX_SECONDS", "420"))
        except ValueError:
            max_s = 420
        try:
            await asyncio.sleep(max_s)
            logger.warning(f"Call {self.call_id} exceeded {max_s}s; hanging up")
            import dialer
            if self.call_id:
                await dialer.hangup_call(self.call_id)
        except asyncio.CancelledError:
            pass

    async def _idle_hangup_guard(self):
        """Keyword-free auto-hangup: end the call when the line goes quiet — quickly once
        the RSVP is recorded (task done), and after a longer window for a dead/abandoned
        call. This is what guarantees the call ends even if the agent never calls end_call.
        The actual hangup goes through _schedule_end (idempotent + grace-cancellable).

        Silence check (EO_SILENCE_CHECK, default on): before the RSVP is settled, a quiet
        spell first gets ONE warm "are you still there?" nudge (after X s of mutual
        silence), then a wrap-up nudge + hangup (after Y more s of caller silence)."""
        def _cfg(name, default):
            try:
                return float(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default
        post_rsvp = _cfg("EO_POST_RSVP_IDLE_SECONDS", 12.0)
        dead_air = _cfg("EO_IDLE_HANGUP_SECONDS", 25.0)
        nudge_on = os.getenv("EO_SILENCE_CHECK", "true").strip().lower() not in ("0", "false", "no", "off")
        nudge_x = _cfg("EO_SILENCE_PROMPT_SECONDS", 6.0)
        nudge_y = _cfg("EO_SILENCE_HANGUP_SECONDS", 10.0)
        try:
            while True:
                await asyncio.sleep(1.0)
                now = time.monotonic()
                if self._pending_hangup_task and not self._pending_hangup_task.done():
                    continue                       # already ending
                if now < self._hold_until:
                    continue                       # caller asked to hold — keep the line open
                idle = now - self._last_activity
                agent_quiet = (not self._turn_open and self._out_frames.empty()
                               and not self._residual)
                if self._rsvp_recorded and idle >= post_rsvp:
                    logger.info(f"Idle {idle:.0f}s after RSVP; scheduling hangup")
                    self._schedule_end(mute=False)   # if the agent does speak a farewell, let it play
                    continue
                if nudge_on and not self._rsvp_recorded and self._agent_audio_started \
                        and not self._ending and agent_quiet:
                    quiet_for = now - max(self._last_caller_audio, self._last_agent_audio,
                                          self._last_activity)
                    if not self._silence_nudged and quiet_for >= nudge_x:
                        self._silence_nudged = True
                        self._silence_nudge_at = now
                        who = f"'{self.first_name}, are you still there? I can't hear you.'" \
                            if self.first_name else "'Hello — are you still there? I can't hear you.'"
                        logger.info(f"Quiet for {quiet_for:.0f}s; injecting are-you-still-there nudge")
                        await self.text_input_queue.put(
                            f"[The line has gone quiet — warmly ask ONCE, {who} Then wait silently.]")
                        continue
                    if (self._silence_nudged and not self._silence_wrapup_at
                            and self._last_caller_audio < self._silence_nudge_at
                            and now - self._silence_nudge_at >= nudge_y):
                        self._silence_wrapup_at = now
                        logger.info("Still silent after the nudge; asking the agent to wrap up")
                        await self.text_input_queue.put(
                            "[Still no reply — the line seems dead. If no outcome is recorded yet, "
                            "record \"callback\" now. Then give ONE short warm goodbye and call end_call.]")
                        continue
                    if (self._silence_wrapup_at
                            and now - self._silence_wrapup_at >= 8.0):
                        logger.info("Wrap-up nudge got no end_call; scheduling hangup")
                        self._schedule_end(mute=False)
                        continue
                if idle >= dead_air:
                    logger.info(f"Idle {idle:.0f}s (dead air); scheduling hangup")
                    self._schedule_end(mute=False)
        except asyncio.CancelledError:
            pass

    def _schedule_end(self, mute: bool = True):
        """Schedule the hangup after a grace window (see _grace_then_hangup).

        mute=True (agent-initiated end_call): also drop any FURTHER agent audio — after
        end_call the only thing the model could still produce is forced-turn filler.
        mute=False (caller said goodbye / idle guard): the agent has NOT spoken its
        farewell yet — let that reply play; _drain_then_hangup waits for it. The mute is
        then armed on the next turn_complete (see _gemini_loop) so a re-greet after the
        goodbye still can't play."""
        if mute:
            self._ending = True                  # call is wrapping up — mute any further agent audio
        if self._pending_hangup_task and not self._pending_hangup_task.done():
            return
        if not mute:
            # remember WHEN the soft end was scheduled: the turn_complete-armed mute in
            # _gemini_loop only arms once agent audio has PLAYED after this moment (i.e.
            # the farewell actually went out), so a tool-only or stale turn can't arm it.
            self._soft_end_at = time.monotonic()
        self._pending_hangup_task = asyncio.create_task(self._grace_then_hangup())

    async def _grace_then_hangup(self):
        """After end_call, wait a short window so the member can jump back in. If
        they speak, _gemini_loop cancels this task and the call continues; if they
        stay silent, drain the goodbye audio and hang up."""
        try:
            # hard-capped at 2.0s so a stale .env can't drag out the "listen for resume" window
            grace = min(float(os.getenv("CALL_END_GRACE_SECONDS", "2")), 2.0)
        except ValueError:
            grace = 2.0
        try:
            await asyncio.sleep(grace)
        except asyncio.CancelledError:
            return                          # caller resumed — do NOT hang up
        # Caller started talking during the grace window (audio in, transcription still catching up)?
        # Abort here too — _drain_then_hangup re-checks as the authoritative gate.
        if self._caller_voiced_recently():
            logger.info("Caller voiced during end grace; ABORTING hangup (mid-speech save)")
            self._pending_hangup_task = None
            self._ending = False                 # the call continues — the agent must be audible
            self._soft_end_at = 0.0
            return
        await asyncio.shield(self._drain_then_hangup())

    async def _gemini_loop(self):
        """Drive the Gemini Live session. On end_call it schedules a hangup after a
        grace window (cancelled if the caller keeps talking) rather than cutting
        immediately. When the caller hangs up first, run() cancels this task;
        CancelledError then propagates into start_session's async generator, whose
        finally closes the live session immediately (so the AI is never 'on hold')."""
        try:
            async for event in self.gemini.start_session(
                audio_input_queue=self.audio_input_queue,
                video_input_queue=self.video_input_queue,
                text_input_queue=self.text_input_queue,
                audio_output_callback=self.audio_output_callback,
                audio_interrupt_callback=self.audio_interrupt_callback,
            ):
                if event:
                    await self._emit(event)
                    etype = event.get("type")
                    if etype == "error":
                        logger.error(f"Gemini error during Plivo call: {event}")
                        break
                    # Feed the idle-hangup guard: mark the task done + stamp any activity.
                    if etype == "tool_call" and event.get("name") == "record_rsvp":
                        self._rsvp_recorded = True
                        if _RSVP_SILENT:
                            # Silent RSVP: the result never forces a turn (so it can't double the closing).
                            # Only risk is a MUTE record — recorded without speaking → nudge it to speak once.
                            if not self._spoke_since_user:
                                await self.text_input_queue.put(
                                    "[Recorded. You have NOT said anything to the member about this answer yet "
                                    "— say your ONE short closing now, then stop.]")
                        elif self._spoke_since_user:
                            # Blocking fallback (<2.x): the result forces one more turn; the agent already
                            # spoke, so drop that filler turn's audio.
                            self._suppress_post_record = True
                            self._did_suppress_audio = False
                            self._suppress_post_record_at = time.monotonic()
                    # Stamp activity on caller speech AND agent speech ("gemini"), so the idle
                    # timer only counts TRUE mutual silence — never while either side is talking.
                    if etype in ("user", "interrupted", "turn_complete", "gemini"):
                        self._last_activity = time.monotonic()
                    if etype == "user":
                        self._last_user_event = time.monotonic()
                    # Within-turn repeat guard: accumulate the agent's transcript; if a closing
                    # phrase repeats inside ONE turn (the fusion loop), drop the duplicate audio.
                    if etype == "gemini":
                        self._turn_open = True           # a model turn is streaming (audio may lag the text)
                        self._turn_text += " " + (event.get("text") or "")
                        if not self._suppress_turn and _has_closing_repeat(self._turn_text):
                            self._suppress_turn = True
                            logger.info("Repeated closing mid-turn; suppressing duplicate audio")
                    elif etype in ("turn_complete", "interrupted"):
                        self._turn_open = False
                        self._turn_text = ""
                        self._suppress_turn = False
                        # A hangup is pending and the agent's FAREWELL just finished playing
                        # (agent audio went out after the soft end was scheduled): arm the mute
                        # so a spurious LATER turn (a re-greet) can never play. Gating on
                        # audio-since-schedule keeps a tool-only or in-flight stale turn's
                        # turn_complete from muting the real farewell that hasn't played yet.
                        if (etype == "turn_complete" and not self._ending
                                and self._pending_hangup_task and not self._pending_hangup_task.done()
                                and self._soft_end_at > 0.0
                                and self._last_agent_audio >= self._soft_end_at):
                            self._ending = True
                        # Clear the stray guard once the forced turn we ACTUALLY muted ends (gated by
                        # _did_suppress_audio so the closing turn's own turn_complete doesn't clear it
                        # early). Barge-in always clears — the caller is engaged.
                        if etype == "interrupted" or self._did_suppress_audio:
                            self._suppress_post_record = False
                            self._did_suppress_audio = False
                    if etype == "end_call":
                        logger.info("Agent requested end_call; will hang up after grace window")
                        self._schedule_end()
                        continue           # stay live during the grace window
                    # Caller asked to hold / wait — keep the line open, cancel any pending hangup,
                    # and DON'T treat it as a sign-off (deterministic, independent of the model).
                    if etype == "user" and _HOLD_RE.search(event.get("text") or ""):
                        try:
                            hold = float(os.getenv("EO_HOLD_GRACE_SECONDS", "30"))
                        except ValueError:
                            hold = 30.0
                        self._hold_until = time.monotonic() + hold
                        if self._pending_hangup_task and not self._pending_hangup_task.done():
                            self._pending_hangup_task.cancel()
                            self._pending_hangup_task = None
                        self._ending = False           # staying on the line — allow agent audio again
                        self._soft_end_at = 0.0
                        logger.info(f"Caller asked to hold; staying on the line for {hold:.0f}s")
                        continue
                    # Decide what a caller utterance means around the end of the call.
                    if self._pending_hangup_task and not self._pending_hangup_task.done():
                        #  - a simple "bye/thanks/okay" -> let the hangup proceed (don't re-engage)
                        #  - a real question / new info -> cancel the hangup and keep talking
                        #  - a bare interrupt (no text) -> wait for the text before deciding
                        if etype == "user" and _looks_like_goodbye(event.get("text")):
                            logger.info("Caller said goodbye; letting the hangup proceed")
                        elif etype == "user":
                            # Once the RSVP is done + goodbye given, ONLY a genuine question re-opens the
                            # call. A bare "hello / okay / hmm" must NOT re-engage (that re-read the whole
                            # invitation) — let the hangup proceed and end cleanly.
                            if _REAL_FOLLOWUP_RE.search(event.get("text") or ""):
                                self._pending_hangup_task.cancel()
                                self._pending_hangup_task = None
                                self._ending = False
                                self._soft_end_at = 0.0
                                logger.info("Caller asked a real follow-up; cancelling hangup")
                            else:
                                logger.info("Bare greeting/ack after goodbye; letting the hangup proceed")
                    elif etype == "user" and _looks_like_goodbye(event.get("text")):
                        # Caller signed off but the agent never called end_call -> end it ourselves.
                        # mute=False: the agent's own farewell reply to this "bye" is still coming —
                        # it must PLAY (muting here was the "never says goodbye back" bug); the mute
                        # arms itself on that turn's turn_complete above.
                        logger.info("Caller said goodbye; scheduling hangup (agent hadn't ended)")
                        self._schedule_end(mute=False)
        except asyncio.CancelledError:
            raise                          # caller hung up: let the generator finally close the session
        except Exception as e:
            logger.error(f"Gemini session error: {e}")

    async def run(self):
        """Run the bridge: Plivo <-> Gemini.

        Race the Gemini loop against the Plivo receive loop (and the max-duration
        guard). Whichever finishes first — caller hangup, agent end_call, or the
        guard — the finally cancels the rest, so the Gemini session never lingers
        billing after the caller leaves.
        """
        gemini_task = asyncio.create_task(self._gemini_loop())
        plivo_task = asyncio.create_task(self.handle_plivo_messages())
        sender_task = asyncio.create_task(self._outbound_sender())
        guard_task = asyncio.create_task(self._max_duration_guard())
        idle_task = asyncio.create_task(self._idle_hangup_guard())

        try:
            await asyncio.wait(
                {gemini_task, plivo_task, sender_task, guard_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            tasks = [gemini_task, plivo_task, sender_task, guard_task, idle_task]
            if self._pending_hangup_task:
                tasks.append(self._pending_hangup_task)
            if self._connect_tone_task:
                tasks.append(self._connect_tone_task)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # Plivo answers with keepCallAlive=true, so if OUR side died (e.g. the sender
            # gave up on a broken socket) the carrier call can stay up with the member
            # hearing silence. Best-effort hangup — idempotent, errors swallowed by dialer.
            if self.call_id and not self._hangup_done:
                self._hangup_done = True
                try:
                    import dialer
                    await dialer.hangup_call(self.call_id)
                except Exception:
                    pass
            self._write_recording()            # audio tasks stopped — flush the mixed WAV
            if self._gate_on and self._gate_frames:
                logger.info(f"Noise squelch: {self._gate_squelched}/{self._gate_frames} inbound frames "
                            f"replaced with silence ({100.0 * self._gate_squelched / self._gate_frames:.0f}%)")
            if self._started and not self._call_end_emitted:
                self._call_end_emitted = True
                await self._emit({"type": "call_end"})
            logger.info("Plivo-Gemini bridge closed")
