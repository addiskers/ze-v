"""
EO Admin API — `/api/eo/*`. Session-gated (bearer token), COST-FREE (no gemini /
twilio / total cost anywhere). Reuses store.py / scheduler.py for calls +
callbacks; adds contacts, campaigns, and users (later phases). The Super-Admin
`/api/admin/*` endpoints are untouched and keep cost.
"""

import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import eo_auth
import eo_db
import eo_import
import scheduler
import store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/eo")

# Cost / token fields that must NEVER reach an EO user.
_CALL_COST_KEYS = {"gemini_cost_usd", "twilio", "total_cost_usd", "cost_estimated", "tokens", "gemini_model"}
_SUMMARY_COST_KEYS = {
    "total_cost_usd", "gemini_cost_usd", "twilio_cost_usd", "avg_cost_per_call",
    "projected_month_cost", "pending_twilio_price",
}


def _filters_from_request(request: Request) -> dict:
    qp = request.query_params
    return {
        "source": qp.get("source") or None,
        "from": qp.get("from") or None,
        "to": qp.get("to") or None,
        "q": qp.get("q") or None,
        "booking": qp.get("booking"),
        "campaign_id": qp.get("campaign_id") or None,
        "limit": qp.get("limit"),
        "offset": qp.get("offset"),
    }


def _strip_summary(s: dict, include_cost: bool = False) -> dict:
    """Dashboard summary. eo_admin gets cost; eo_agent gets a cost-free view."""
    s = dict(s)
    if include_cost:
        return s
    for k in _SUMMARY_COST_KEYS:
        s.pop(k, None)
    if isinstance(s.get("this_month"), dict):
        s["this_month"] = {"calls": s["this_month"].get("calls")}
    s["by_day"] = [{"date": d.get("date"), "calls": d.get("calls")} for d in s.get("by_day", [])]
    return s


def _campaign_label(call, meta_by_id):
    """Campaign name for a call — but ONLY if the call started at/after that campaign was
    created. Guards against a call record (which survived a DB reset) being mislabelled by a
    NEW campaign that reused the old campaign's numeric id."""
    cid = call.get("campaign_id")
    if not cid:
        return None
    m = meta_by_id.get(int(cid))
    if not m or (call.get("started_at") or "") < (m.get("created_at") or ""):
        return None
    return m["name"]


def _campaign_since(filters: dict) -> dict:
    """When filtering by ONE campaign, set `since` = its created_at so calls that predate it
    (stale records with a reused campaign id after a DB reset) don't show in that campaign."""
    cid = filters.get("campaign_id")
    if cid:
        camp = eo_db.get_campaign(cid)
        if camp:
            filters["since"] = camp.get("created_at")
    return filters


def _label_and_strip(items: list[dict], include_cost: bool = False) -> list[dict]:
    """Attach campaign_name; strip cost fields unless include_cost (eo_admin)."""
    meta = eo_db.campaign_meta([c.get("campaign_id") for c in items if c.get("campaign_id")])
    out = []
    for c in items:
        c = dict(c) if include_cost else {k: v for k, v in c.items() if k not in _CALL_COST_KEYS}
        c["campaign_name"] = _campaign_label(c, meta)
        c["has_recording"] = store.has_recording(c.get("call_sid"))
        out.append(c)
    return out


def _strip_full(call: dict, include_cost: bool = False) -> dict:
    """Full call record (for the transcript drawer). eo_admin keeps cost."""
    if include_cost:
        c = dict(call)
        c.setdefault("messages", c.get("transcript") or [])
        cid = c.get("campaign_id")
        if cid:
            c["campaign_name"] = _campaign_label(c, eo_db.campaign_meta([cid]))
        c["has_recording"] = store.has_recording(c.get("call_sid"))
        return c
    c = {k: v for k, v in call.items() if k not in _CALL_COST_KEYS}
    for k in ("cost", "pricing"):
        c.pop(k, None)
    if isinstance(c.get("summary"), dict):
        c["summary"] = {k: v for k, v in c["summary"].items() if k not in _SUMMARY_COST_KEYS}
    # normalise transcript key for the SPA (it reads `messages` or `transcript`)
    c.setdefault("messages", c.get("transcript") or [])
    cid = c.get("campaign_id")
    if cid:
        c["campaign_name"] = _campaign_label(c, eo_db.campaign_meta([cid]))
    c["has_recording"] = store.has_recording(c.get("call_sid"))
    return c


