"""campaign_runner.py — retry math (IST next-day fix) + voicemail reap routing."""

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import campaign_runner
import eo_db
import store

IST = ZoneInfo("Asia/Kolkata")

CAMPAIGN = {
    "id": 7, "status": "live",
    "callback_delay_hours": 2, "callback_max_per_day": 3, "callback_days": 2,
    "call_start_min": 600, "call_end_min": 1260,   # 10:00-21:00 IST
}


def _cc(**over):
    cc = {"id": 42, "campaign_id": 7, "phone": "+919000000000", "name": "Rohan",
          "call_status": "calling", "attempts": 1, "day_attempts": 1,
          "created_at": datetime.now(timezone.utc).isoformat(),
          "last_attempt_at": datetime.now(timezone.utc).isoformat()}
    cc.update(over)
    return cc


def _capture_cc_update(monkeypatch):
    calls = []
    monkeypatch.setattr(eo_db, "cc_update", lambda cc_id, **fields: calls.append((cc_id, fields)))
    return calls


def test_apply_failure_same_day_retry_after_delay_hours(monkeypatch):
    calls = _capture_cc_update(monkeypatch)
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    campaign_runner._apply_failure(_cc(), CAMPAIGN, now, error="no answer")
    _, fields = calls[0]
    assert fields["call_status"] == "pending"
    assert fields["last_error"] == "no answer"
    nxt = datetime.fromisoformat(fields["next_attempt_at"])
    assert abs((nxt - now).total_seconds() - 2 * 3600) < 2


def test_apply_failure_day_quota_resumes_next_ist_day_at_window_start(monkeypatch):
    calls = _capture_cc_update(monkeypatch)
    # 00:30 UTC = 06:00 IST — the old UTC-date bug would compute "next day" as IST-today.
    now = datetime(2026, 7, 9, 0, 30, tzinfo=timezone.utc)
    campaign_runner._apply_failure(_cc(day_attempts=3), CAMPAIGN, now, error="no answer")
    _, fields = calls[0]
    assert fields["call_status"] == "pending"
    nxt_ist = datetime.fromisoformat(fields["next_attempt_at"]).astimezone(IST)
    assert nxt_ist.date() == datetime(2026, 7, 10).date()     # next IST calendar day
    assert (nxt_ist.hour, nxt_ist.minute) == (10, 0)          # campaign call_start_min=600


def test_apply_failure_exhausted_marks_failed(monkeypatch):
    calls = _capture_cc_update(monkeypatch)
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    campaign_runner._apply_failure(_cc(attempts=6), CAMPAIGN, now, error="no answer")  # 3/day × 2 days
    _, fields = calls[0]
    assert fields["call_status"] == "failed"
    assert fields["next_attempt_at"] is None


def _run_reap(monkeypatch, rec, cc):
    calls = _capture_cc_update(monkeypatch)
    monkeypatch.setattr(eo_db, "cc_by_status", lambda cid, st: [cc])

    async def fake_find(campaign_id, phone, since_iso=None):
        return rec
    monkeypatch.setattr(store, "find_campaign_call", fake_find)
    asyncio.run(campaign_runner._reap_calling(CAMPAIGN, datetime.now(timezone.utc)))
    return calls


def test_reap_voicemail_routes_to_retry_not_done(monkeypatch):
    rec = {"id": "call1", "ended_at": "2026-07-09T10:00:00+00:00", "rsvp_outcome_status": "voicemail"}
    calls = _run_reap(monkeypatch, rec, _cc())
    # first update: keep the voicemail marker + call link on the contact
    assert calls[0][1] == {"rsvp_outcome": "voicemail", "last_call_id": "call1"}
    # second update (from _apply_failure): retry track, NOT done
    fields = calls[1][1]
    assert fields["call_status"] == "pending"
    assert fields["last_error"] == "voicemail"
    assert fields["next_attempt_at"] is not None


def test_reap_real_answer_marks_done(monkeypatch):
    rec = {"id": "call2", "ended_at": "2026-07-09T10:00:00+00:00", "rsvp_outcome_status": "yes"}
    calls = _run_reap(monkeypatch, rec, _cc())
    assert len(calls) == 1
    assert calls[0][1]["call_status"] == "done"
    assert calls[0][1]["rsvp_outcome"] == "yes"


def test_reap_no_record_past_ring_window_is_no_answer(monkeypatch):
    from datetime import timedelta
    old = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    calls = _run_reap(monkeypatch, None, _cc(last_attempt_at=old))
    fields = calls[0][1]
    assert fields["last_error"] == "no answer"
    assert fields["call_status"] in ("pending", "failed")
