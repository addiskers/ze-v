"""store.py — remark rides the light meta; find_campaign_call since-filtering."""

import asyncio
from datetime import datetime, timedelta, timezone

import store


def _call(call_id, campaign_id=None, caller=None, started_at=None, **over):
    c = {"id": call_id, "call_sid": f"sid-{call_id}", "source": "plivo",
         "caller": caller, "campaign_id": campaign_id,
         "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
         "ended_at": datetime.now(timezone.utc).isoformat(),
         "status": "completed", "booking_created": False,
         "transcript": [{"role": "user", "text": "hi", "ts": "t"}],
         "tool_calls": []}
    c.update(over)
    return c


def test_remark_is_in_light_meta_but_transcript_is_not():
    call = _call("meta1", remark="spoke to spouse")
    meta = store._meta_from_call(call)
    assert meta["remark"] == "spoke to spouse"
    assert "transcript" not in meta
    assert "tool_calls" not in meta


def test_remark_roundtrips_through_save_and_load():
    async def run():
        call = _call("rt1", remark="note to self")
        await store.save_call(call)
        loaded = await store.load_call("rt1")
        return loaded
    loaded = asyncio.run(run())
    assert loaded["remark"] == "note to self"
    assert loaded["transcript"]                       # heavy fields intact on disk


def test_find_campaign_call_respects_since_iso():
    async def run():
        base = datetime.now(timezone.utc)
        old = _call("old1", campaign_id=9, caller="+919111111111", started_at=base - timedelta(hours=2))
        new = _call("new1", campaign_id=9, caller="+919111111111", started_at=base - timedelta(minutes=5))
        await store.save_call(old)
        await store.save_call(new)
        since = (base - timedelta(hours=1)).isoformat()
        hit = await store.find_campaign_call(9, "+919111111111", since_iso=since)
        return hit
    hit = asyncio.run(run())
    assert hit is not None and hit["id"] == "new1"