# ── per-role data scoping ────────────────────────────────────────────────────
def _scope_ids(user):
    """Campaign-id strings this user may see, or None for full access (eo_admin =
    Superadmin). An eo_agent (Admin) only sees campaigns they created + the calls
    from those campaigns."""
    if user["role"] == "eo_admin":
        return None
    return {str(i) for i in eo_db.campaign_ids_by_owner(user["id"])}


def _owns_or_admin(user, campaign) -> bool:
    return bool(campaign) and (user["role"] == "eo_admin" or campaign.get("created_by") == user["id"])


# ── auth ─────────────────────────────────────────────────────────────────────
@router.post("/login")
async def login(request: Request):
    body = await request.json()
    user = eo_auth.authenticate((body.get("username") or "").strip(), body.get("password") or "")
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = eo_auth.issue_token(user)
    return {"ok": True, "token": token,
            "user": {"id": user["id"], "username": user["username"], "name": user.get("name"), "role": user["role"]}}


@router.post("/logout")
async def logout(request: Request):
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = eo_auth.require_eo(request)
    return {"ok": True, "user": {"id": user["id"], "username": user["username"], "name": user.get("name"), "role": user["role"]}}


@router.post("/me/password")
async def me_password(request: Request):
    user = eo_auth.require_eo(request)
    body = await request.json()
    if not eo_auth.verify_password(body.get("current") or "", user["password_hash"], user["password_salt"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new = body.get("new") or ""
    if len(new) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    h, s = eo_auth.hash_password(new)
    eo_db.update_user_password(user["id"], h, s)
    return {"ok": True}


# ── users (eo_admin only) ────────────────────────────────────────────────────
@router.get("/users")
async def users_list(request: Request):
    eo_auth.require_eo_admin(request)
    return JSONResponse({"items": eo_db.list_users()})


@router.post("/users")
async def users_create(request: Request):
    eo_auth.require_eo_admin(request)
    body = await request.json()
    username = (body.get("username") or "").strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if eo_db.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="That username already exists")
    password = body.get("password") or ""
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    role = body.get("role") if body.get("role") in ("eo_admin", "eo_agent") else "eo_agent"
    h, s = eo_auth.hash_password(password)
    uid = eo_db.create_user(username, (body.get("name") or "").strip(), h, s, role)
    return {"ok": True, "id": uid}


@router.patch("/users/{user_id}")
async def users_update(user_id: int, request: Request):
    admin = eo_auth.require_eo_admin(request)
    body = await request.json()
    if "active" in body:
        if int(user_id) == int(admin["id"]) and not body["active"]:
            raise HTTPException(status_code=400, detail="You cannot disable your own account")
        eo_db.set_user_active(int(user_id), bool(body["active"]))
    return {"ok": True}


# ── dashboard + call logs (cost for Superadmin; Admins see only their calls) ──
@router.get("/summary")
async def eo_summary(request: Request):
    user = eo_auth.require_eo(request)
    include_cost = user["role"] == "eo_admin"
    filters = _filters_from_request(request)
    scope = _scope_ids(user)
    if scope is not None:
        filters["campaign_ids"] = scope
    return JSONResponse(_strip_summary(await store.summary(filters), include_cost))


@router.get("/calls")
async def eo_calls(request: Request):
    user = eo_auth.require_eo(request)
    include_cost = user["role"] == "eo_admin"
    filters = _campaign_since(_filters_from_request(request))
    scope = _scope_ids(user)
    if scope is not None:
        filters["campaign_ids"] = scope
    if filters.get("limit") is None:
        filters["limit"] = 500
    data = await store.list_calls(filters)
    data["items"] = _label_and_strip(data["items"], include_cost)
    return JSONResponse(data)


@router.get("/calls.csv")
async def eo_calls_csv(request: Request):
    user = eo_auth.require_eo(request)
    include_cost = user["role"] == "eo_admin"
    filters = _campaign_since(_filters_from_request(request))
    scope = _scope_ids(user)
    if scope is not None:
        filters["campaign_ids"] = scope
    filters["limit"] = None
    data = await store.list_calls(filters)
    items = _label_and_strip(data["items"], include_cost)
    buf = io.StringIO()
    cols = ["started_at", "call_sid", "source", "caller", "campaign_name",
            "duration_seconds", "language", "status", "booking_created", "rsvp_outcome_status"]
    if include_cost:
        cols += ["total_cost_usd", "gemini_cost_usd"]
    w = csv.writer(buf)
    w.writerow(cols)
    for c in items:
        w.writerow([c.get(k) for k in cols])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=call_logs.csv"})


@router.get("/calls/{call_id}")
async def eo_call_detail(call_id: str, request: Request):
    user = eo_auth.require_eo(request)
    include_cost = user["role"] == "eo_admin"
    call = await store.load_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    scope = _scope_ids(user)
    if scope is not None and str(call.get("campaign_id") or "") not in scope:
        raise HTTPException(status_code=404, detail="Call not found")
    return JSONResponse(_strip_full(call, include_cost))


@router.get("/calls/{call_id}/audio")
async def eo_call_audio(call_id: str, request: Request):
    """Stream a call's recording (WAV). Same auth + per-agent scoping as the transcript."""
    user = eo_auth.require_eo(request)
    call = await store.load_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    scope = _scope_ids(user)
    if scope is not None and str(call.get("campaign_id") or "") not in scope:
        raise HTTPException(status_code=404, detail="Call not found")
    sid = call.get("call_sid")
    if not store.has_recording(sid):
        raise HTTPException(status_code=404, detail="Recording not found")
    return FileResponse(store.recording_path(sid), media_type="audio/wav",
                        filename=f"call-{call_id}.wav")


# ── campaigns ────────────────────────────────────────────────────────────────
def _whole_int(v, name, lo, hi):
    """Accept only a whole number in [lo, hi]; reject decimals / junk with a 400."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a whole number")
    if f != int(f):
        raise HTTPException(status_code=400, detail=f"{name} must be a whole number (no decimals)")
    n = int(f)
    if n < lo or n > hi:
        raise HTTPException(status_code=400, detail=f"{name} must be between {lo} and {hi}")
    return n


def _parse_iso(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@router.get("/campaigns")
async def campaigns_list(request: Request):
    user = eo_auth.require_eo(request)
    qp = request.query_params
    data = eo_db.list_campaigns(
        q=qp.get("q") or None,
        sort=qp.get("sort") or "created_at",
        direction=qp.get("dir") or "desc",
        limit=int(qp.get("limit") or 50),
        offset=int(qp.get("offset") or 0),
        created_by=None if user["role"] == "eo_admin" else user["id"],
    )
    for c in data["items"]:
        c["progress"] = eo_db.campaign_progress(c["id"])
    return JSONResponse(data)


@router.get("/campaigns/active")
async def campaign_active(request: Request):
    user = eo_auth.require_eo(request)
    c = eo_db.active_campaign()
    if c and not _owns_or_admin(user, c):
        c = None                       # Admins only see their own live campaign
    if c:
        c["progress"] = eo_db.campaign_progress(c["id"])
    return JSONResponse({"campaign": c})


@router.get("/campaigns/{campaign_id}")
async def campaign_detail(campaign_id: int, request: Request):
    user = eo_auth.require_eo(request)
    c = eo_db.get_campaign_full(campaign_id)
    if not c or not _owns_or_admin(user, c):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return JSONResponse(c)


@router.post("/campaigns")
async def campaign_create(request: Request):
    user = eo_auth.require_eo(request)
    body = await request.json()

    # one-active-at-a-time rule
    active = eo_db.active_campaign()
    if active:
        raise HTTPException(status_code=409,
                            detail=f"Campaign '{active['name']}' is already {active['status']}. Only one campaign can be active at a time.")

    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Campaign name is required")

    start_dt = _parse_iso(body.get("start_at"))
    if not start_dt:
        raise HTTPException(status_code=400, detail="Valid start date/time is required")
    # reject past-dated campaigns (small grace for clock skew / "start now")
    if start_dt < datetime.now(timezone.utc) - timedelta(minutes=2):
        raise HTTPException(status_code=400, detail="Start time is in the past. Pick the current time or later.")

    # callback config — whole numbers only, within documented bounds
    delay_h = _whole_int(body.get("callback_delay_hours", 4), "Call-back hours", 0, 720)
    max_day = _whole_int(body.get("callback_max_per_day", 3), "Attempts per day", 1, 10)
    days = _whole_int(body.get("callback_days", 1), "Call-back days", 1, 10)

    # calling hours (the night hard-stop) — "HH:MM" IST → minutes-since-midnight
    def _hhmm(v, default):
        try:
            hh, mm = str(v).split(":")
            return max(0, min(1439, (int(hh) % 24) * 60 + (int(mm) % 60)))
        except Exception:
            return default
    call_start_min = _hhmm(body.get("call_start", "09:00"), 540)
    call_end_min = _hhmm(body.get("call_end", "21:00"), 1260)

    ids = body.get("contact_ids") or []
    contacts = [c for c in eo_db.get_contacts_by_ids(ids) if c.get("status") == "valid"]
    if not contacts:
        raise HTTPException(status_code=400, detail="Select at least one valid contact")

    now = datetime.now(timezone.utc)
    status = "live" if start_dt <= now else "scheduled"
    cid = eo_db.create_campaign(
        name=name, start_at=start_dt.astimezone(timezone.utc).isoformat(), created_by=user["id"],
        callback_delay_hours=delay_h, callback_max_per_day=max_day, callback_days=days, status=status,
        call_start_min=call_start_min, call_end_min=call_end_min,
    )
    eo_db.add_campaign_contacts(cid, contacts)
    return JSONResponse(eo_db.get_campaign_full(cid), status_code=201)


@router.post("/campaigns/{campaign_id}/cancel")
async def campaign_cancel(campaign_id: int, request: Request):
    user = eo_auth.require_eo(request)
    if not _owns_or_admin(user, eo_db.get_campaign(campaign_id)):
        raise HTTPException(status_code=404, detail="Campaign not found")
    ok = eo_db.cancel_campaign(campaign_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Campaign is not cancellable (already completed or cancelled)")
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/contacts")
async def campaign_contacts(campaign_id: int, request: Request):
    user = eo_auth.require_eo(request)
    if not _owns_or_admin(user, eo_db.get_campaign(campaign_id)):
        raise HTTPException(status_code=404, detail="Campaign not found")
    qp = request.query_params
    return JSONResponse(eo_db.list_campaign_contacts(
        campaign_id, status=qp.get("status") or None,
        limit=int(qp.get("limit") or 500), offset=int(qp.get("offset") or 0)))


@router.post("/campaigns/{campaign_id}/contacts/{cc_id}/retry")
async def campaign_contact_retry(campaign_id: int, cc_id: int, request: Request):
    """'Call now' — dial this recipient immediately (promotes a scheduled campaign to live)."""
    import campaign_runner
    user = eo_auth.require_eo(request)
    if not _owns_or_admin(user, eo_db.get_campaign(campaign_id)):
        raise HTTPException(status_code=404, detail="Campaign not found")
    res = await campaign_runner.dial_contact_now(campaign_id, cc_id)
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])
    return {"ok": True}


# ── contacts pool ────────────────────────────────────────────────────────────
@router.get("/contacts")
async def contacts_list(request: Request):
    eo_auth.require_eo(request)
    qp = request.query_params
    return JSONResponse(eo_db.list_contacts(
        q=qp.get("q") or None,
        source=qp.get("source") or None,
        status=qp.get("status") or None,
        sort=qp.get("sort") or "created_at",
        direction=qp.get("dir") or "desc",
        limit=int(qp.get("limit") or 25),
        offset=int(qp.get("offset") or 0),
    ))


@router.post("/contacts")
async def contacts_add(request: Request):
    eo_auth.require_eo(request)
    body = await request.json()
    e164, valid = eo_import.normalize_phone(body.get("phone"))
    if not e164:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    cid, created = eo_db.add_contact(
        (body.get("name") or "").strip(), e164,
        source="manual", status="valid" if valid else "invalid",
    )
    return {"ok": True, "id": cid, "created": created, "phone": e164, "valid": valid}


@router.post("/contacts/import")
async def contacts_import(request: Request, file: UploadFile = File(...)):
    eo_auth.require_eo(request)
    data = await file.read()
    try:
        rows, rejected, total = eo_import.parse_upload(file.filename, data)
    except Exception as e:
        logger.warning("Contacts import parse failed: %s", e)
        raise HTTPException(status_code=400, detail="Could not read that file. Use the sample .xlsx / .csv format.")
    added, updated = eo_db.bulk_upsert_contacts(rows, source="upload")
    invalid = sum(1 for r in rows if r[2] == "invalid")
    return {"ok": True, "rows_read": total, "added": added, "updated": updated,
            "rejected": rejected, "invalid": invalid}


@router.post("/contacts/delete")
async def contacts_delete(request: Request):
    eo_auth.require_eo(request)
    body = await request.json()
    n = eo_db.delete_contacts(body.get("ids") or [])
    return {"ok": True, "deleted": n}


@router.get("/contacts/template")
async def contacts_template(request: Request):
    eo_auth.require_eo(request)
    data = eo_import.build_template()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=contacts_template.xlsx"},
    )


# ── scheduler / callbacks (reuse super-admin logic) ──────────────────────────
@router.get("/callbacks")
async def eo_callbacks(request: Request):
    user = eo_auth.require_eo(request)
    include_cost = user["role"] == "eo_admin"
    qp = request.query_params
    statuses = set(s.strip() for s in qp["status"].split(",")) if qp.get("status") else None
    items = await store.list_callbacks(statuses)
    scope = _scope_ids(user)
    if scope is not None:
        items = [c for c in items if str(c.get("campaign_id") or "") in scope]
    items = _label_and_strip(items, include_cost)
    state = await store.load_scheduler_state()
    return JSONResponse({"items": items, "scheduler_enabled": scheduler.is_enabled(),
                         "paused_until": state.get("paused_until")})


async def _owned_callback(user, call_id):
    """Load a call that has a callback block, enforcing per-agent ownership.
    Superadmin: any. Agent: only if the call's campaign belongs to them."""
    call = await store.load_call(call_id)
    if not call or not call.get("callback"):
        raise HTTPException(status_code=404, detail="Callback not found")
    if user["role"] != "eo_admin":
        cid = call.get("campaign_id")
        if not cid or not _owns_or_admin(user, eo_db.get_campaign(cid)):
            raise HTTPException(status_code=404, detail="Callback not found")
    return call


@router.post("/callbacks/{call_id}/cancel")
async def eo_callback_cancel(call_id: str, request: Request):
    user = eo_auth.require_eo(request)
    call = await _owned_callback(user, call_id)
    call["callback"]["status"] = "cancelled"
    await store.save_call(call)
    return {"ok": True}


@router.post("/callbacks/{call_id}/call-now")
async def eo_callback_call_now(call_id: str, request: Request):
    user = eo_auth.require_eo(request)
    call = await _owned_callback(user, call_id)
    cb = call["callback"]
    if cb.get("status") in ("in_flight", "completed"):
        return {"ok": False, "error": f"callback is {cb.get('status')}"}
    cb.update({"status": "pending", "due_at": datetime.now(timezone.utc).isoformat(),
               "next_retry_at": None, "attempts": 0, "last_error": None})
    await store.save_call(call)
    return {"ok": True}


@router.post("/callbacks/{call_id}/reschedule")
async def eo_callback_reschedule(call_id: str, request: Request):
    """Change a scheduled callback's due time to a chosen future moment."""
    user = eo_auth.require_eo(request)
    call = await _owned_callback(user, call_id)
    body = await request.json()
    due = _parse_iso(body.get("due_at"))
    if not due:
        raise HTTPException(status_code=400, detail="A valid date/time is required")
    if due < datetime.now(timezone.utc) - timedelta(minutes=2):
        raise HTTPException(status_code=400, detail="Pick a time in the future")
    cb = call["callback"]
    if cb.get("status") in ("in_flight", "completed"):
        return {"ok": False, "error": f"callback is {cb.get('status')}"}
    cb.update({"status": "pending", "due_at": due.astimezone(timezone.utc).isoformat(),
               "next_retry_at": None, "last_error": None})
    await store.save_call(call)
    return {"ok": True}


@router.post("/scheduler/toggle")
async def eo_scheduler_toggle(request: Request):
    eo_auth.require_eo_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = bool(body.get("enabled", not scheduler.is_enabled()))
    scheduler.set_override(enabled)
    return {"ok": True, "enabled": enabled}
