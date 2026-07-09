"""Name + number search across call grids and campaign recipients."""

import asyncio
from datetime import datetime, timezone

import store


def _call(call_id, caller, **over):
    c = {"id": call_id, "call_sid": f"sid-{call_id}", "source": "plivo", "caller": caller,
         "campaign_id": None, "started_at": datetime.now(timezone.utc).isoformat(),
         "ended_at": None, "status": "completed", "booking_created": False,
         "transcript": [], "tool_calls": []}
    c.update(over)
    return c


def test_q_matches_phone_with_spaces_and_dashes():
    meta = store._meta_from_call(_call("s1", "+919824018000"))
    assert store._matches(meta, {"q": "98240 18000"}) is True
    assert store._matches(meta, {"q": "98240-18000"}) is True
    assert store._matches(meta, {"q": "9824018000"}) is True
    assert store._matches(meta, {"q": "9999999999"}) is False


def test_q_matches_by_contact_name_via_q_phones():
    meta = store._meta_from_call(_call("s2", "+919824094215"))
    # the API resolves "percy" -> the phones whose contact name matches, passed as q_phones
    assert store._matches(meta, {"q": "percy", "q_phones": {"+919824094215"}}) is True
    assert store._matches(meta, {"q": "percy", "q_phones": set()}) is False
    assert store._matches(meta, {"q": "percy"}) is False   # no resolution → no match


def test_phones_by_name_query_spans_pool_and_campaign_names(fresh_eo_db):
    eo_db = fresh_eo_db
    eo_db.init()
    admin = eo_db.create_user("admin", "Admin", "h", "s", role="eo_admin")
    eo_db.add_contact("Percy Mehta", "+919824094215", created_by=admin)
    cid = eo_db.create_campaign("C", datetime.now(timezone.utc).isoformat(), admin, 4, 3, 1)
    eo_db.add_campaign_contacts(cid, [{"id": None, "phone": "+919825227503", "name": "Raj Shah"}])

    assert eo_db.phones_by_name_query("percy") == {"+919824094215"}
    assert eo_db.phones_by_name_query("raj") == {"+919825227503"}   # campaign-only name
    assert eo_db.phones_by_name_query("nobody") == set()
    assert eo_db.phones_by_name_query("") == set()


def test_list_campaign_contacts_q_filters_name_and_phone(fresh_eo_db):
    eo_db = fresh_eo_db
    eo_db.init()
    admin = eo_db.create_user("admin", "Admin", "h", "s", role="eo_admin")
    cid = eo_db.create_campaign("C", datetime.now(timezone.utc).isoformat(), admin, 4, 3, 1)
    eo_db.add_campaign_contacts(cid, [
        {"id": None, "phone": "+919824018000", "name": "Rohan"},
        {"id": None, "phone": "+919824077288", "name": "Chiranjiv"},
    ])
    assert [c["name"] for c in eo_db.list_campaign_contacts(cid, q="rohan")["items"]] == ["Rohan"]
    assert [c["name"] for c in eo_db.list_campaign_contacts(cid, q="77288")["items"]] == ["Chiranjiv"]
    assert eo_db.list_campaign_contacts(cid, q="zzz")["total"] == 0
    assert eo_db.list_campaign_contacts(cid)["total"] == 2
