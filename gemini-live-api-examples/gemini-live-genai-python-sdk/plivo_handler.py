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
import os
import re
import struct
import time
from urllib.parse import unquote

logger = logging.getLogger(__name__)

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


def _looks_like_goodbye(text: str) -> bool:
    """True only for a short caller sign-off with no real follow-up/question."""
    t = (text or "").strip().lower()
    if not t or _QUESTION_RE.search(t):
        return False
    if len(re.findall(r"[a-z']+", t)) > 7:          # too long to be a simple sign-off
        return False
    return bool(_GOODBYE_RE.search(t))

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


def pcm24k_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert PCM 16-bit 24kHz (Gemini output) -> mulaw 8kHz (Plivo)."""
    n_samples = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{n_samples}h", pcm_bytes)
    # Downsample 24kHz -> 8kHz (take every 3rd sample)
    samples_8k = samples[::3]
    return bytes(_pcm16_to_mulaw_sample(s) for s in samples_8k)


# 20ms of mulaw @ 8kHz = 160 bytes per frame
ULAW_FRAME_BYTES = 160
ULAW_FRAME_S = 0.020


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

        # Queues for Gemini
        self.audio_input_queue = asyncio.Queue()
        self.video_input_queue = asyncio.Queue()
        self.text_input_queue = asyncio.Queue()

        # Outbound (to Plivo) paced 20ms mulaw frames
        self._out_frames = asyncio.Queue()
        self._residual = bytearray()
        self._started = False
        self._call_end_emitted = False
        self._pending_hangup_task = None

    # ---- outbound (Gemini -> Plivo) ----

    async def audio_output_callback(self, data: bytes):
        """Gemini produced audio (24k PCM16). Convert to mulaw 8k and chunk into 20ms frames."""
        if not self.stream_id:
            return
        try:
            self._residual.extend(pcm24k_to_mulaw(data))
            while len(self._residual) >= ULAW_FRAME_BYTES:
                frame = bytes(self._residual[:ULAW_FRAME_BYTES])
                del self._residual[:ULAW_FRAME_BYTES]
                await self._out_frames.put(frame)
        except Exception as e:
            logger.error(f"Error queuing audio for Plivo: {e}")

    async def _outbound_sender(self):
        """Send queued mulaw frames to Plivo, paced at 20ms for smooth playout."""
        next_t = None
        try:
            while True:
                frame = await self._out_frames.get()
                if not self.stream_id:
                    continue
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
                now = time.monotonic()
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
                    logger.info(f"Plivo stream started: stream_id={self.stream_id}, "
                                f"call={self.call_id}, caller={self.caller}, "
                                f"named={'yes' if first_name else 'no'}, gen={self.generation}")
                    if not self._started:
                        self._started = True
                        await self._emit({"type": "call_start", "call_sid": self.call_id or "",
                                          "caller": self.caller or "",
                                          "generation": self.generation})
                    # Trigger the AI to start talking — personalised by first name when known.
                    if first_name:
                        trigger = (f"[The guest has just answered. Their first name is {first_name}. "
                                   f'Greet them by first name (e.g. "Hello {first_name}!") and give '
                                   f"your invitation now. Use their first name naturally once or twice "
                                   f"more — never overuse it.]")
                    else:
                        trigger = self.text_trigger
                    await self.text_input_queue.put(trigger)

                elif event == "media":
                    media = data.get("media") or {}
                    payload = media.get("payload")
                    if payload:
                        mulaw_bytes = base64.b64decode(payload)
                        await self.audio_input_queue.put(mulaw_to_pcm16k(mulaw_bytes))

                elif event == "dtmf":
                    pass

                elif event == "stop":
                    logger.info("Plivo stream stopped")
                    break

        except Exception as e:
            logger.error(f"Plivo receive error: {e}")

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
        if self.call_id:
            await dialer.hangup_call(self.call_id)

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

    def _schedule_end(self):
        """Schedule the hangup after a grace window (see _grace_then_hangup)."""
        if self._pending_hangup_task and not self._pending_hangup_task.done():
            return
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
                    if etype == "end_call":
                        logger.info("Agent requested end_call; will hang up after grace window")
                        self._schedule_end()
                        continue           # stay live during the grace window
                    # After the agent's goodbye + end_call, decide what a caller utterance means:
                    #  - a simple "bye/thanks/okay"  -> let the hangup proceed (don't re-engage)
                    #  - a real question / new info  -> cancel the hangup and keep talking
                    #  - a bare interrupt (no text)  -> wait for the text before deciding
                    if self._pending_hangup_task and not self._pending_hangup_task.done():
                        if etype == "user" and _looks_like_goodbye(event.get("text")):
                            logger.info("Caller said goodbye; letting the hangup proceed")
                        elif etype == "user":
                            self._pending_hangup_task.cancel()
                            self._pending_hangup_task = None
                            logger.info("Caller resumed with a follow-up; cancelling hangup")
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

        try:
            await asyncio.wait(
                {gemini_task, plivo_task, guard_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            tasks = [gemini_task, plivo_task, sender_task, guard_task]
            if self._pending_hangup_task:
                tasks.append(self._pending_hangup_task)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._started and not self._call_end_emitted:
                self._call_end_emitted = True
                await self._emit({"type": "call_end"})
            logger.info("Plivo-Gemini bridge closed")
