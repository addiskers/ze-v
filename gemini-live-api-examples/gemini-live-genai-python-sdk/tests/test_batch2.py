"""Batch 2: manual RSVP overwrite, cancellable retries, remark = agent note."""

import asyncio
from datetime import datetime, timezone

import campaign_runner
import eo_api
import eo_db
import store
from recorder import CallRecorder


# ── manual RSVP overwrite ─────────────────────────────────────────────────────

def _call(**over):
    c = {"id": "c1", "status": "completed", "rsvp_outcome_status": "callback",
         "booking_created": False, "caller": "+919000000001", "campaign_id": None}
    c.update(over)
    return c


def test_manual_outcome_preserves_original_once_and_flags_manual():
    call = _call()
    eo_api._apply_manual_outcome(call, "yes", "eoadmin")
    assert call["rsvp_outcome_status"] == "yes"
    assert call["rsvp_outcome_original"] == "callback"
    assert call["booking_created"] is True
    assert call["rsvp_source"] == "manual"
    assert call["rsvp_edited_by"] == "eoadmin"
    # a second edit keeps the FIRST original, not the intermediate value
    eo_api._apply_manual_outcome(call, "no", "eoadmin")
    assert call["rsvp_outcome_original"] == "callback"
    assert call["booking_created"] is False


def test_manual_outcome_cancels_pending_callback_block():
    call = _call(callback={"status": "pending"})
    eo_api._apply_manual_outcome(call, "no", "u")
    assert call["callback"]["status"] == "cancelled"
    # ...but keeping it as "callback" leaves the block alone
    call2 = _call(callback={"status": "pending"})
    eo_api._apply_manual_outcome(call2, "callback", "u")
    assert call2["callback"]["status"] == "pending"
    # ...and a COMPLETED block (history) is never touched
    call3 = _call(callback={"status": "completed"})
    eo_api._apply_manual_outcome(call3, "no", "u")
    assert call3["callback"]["status"] == "completed"


def test_cc_set_outcome_mark_done_and_remark_fill(fresh_eo_db):
    eo_db_ = fresh_eo_db
    eo_db_.init()
    admin = eo_db_.create_user("a", "A", "h", "s", role="eo_admin")
    cid = eo_db_.create_campaign("C", datetime.now(timezone.utc).isoformat(), admin, 4, 3, 1)
    eo_db_.add_campaign_contacts(cid, [{"id": None, "phone": "+919000000009", "name": "R"}])
    cc = eo_db_.list_campaign_contacts(cid)["items"][0]
    eo_db_.cc_update(cc["id"], call_status="pending", attempts=1,
                     next_attempt_at="2026-07-10T05:00:00+00:00")

    eo_db_.cc_set_outcome_by_phone(cid, "+919000000009", "yes", mark_done=True, remark="spoke to member")
    row = eo_db_.get_campaign_contact(cc["id"])
    assert row["rsvp_outcome"] == "yes"
    assert row["call_status"] == "done"            # retries stopped
    assert row["next_attempt_at"] is None
    assert row["remark"] == "spoke to member"      # filled because it was empty

    # a human remark is never overwritten
    eo_db_.cc_set_outcome_by_phone(cid, "+919000000009", "no", remark="different note")
    row = eo_db_.get_campaign_contact(cc["id"])
    assert row["remark"] == "spoke to member"
    assert row["rsvp_outcome"] == "no"


# ── cancelled retries ─────────────────────────────────────────────────────────

def test_display_status_cancelled():
    assert eo_api._contact_display({"call_status": "cancelled", "attempts": 2,
                                    "rsvp_outcome": None, "next_attempt_at": None,
                                    "last_error": "no answer"}) == ("Cancelled", "red")


# ── remark = agent note ───────────────────────────────────────────────────────

def test_recorder_note_becomes_call_remark():
    r = CallRecorder(model="t")
    r.call = {"id": "x", "caller": "+919", "generation": 0, "booking_created": False,
              "transcript": [], "tool_calls": []}
    r._record_tool({"type": "tool_call", "name": "record_rsvp", "args": {},
                    "result": {"outcome_status": "yes", "note": "bringing son, 14"}})
    assert r.call["remark"] == "bringing son, 14"
    assert r.call["rsvp_note"] == "bringing son, 14"


def _reap_with(monkeypatch, rec, cc_extra=None):
    calls = []
    cc = {"id": 42, "campaign_id": 7, "phone": "+919000000000", "name": "Rohan",
          "call_status": "calling", "attempts": 1, "day_attempts": 1,
          "created_at": datetime.now(timezone.utc).isoformat(),
          "last_attempt_at": datetime.now(timezone.utc).isoformat()}
    cc.update(cc_extra or {})
    monkeypatch.setattr(eo_db, "cc_update", lambda cc_id, **f: calls.append((cc_id, f)))
    monkeypatch.setattr(eo_db, "cc_by_status", lambda c, s: [cc])

    async def fake_find(campaign_id, phone, since_iso=None):
        return rec
    monkeypatch.setattr(store, "find_campaign_call", fake_find)
    campaign = {"id": 7, "status": "live", "callback_delay_hours": 2,
                "callback_max_per_day": 3, "callback_days": 1,
                "call_start_min": 540, "call_end_min": 1260}
    asyncio.run(campaign_runner._reap_calling(campaign, datetime.now(timezone.utc)))
    return calls


def test_reap_copies_agent_note_onto_empty_contact_remark(monkeypatch):
    rec = {"id": "k1", "ended_at": "t", "rsvp_outcome_status": "yes",
           "remark": "wife confirmed for both"}
    calls = _reap_with(monkeypatch, rec)
    assert calls[0][1]["remark"] == "wife confirmed for both"


def test_reap_never_overwrites_a_human_remark(monkeypatch):
    rec = {"id": "k2", "ended_at": "t", "rsvp_outcome_status": "yes", "remark": "agent note"}
    calls = _reap_with(monkeypatch, rec, cc_extra={"remark": "typed by admin"})
    assert "remark" not in calls[0][1]