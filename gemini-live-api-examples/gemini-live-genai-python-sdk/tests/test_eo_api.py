"""eo_api.py — display-status derivation matrix + remark validation + RSVP labels."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import eo_api


def _cc(**over):
    cc = {"call_status": "pending", "attempts": 0, "rsvp_outcome": None,
          "next_attempt_at": None, "last_error": None}
    cc.update(over)
    return cc


FUTURE = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
LIVE = {"status": "live", "call_start_min": 0, "call_end_min": 0}      # 0==0 → window always open


def test_display_matrix_core_states():
    assert eo_api._contact_display(_cc(call_status="calling")) == ("In progress", "blue")
    assert eo_api._contact_display(_cc(call_status="failed")) == ("Unreachable — max attempts", "red")
    assert eo_api._contact_display(_cc(call_status="done", rsvp_outcome="yes")) == ("Interested", "green")
    assert eo_api._contact_display(_cc(call_status="done", rsvp_outcome="voicemail")) == ("Voicemail", "amber")
    assert eo_api._contact_display(_cc(call_status="done")) == ("Answered — no outcome captured", "amber")
    assert eo_api._contact_display(_cc()) == ("Queued", "amber")


def test_display_retry_scheduled_names_the_reason():
    label, variant = eo_api._contact_display(
        _cc(attempts=1, next_attempt_at=FUTURE, last_error="no answer"))
    assert label == "Retry scheduled — no answer" and variant == "amber"
    label, _ = eo_api._contact_display(
        _cc(attempts=2, next_attempt_at=FUTURE, last_error="voicemail"))
    assert label == "Retry scheduled — voicemail"


def test_display_past_due_explains_the_gate():
    row = _cc(attempts=1, next_attempt_at=PAST, last_error="no answer")
    assert eo_api._contact_display(row, {"status": "completed"}, True)[0] == "Waiting — campaign not active"
    assert eo_api._contact_display(row, LIVE, False)[0] == "Waiting — scheduler off"
    # window (0,1): only minute 0 of the IST day is "inside" — effectively always closed
    closed = {"status": "live", "call_start_min": 0, "call_end_min": 1}
    label = eo_api._contact_display(row, closed, True)[0]
    assert label in ("Waiting for calling hours", "Due now — no answer")   # minute-0 edge tolerated
    assert eo_api._contact_display(row, LIVE, True)[0] == "Due now — no answer"


def test_attach_contact_display_uses_inline_campaign_fields_from_queue_rows():
    rows = [_cc(attempts=1, next_attempt_at=PAST, last_error="voicemail",
                campaign_status="completed", campaign_call_start_min=540,
                campaign_call_end_min=1260)]
    eo_api._attach_contact_display(rows, None, True)
    assert rows[0]["display_status"] == "Waiting — campaign not active"
    assert rows[0]["display_variant"] == "amber"


def test_callback_labels_cover_the_full_machine():
    for raw in ("pending", "in_flight", "completed", "failed", "cancelled"):
        label, variant = eo_api._CALLBACK_LABELS[raw]
        assert label and variant in ("green", "blue", "amber", "red")


def test_rsvp_labels_cover_every_tool_enum_value():
    import gemini_live
    enum = gemini_live.TOOLS[0]["parameters"]["properties"]["outcome_status"]["enum"]
    for value in enum:
        assert value in eo_api._RSVP_LABELS, f"missing display label for outcome '{value}'"


def test_clean_remark_strips_and_caps():
    assert eo_api._clean_remark({"remark": "  hello  "}) == "hello"
    assert eo_api._clean_remark({}) == ""
    with pytest.raises(HTTPException):
        eo_api._clean_remark({"remark": "x" * 501})
