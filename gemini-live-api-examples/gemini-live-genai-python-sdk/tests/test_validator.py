"""main.handle_record_rsvp — outcome normalization, incl. the voicemail coercions that
stop a machine answer from ever becoming a phantom 'user requested callback'."""

from main import handle_record_rsvp


def _status(**kwargs):
    return handle_record_rsvp(**kwargs)["outcome_status"]


def test_valid_statuses_pass_through():
    for s in ("yes", "no", "callback", "voicemail", "do_not_contact", "wrong_number"):
        assert _status(outcome_status=s) == s


def test_unknown_status_with_voicemail_wording_coerces_to_voicemail():
    assert _status(outcome_status="voicemail_detected") == "voicemail"
    assert _status(outcome_status="voice mail") == "voicemail"
    assert _status(outcome_status="unknown", note="reached an answering machine") == "voicemail"


def test_unknown_status_falls_back_to_callback_not_no():
    assert _status(outcome_status="not_interested") == "callback"
    assert _status(outcome_status="") == "callback"


def test_unknown_status_with_attending_flag_is_yes():
    assert _status(outcome_status="confirmed", attending=True) == "yes"


def test_callback_with_voicemail_note_and_no_time_is_voicemail():
    # the exact old-prompt shape that created the phantom next-day-10am callbacks
    assert _status(outcome_status="callback",
                   note="voicemail — no live answer") == "voicemail"


def test_callback_with_voicemail_note_but_a_real_time_stays_callback():
    assert _status(outcome_status="callback", note="voicemail mentioned earlier",
                   callback_time_text="tomorrow evening") == "callback"
    assert _status(outcome_status="callback", note="voicemail",
                   callback_time_iso="2026-07-10T18:00:00+05:30") == "callback"


def test_genuine_member_callback_untouched():
    assert _status(outcome_status="callback", note="busy driving") == "callback"
    assert _status(outcome_status="callback") == "callback"
