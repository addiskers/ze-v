"""callbacks.py — due-time resolution + calling-window math."""

from datetime import datetime, timedelta, timezone

import callbacks


def test_compute_due_at_prefers_valid_future_iso():
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    due, source = callbacks.compute_due_at(future, "")
    assert source == "iso"
    got = datetime.fromisoformat(due)
    assert abs((got - datetime.fromisoformat(future)).total_seconds()) < 2


def test_compute_due_at_past_iso_falls_back_to_default_next_day():
    past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    due, source = callbacks.compute_due_at(past, "")
    assert source == "default"
    # default = NEXT day 10:00 in the calling timezone (IST)
    got_ist = datetime.fromisoformat(due).astimezone(callbacks._tz())
    assert (got_ist.hour, got_ist.minute) == (10, 0)


def test_compute_due_at_never_in_the_past():
    due, _ = callbacks.compute_due_at("", "")
    assert datetime.fromisoformat(due) > datetime.now(timezone.utc)


def test_in_call_window_normal_window():
    assert callbacks.in_call_window(540, 1260, now_min=600) is True     # 10:00 inside 09-21
    assert callbacks.in_call_window(540, 1260, now_min=300) is False    # 05:00 outside
    assert callbacks.in_call_window(540, 1260, now_min=1260) is False   # end is exclusive


def test_in_call_window_overnight_wrap():
    # 21:00 → 09:00 next morning
    assert callbacks.in_call_window(1260, 540, now_min=100) is True     # 01:40
    assert callbacks.in_call_window(1260, 540, now_min=800) is False    # 13:20


def test_in_call_window_no_restriction_cases():
    assert callbacks.in_call_window(None, 540, now_min=0) is True
    assert callbacks.in_call_window(600, 600, now_min=0) is True        # start == end
