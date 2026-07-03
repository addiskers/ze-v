"""
Campaign runner — paced outbound dialing for EO calling campaigns.

A single in-process asyncio task (one uvicorn worker), a sibling of the RSVP
callback `scheduler`. It:

  1. Promotes `scheduled` campaigns to `live` when their start time arrives.
  2. For each live campaign, PACES outbound dials: at most EO_CAMPAIGN_MAX_PER_TICK
     new dials per tick and at most EO_CAMPAIGN_MAX_CONCURRENT calls "in flight" —
     it never blasts the whole pool at once.
  3. Reaps in-flight ('calling') contacts by matching a call record (campaign_id +
     phone). Answered → `done` (with rsvp outcome); no record within the ring window
     → treated as no-answer and retried per the campaign's callback config
     (delay hours, max attempts/day, number of days) until exhausted → `failed`.
  4. Marks a campaign `completed` once no contact is pending or calling.

Isolation: it only reads/writes the campaign tables + the call index. It never
touches the RSVP `callback` blocks, so the existing callback scheduler is
unaffected. Gated by the same EO "Scheduler" toggle (scheduler.is_enabled()) plus
a master env switch, and it will not dial when Plivo credentials are absent.
"""

import asyncio
import logging
import os
from datetime import datetime, time as dtime, timedelta, timezone

import dialer
import eo_db
import scheduler
import store

logger = logging.getLogger(__name__)


def _cfg_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _enabled():
    return os.getenv("EO_CAMPAIGN_RUNNER_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def _plivo_ready():
    return bool(os.getenv("PLIVO_AUTH_ID") and os.getenv("PLIVO_AUTH_TOKEN") and os.getenv("PLIVO_FROM_NUMBER"))


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _parse(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _apply_failure(cc, campaign, now, error=None):
    """A dial attempt did not connect (dial error or no-answer). Schedule a retry
    per the campaign callback config, or mark failed when exhausted. `attempts`
    and the per-day counter are already bumped at dial time."""
    delay_h = int(campaign.get("callback_delay_hours") or 4)
    max_day = max(1, int(campaign.get("callback_max_per_day") or 3))
    days = max(1, int(campaign.get("callback_days") or 1))
    attempts = int(cc.get("attempts") or 0)
    max_total = max_day * days

    first = _parse(cc.get("created_at")) or now
    days_elapsed = (now.date() - first.date()).days

    fields = {"last_error": (error or "no answer")}
    if attempts >= max_total or days_elapsed >= days:
        fields["call_status"] = "failed"
        fields["next_attempt_at"] = None
    else:
        fields["call_status"] = "pending"
        if int(cc.get("day_attempts") or 0) >= max_day:
            # today's quota is spent → resume next calendar day
            nxt = datetime.combine(now.date() + timedelta(days=1), dtime(9, 0), tzinfo=timezone.utc)
        else:
            nxt = now + timedelta(hours=delay_h)
        fields["next_attempt_at"] = _iso(nxt)
    eo_db.cc_update(cc["id"], **fields)


async def _reap_calling(campaign, now):
    ring_window = _cfg_int("EO_CAMPAIGN_NOANSWER_SECONDS", 90)
    for cc in eo_db.cc_by_status(campaign["id"], "calling"):
        last = _parse(cc.get("last_attempt_at")) or now
        rec = await store.find_campaign_call(campaign["id"], cc["phone"], since_iso=cc.get("last_attempt_at"))
        if rec:
            if rec.get("ended_at"):
                outcome = rec.get("rsvp_outcome_status") or ("yes" if rec.get("booking_created") else None)
                eo_db.cc_update(cc["id"], call_status="done", rsvp_outcome=outcome, last_call_id=rec.get("id"))
            # else: still on the call — leave it as 'calling'
        elif (now - last).total_seconds() > ring_window:
            _apply_failure(cc, campaign, now, error="no answer")


async def _dial_one(cc, campaign, now):
    today = now.date().isoformat()
    day_attempts = (int(cc.get("day_attempts") or 0) + 1) if cc.get("day_key") == today else 1
    attempts = int(cc.get("attempts") or 0) + 1
    # claim BEFORE dialing so a crash can't double-dial silently
    eo_db.cc_update(cc["id"], call_status="calling", attempts=attempts, day_attempts=day_attempts,
                    day_key=today, last_attempt_at=_iso(now), next_attempt_at=None)
    cc = {**cc, "attempts": attempts, "day_attempts": day_attempts, "day_key": today}
    try:
        res = await asyncio.wait_for(
            dialer.place_call(cc["phone"], base_url=os.getenv("PUBLIC_URL"),
                              name=cc.get("name") or "", campaign_id=campaign["id"]),
            timeout=_cfg_int("EO_CAMPAIGN_DIAL_TIMEOUT", 60))
    except asyncio.TimeoutError:
        res = {"error": "dial timeout"}
    if res.get("success"):
        eo_db.cc_update(cc["id"], last_call_id=res.get("call_uuid"))
    else:
        _apply_failure(cc, campaign, now, error=res.get("error"))


async def _process_campaign(campaign, now):
    await _reap_calling(campaign, now)
    if eo_db.cc_open_count(campaign["id"]) == 0:
        eo_db.set_campaign_status(campaign["id"], "completed")
        logger.info(f"Campaign {campaign['id']} '{campaign['name']}' completed")
        return
    if not _plivo_ready():
        return                       # nothing to dial with (dev/local) — leave pending
    calling = len(eo_db.cc_by_status(campaign["id"], "calling"))
    budget = min(_cfg_int("EO_CAMPAIGN_MAX_PER_TICK", 3),
                 max(0, _cfg_int("EO_CAMPAIGN_MAX_CONCURRENT", 5) - calling))
    if budget <= 0:
        return
    for cc in eo_db.cc_pending_due(campaign["id"], _iso(now), budget):
        await _dial_one(cc, campaign, _now())


async def _tick():
    if not scheduler.is_enabled():        # shares the EO "Scheduler" ON/OFF toggle
        return
    now = _now()
    try:
        eo_db.promote_due_campaigns(_iso(now))
    except Exception as e:
        logger.warning(f"promote_due_campaigns failed: {e}")
    for campaign in eo_db.live_campaigns():
        try:
            await _process_campaign(campaign, _now())
        except Exception as e:
            logger.warning(f"Campaign {campaign.get('id')} tick error: {e}")


async def run_loop():
    if not _enabled():
        logger.info("Campaign runner disabled (EO_CAMPAIGN_RUNNER_ENABLED)")
        return
    interval = _cfg_int("EO_CAMPAIGN_POLL_INTERVAL", 30)
    logger.info(f"Campaign runner started (interval={interval}s, plivo_ready={_plivo_ready()})")
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            logger.info("Campaign runner loop cancelled")
            raise
        except Exception as e:
            logger.warning(f"Campaign runner tick error: {e}")
        await asyncio.sleep(interval)
