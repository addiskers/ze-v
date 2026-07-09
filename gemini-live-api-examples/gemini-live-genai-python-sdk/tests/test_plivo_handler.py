"""plivo_handler.py — codec tables, goodbye/mute separation, sender resilience, squelch."""

import asyncio
import base64
import json
import struct
import time

import pytest

import plivo_handler as ph
from plivo_handler import (PlivoMediaBridge, _has_closing_repeat, _looks_like_goodbye,
                           _MULAW_DECODE, _MULAW_SQ, _PCM_TO_ULAW, _SILENCE_20MS_16K,
                           _mulaw_frame_meansquare, _pcm16_to_mulaw_sample, pcm24k_to_mulaw)

try:
    from starlette.websockets import WebSocketState
except ImportError:
    WebSocketState = None


class FakeWS:
    def __init__(self, fail_times=0, connected=True, incoming=None):
        self.sent = []
        self.fail_times = fail_times
        self._incoming = list(incoming or [])
        if WebSocketState is not None:
            state = WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
            self.client_state = state
            self.application_state = state

    async def send_json(self, payload):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("boom")
        self.sent.append(payload)

    async def receive_text(self):
        if not self._incoming:
            raise Exception((1000,))
        return self._incoming.pop(0)


def _bridge(ws=None, **env):
    return PlivoMediaBridge(ws or FakeWS(), gemini_client=None, text_trigger="[go]")


# ── codec tables ──────────────────────────────────────────────────────────────

def test_pcm_to_ulaw_table_matches_reference_encoder():
    for s in (-32768, -32635, -10000, -1, 0, 1, 42, 8000, 32635, 32767):
        assert _PCM_TO_ULAW[s & 0xFFFF] == _pcm16_to_mulaw_sample(s)


def test_mulaw_square_table_matches_decode_table():
    for b in range(256):
        assert _MULAW_SQ[b] == int(_MULAW_DECODE[b]) ** 2


