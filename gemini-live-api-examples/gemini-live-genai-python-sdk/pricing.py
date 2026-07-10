"""
Cost calculation for Voice Hero calls.

Two providers incur cost:
- Gemini Live API  -> priced from REAL measured token usage (usage_metadata) x rates.
- Twilio           -> priced from Twilio's REAL billed Call.price (fetched from the API).

All rates are env-overridable so they can be corrected without a code change.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Gemini rates (USD per 1,000,000 tokens, paid tier)
GEMINI_RATES_PER_1M = {
    "text_in":   float(os.getenv("RATE_GEMINI_TEXT_IN",   "0.75")),
    "audio_in":  float(os.getenv("RATE_GEMINI_AUDIO_IN",  "3.00")),
    "imgvid_in": float(os.getenv("RATE_GEMINI_IMGVID_IN", "1.00")),
    "text_out":  float(os.getenv("RATE_GEMINI_TEXT_OUT",  "4.50")),   # incl. thinking tokens
    "audio_out": float(os.getenv("RATE_GEMINI_AUDIO_OUT", "12.00")),
}

# Twilio fallback rate (USD per minute), used only until the real Call.price is available
TWILIO_PER_MINUTE = float(os.getenv("RATE_TWILIO_PER_MIN", "0.014"))


def _empty_tokens():
    """Zeroed token bucket structure used by a call record."""
    return {
        "text_in": 0,
        "audio_in": 0,
        "imgvid_in": 0,
        "text_out": 0,
        "audio_out": 0,
        "thoughts": 0,
        "total": 0,
    }


def compute_gemini_cost(tokens):
    """
    Real Gemini cost in USD from accumulated token buckets.

    Thinking tokens are billed at the text-output rate. The `total` bucket is
    informational only and is NOT priced (it would double count).
    """
    t = tokens or {}
    r = GEMINI_RATES_PER_1M
    cost = (
        t.get("text_in", 0)   * r["text_in"]
        + t.get("audio_in", 0)  * r["audio_in"]
        + t.get("imgvid_in", 0) * r["imgvid_in"]
        + t.get("text_out", 0)  * r["text_out"]
        + t.get("audio_out", 0) * r["audio_out"]
        + t.get("thoughts", 0)  * r["text_out"]
    ) / 1_000_000.0
    return round(cost, 6)


def gemini_cost_breakdown(tokens):
    """Per-bucket USD breakdown for the call-detail view."""
    t = tokens or {}
    r = GEMINI_RATES_PER_1M
    per = {
        "text_in":   round(t.get("text_in", 0)   * r["text_in"]   / 1e6, 6),
        "audio_in":  round(t.get("audio_in", 0)  * r["audio_in"]  / 1e6, 6),
        "imgvid_in": round(t.get("imgvid_in", 0) * r["imgvid_in"] / 1e6, 6),
        "text_out":  round(t.get("text_out", 0)  * r["text_out"]  / 1e6, 6),
        "audio_out": round(t.get("audio_out", 0) * r["audio_out"] / 1e6, 6),
        "thoughts":  round(t.get("thoughts", 0)  * r["text_out"]  / 1e6, 6),
    }
    return {"tokens": t, "rates_per_1m": r, "cost_by_bucket": per,
            "cost_usd": round(sum(per.values()), 6)}


def compute_total(call):
    """
    Total real cost for a call = Gemini cost + Twilio cost.

    Twilio cost prefers the real billed price; falls back to a per-minute
    estimate when the price has not arrived yet. Returns (total_usd, estimated).
    """
    gemini = call.get("gemini_cost_usd")
    if gemini is None:
        gemini = compute_gemini_cost(call.get("tokens"))

    twilio = call.get("twilio") or {}
    twilio_price = twilio.get("price_usd")
    estimated = bool(call.get("cost_estimated"))

    if twilio_price is None and call.get("source") == "twilio":
        # Estimate from duration until the real price is fetched.
        secs = twilio.get("duration_seconds") or call.get("duration_seconds") or 0
        twilio_price = round((secs / 60.0) * TWILIO_PER_MINUTE, 6)
        estimated = True

    total = round((gemini or 0) + (twilio_price or 0), 6)
    return total, estimated


def fetch_twilio_price(call_sid):
    """
    Fetch the REAL billed price for a Twilio call. Synchronous (Twilio SDK is
    sync) -> call this inside an executor. Returns a dict or None on failure.

    Twilio reports `price` as a negative string (a charge) and only populates
    it a few seconds AFTER the call completes, so the caller should retry while
    `price` is None.
    """
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not (sid and token and call_sid):
        return None
    try:
        from twilio.rest import Client

        call = Client(sid, token).calls(call_sid).fetch()
        price = abs(float(call.price)) if call.price else None
        return {
            "price_usd": price,
            "price_unit": call.price_unit,
            "duration_seconds": int(call.duration) if call.duration else None,
            "status": call.status,
        }
    except Exception as e:
        logger.warning(f"Twilio price fetch failed for {call_sid}: {e}")
        return None
