"""recorder.py — voicemail must never create a member-callback; backprop exclusions."""

import asyncio
from datetime import datetime, timedelta, timezone

import eo_db
import recorder as recorder_mod
import store
from recorder import CallRecorder


def _rec_with_call(**over):
    r = CallRecorder(model="test")
    r.call = {"id": "c1", "call_sid": "sid1", "caller": "+919000000001", "generation": 0,
              "campaign_id": None, "origin_call_id": None, "booking_created": False,
              "transcript": [], "tool_calls": []}
    r.call.update(over)
    return r


def _tool_event(result):
    return {"type": "tool_call", "name": "record_rsvp", "args": {}, "result": result}


def test_voicemail_records_outcome_but_never_schedules_callback():
    r = _rec_with_call()
    r._record_tool(_tool_event({"outcome_status": "voicemail", "note": "machine answered"}))
    assert r.call["rsvp_outcome_status"] == "voicemail"
    assert r.call["rsvp_note"] == "machine answered"
    assert "callback" not in r.call                      # no "user requested callback"
    assert r.call["booking_created"] is False


def test_live_callback_still_schedules_a_callback_block():
    future = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    r = _rec_with_call()
    r._record_tool(_tool_event({"outcome_status": "callback",
                                "callback_time_iso": future,
                                "callback_time_text": "this evening"}))
    cb = r.call.get("callback")
    assert cb and cb["status"] == "pending"
    assert cb["to"] == "+919000000001"


def test_yes_after_pending_callback_cancels_it():
    r = _rec_with_call()
    r.call["callback"] = {"status": "pending"}
    r._record_tool(_tool_event({"outcome_status": "yes"}))
    assert r.call["callback"]["status"] == "cancelled"
    assert r.call["booking_created"] is True


def test_guest_name_and_note_are_persisted():
    r = _rec_with_call()
    r._record_tool(_tool_event({"outcome_status": "no", "guest_name": "Pratik",
                                "note": "travelling that week"}))
    assert r.call["rsvp_guest_name"] == "Pratik"
    assert r.call["rsvp_note"] == "travelling that week"


def _run_backprop(monkeypatch, outcome):
    origin = {"id": "origin1", "callback": {"status": "pending", "result_call_id": None,
                                            "result_outcome": None}}
    saved, cc_calls = [], []

    async def fake_load(call_id):
        return origin

    async def fake_save(call):
        saved.append(call)

    monkeypatch.setattr(store, "load_call", fake_load)
    monkeypatch.setattr(store, "save_call", fake_save)
    monkeypatch.setattr(eo_db, "cc_set_outcome_by_phone",
                        lambda cid, phone, oc: cc_calls.append((cid, phone, oc)))

    r = _rec_with_call(origin_call_id="origin1", campaign_id=5,
                       rsvp_outcome_status=outcome)
    asyncio.run(r._backpropagate_to_origin())
    return origin, cc_calls


def test_backprop_voicemail_links_but_never_resolves_the_block(monkeypatch):
    origin, cc_calls = _run_backprop(monkeypatch, "voicemail")
    assert origin["callback"]["result_outcome"] == "voicemail"   # linked for history
    assert origin["callback"]["status"] == "pending"             # NOT resolved (not an answer)
    # the contact rollup DOES run — "Voicemail" is the truthful final label for a spent
    # callback chain (the old phantom was a forever-"Callback requested" contact)
    assert cc_calls == [(5, "+919000000001", "voicemail")]


def test_backprop_real_answer_resolves_block_and_rolls_onto_contact(monkeypatch):
    origin, cc_calls = _run_backprop(monkeypatch, "yes")
    assert origin["callback"]["status"] == "completed"
    assert cc_calls == [(5, "+919000000001", "yes")]