def test_pcm24k_to_mulaw_lookup_equivalent_to_per_sample_encode():
    samples = [0, 100, -100, 8000, -8000, 32767, -32768, 5, 6, 7]
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    expected = bytes(_pcm16_to_mulaw_sample((samples[i] + samples[i+1] + samples[i+2]) // 3)
                     for i in range(0, len(samples) - 2, 3))
    assert pcm24k_to_mulaw(pcm) == expected


def test_meansquare_zero_for_silence_high_for_speech():
    silence = bytes([_pcm16_to_mulaw_sample(0)]) * 160
    loud = bytes([_pcm16_to_mulaw_sample(8000)]) * 160
    assert _mulaw_frame_meansquare(silence) < 10
    assert _mulaw_frame_meansquare(loud) > 250_000


# ── goodbye heuristics ────────────────────────────────────────────────────────

def test_looks_like_goodbye():
    assert _looks_like_goodbye("okay bye") is True
    assert _looks_like_goodbye("thank you") is True
    assert _looks_like_goodbye("bye, but what time is it?") is False       # real follow-up
    assert _looks_like_goodbye("thanks a lot for calling me today about this event") is False  # too long
    assert _looks_like_goodbye("") is False


def test_has_closing_repeat_detects_doubled_closing():
    assert _has_closing_repeat("see you on the tenth! ... see you on the tenth!") is True
    assert _has_closing_repeat("lovely, see you on the tenth then") is False


# ── goodbye playback: scheduling a hangup must NOT mute the farewell ─────────

def test_schedule_end_soft_lets_farewell_audio_through():
    async def run():
        b = _bridge()
        b.stream_id = "s1"
        b._agent_audio_started = True
        b._schedule_end(mute=False)
        assert b._ending is False                     # farewell may still play
        await b.audio_output_callback(b"\x00\x10" * 240)   # 24kHz pcm chunk
        got = not b._out_frames.empty() or bool(b._residual)
        b._pending_hangup_task.cancel()
        return got
    assert asyncio.run(run()) is True


def test_schedule_end_muted_drops_further_audio():
    async def run():
        b = _bridge()
        b.stream_id = "s1"
        b._agent_audio_started = True
        b._schedule_end(mute=True)
        assert b._ending is True
        await b.audio_output_callback(b"\x00\x10" * 240)
        got = b._out_frames.empty() and not b._residual
        b._pending_hangup_task.cancel()
        return got
    assert asyncio.run(run()) is True


# ── outbound sender resilience ────────────────────────────────────────────────

def test_sender_survives_transient_send_failures():
    async def run():
        ws = FakeWS(fail_times=3, connected=True)
        b = _bridge(ws)
        b.stream_id = "s1"
        for _ in range(5):
            b._out_frames.put_nowait(b"\x00" * 160)
        task = asyncio.create_task(b._outbound_sender())
        await asyncio.sleep(0.3)
        alive = not task.done()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # 3 transient failures skipped, remaining 2 frames actually sent
        return alive, len(ws.sent)
    alive, sent = asyncio.run(run())
    assert alive is True
    assert sent == 2


@pytest.mark.skipif(WebSocketState is None, reason="starlette not installed")
def test_sender_exits_when_socket_is_closed():
    async def run():
        ws = FakeWS(fail_times=99, connected=False)
        b = _bridge(ws)
        b.stream_id = "s1"
        b._out_frames.put_nowait(b"\x00" * 160)
        task = asyncio.create_task(b._outbound_sender())
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()
            return False
        return True
    assert asyncio.run(run()) is True


# ── noise squelch: substitutes silence, same frame cadence, never drops ──────

def _media_msg(mulaw: bytes) -> str:
    return json.dumps({"event": "media",
                       "media": {"payload": base64.b64encode(mulaw).decode(), "track": "inbound"}})


def test_squelch_substitutes_silence_and_preserves_frame_count(monkeypatch):
    monkeypatch.setenv("EO_NOISE_GATE", "true")
    quiet = bytes([_pcm16_to_mulaw_sample(0)]) * 160
    loud = bytes([_pcm16_to_mulaw_sample(8000)]) * 160

    async def run():
        ws = FakeWS(incoming=[_media_msg(quiet), _media_msg(quiet), _media_msg(loud)])
        b = _bridge(ws)
        b._rec_on = False
        await b.handle_plivo_messages()
        frames = []
        while not b.audio_input_queue.empty():
            frames.append(b.audio_input_queue.get_nowait())
        return frames

    frames = asyncio.run(run())
    assert len(frames) == 3                          # cadence preserved — nothing dropped
    assert frames[0] == _SILENCE_20MS_16K            # below gate, no recent voice → silence
    assert frames[1] == _SILENCE_20MS_16K
    assert frames[2] != _SILENCE_20MS_16K            # voiced frame passes unmodified


def test_gate_off_forwards_everything_verbatim(monkeypatch):
    monkeypatch.setenv("EO_NOISE_GATE", "false")
    quiet = bytes([_pcm16_to_mulaw_sample(0)]) * 160

    async def run():
        ws = FakeWS(incoming=[_media_msg(quiet)])
        b = _bridge(ws)
        b._rec_on = False
        await b.handle_plivo_messages()
        return b.audio_input_queue.get_nowait()

    frame = asyncio.run(run())
    assert len(frame) == 640
    # decoded silence upsampled is all-zero PCM, but it went through the codec path
    assert frame == ph.mulaw_to_pcm16k(quiet)


# ── silence check: ask ONCE, then escalate — never loop the question ─────────

def test_silence_nudge_fires_once_then_escalates(monkeypatch):
    monkeypatch.setenv("EO_SILENCE_CHECK", "true")
    monkeypatch.setenv("EO_SILENCE_PROMPT_SECONDS", "0.2")
    monkeypatch.setenv("EO_SILENCE_HANGUP_SECONDS", "0.5")

    async def run():
        b = _bridge()
        b.stream_id = "s1"
        b._agent_audio_started = True
        b.first_name = "Pratik"
        t = time.monotonic()
        b._last_agent_audio = t - 10          # agent finished long ago, caller silent since
        b._last_caller_audio = t - 10
        b._last_activity = t - 10
        task = asyncio.create_task(b._idle_hangup_guard())
        await asyncio.sleep(1.1)              # 1st guard tick → "are you still there?"
        await b.audio_output_callback(b"\x00\x10" * 240)   # the nudge is spoken aloud...
        b._drain_outbound()                                # ...and finishes playing
        await asyncio.sleep(2.2)              # must ESCALATE now, not re-ask
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if b._pending_hangup_task:
            b._pending_hangup_task.cancel()
        msgs = []
        while not b.text_input_queue.empty():
            msgs.append(b.text_input_queue.get_nowait())
        return msgs

    msgs = asyncio.run(run())
    still_there = [m for m in msgs if "still there" in m]
    wrapups = [m for m in msgs if "seems dead" in m]
    assert len(still_there) == 1, f"nudge must fire exactly once, got {msgs}"
    assert len(wrapups) == 1, f"expected one wrap-up escalation, got {msgs}"
    assert "Pratik" in still_there[0]


# ── greeting watchdog: one firm push when Gemini stalls on the opening line ──

def test_greeting_watchdog_pushes_exactly_once(monkeypatch):
    monkeypatch.setenv("EO_GREETING_NUDGE_SECONDS", "0.5")

    async def run():
        b = _bridge()
        b._greeting_sent_at = time.monotonic() - 5    # trigger sent, still no agent audio
        task = asyncio.create_task(b._idle_hangup_guard())
        await asyncio.sleep(2.3)                      # two+ guard ticks
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        msgs = []
        while not b.text_input_queue.empty():
            msgs.append(b.text_input_queue.get_nowait())
        return msgs

    msgs = asyncio.run(run())
    assert sum("Speak your opening line" in m for m in msgs) == 1


def test_greeting_watchdog_never_fires_after_audio_started(monkeypatch):
    monkeypatch.setenv("EO_GREETING_NUDGE_SECONDS", "0.5")

    async def run():
        b = _bridge()
        b._greeting_sent_at = time.monotonic() - 5
        b._agent_audio_started = True                 # greeting already played
        task = asyncio.create_task(b._idle_hangup_guard())
        await asyncio.sleep(1.2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        msgs = []
        while not b.text_input_queue.empty():
            msgs.append(b.text_input_queue.get_nowait())
        return [m for m in msgs if "Speak your opening line" in m]

    assert asyncio.run(run()) == []


# ── silence nudge: cooldown + hard cap survive noise-blip flag resets ─────────

def test_silence_nudge_respects_cooldown_after_noise_reset(monkeypatch):
    monkeypatch.setenv("EO_SILENCE_CHECK", "true")
    monkeypatch.setenv("EO_SILENCE_PROMPT_SECONDS", "0.2")
    monkeypatch.setenv("EO_SILENCE_NUDGE_COOLDOWN_S", "60")

    async def run():
        b = _bridge()
        b._agent_audio_started = True
        t = time.monotonic()
        b._last_agent_audio = t - 10
        b._last_caller_audio = t - 10
        b._last_activity = t - 10
        # a nudge fired 1s ago; then a noise blip reset the flag
        b._silence_nudged = False
        b._silence_nudge_at = t - 1
        b._silence_nudge_count = 1
        task = asyncio.create_task(b._idle_hangup_guard())
        await asyncio.sleep(1.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if b._pending_hangup_task:
            b._pending_hangup_task.cancel()
        msgs = []
        while not b.text_input_queue.empty():
            msgs.append(b.text_input_queue.get_nowait())
        return [m for m in msgs if "still there" in m]

    assert asyncio.run(run()) == []                   # cooldown blocks the re-ask


# ── bounded input queue: drop-oldest, never blocks ───────────────────────────

def test_put_audio_drops_oldest_on_overflow():
    async def run():
        b = _bridge()
        b.audio_input_queue = asyncio.Queue(maxsize=3)
        for i in range(5):
            b._put_audio(bytes([i]) * 4)
        out = []
        while not b.audio_input_queue.empty():
            out.append(b.audio_input_queue.get_nowait())
        return out
    out = asyncio.run(run())
    assert len(out) == 3
    assert out[0][0] == 2 and out[-1][0] == 4        # oldest (0,1) dropped
