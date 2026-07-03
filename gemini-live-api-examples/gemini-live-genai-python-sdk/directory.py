"""
Member directory — maps a phone number (E.164) to the member's first name so the
agent can greet them personally ("Hello Pratik!").

Loaded lazily from a data file (CSV or JSON) at MEMBER_DIRECTORY_PATH
(default: data/members.csv). Pure stdlib, no app imports, never raises — an unknown
number or a missing file simply yields "" (the agent then falls back to "Hello!").

CSV shape (header required):
    phone,first_name
    +919876543210,Pratik

JSON shape (either form):
    {"+919876543210": "Pratik"}
    [{"phone": "+919876543210", "first_name": "Pratik"}]

The file is PII — keep it out of version control and do not expose names on the
public /live dashboard.
"""

import csv
import json
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "members.csv")

_LOCK = threading.Lock()
_MAP = None            # normalized phone -> first name (None until first load)
_MISSING_LOGGED = False


def normalize_phone(raw):
    """Normalise a phone number for exact matching.

    Strips spaces/dashes/parens/dots, keeps a single leading '+', and defaults a
    bare 10-digit Indian mobile to +91. Returns '' for anything without digits.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if plus:
        return "+" + digits
    if len(digits) == 10:                 # bare Indian mobile
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return "+" + digits


def _path():
    return os.getenv("MEMBER_DIRECTORY_PATH") or _DEFAULT_PATH


def _load(path):
    """Read the directory file into a {normalized_phone: first_name} dict."""
    out = {}
    _, ext = os.path.splitext(path.lower())
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        if ext == ".json":
            data = json.load(f)
            items = data.items() if isinstance(data, dict) else (
                ((row.get("phone"), row.get("first_name")) for row in data))
            for phone, name in items:
                key = normalize_phone(phone)
                if key and name:
                    out[key] = str(name).strip()
        else:
            for row in csv.DictReader(f):
                # tolerate header variants: phone/number, first_name/name
                phone = row.get("phone") or row.get("number") or row.get("mobile")
                name = row.get("first_name") or row.get("name") or row.get("firstname")
                key = normalize_phone(phone)
                if key and name:
                    out[key] = str(name).strip()
    return out


def _ensure_loaded():
    global _MAP, _MISSING_LOGGED
    if _MAP is not None:
        return _MAP
    with _LOCK:
        if _MAP is not None:
            return _MAP
        path = _path()
        try:
            _MAP = _load(path)
            logger.info(f"Member directory loaded from {path} ({len(_MAP)} members)")
        except FileNotFoundError:
            if not _MISSING_LOGGED:
                logger.info(f"Member directory not found at {path}; greetings will be generic")
                _MISSING_LOGGED = True
            _MAP = {}
        except Exception as e:
            logger.warning(f"Failed to load member directory {path}: {e}")
            _MAP = {}
    return _MAP


def first_name_for(phone):
    """Return the member's first name for a phone number, or '' if unknown.

    Exact match only (never fuzzy) — a wrong name on a premium invite is worse
    than no name.
    """
    key = normalize_phone(phone)
    if not key:
        return ""
    return _ensure_loaded().get(key, "")


def reload():
    """Drop the cache so the next lookup re-reads the file (e.g. after an edit)."""
    global _MAP, _MISSING_LOGGED
    with _LOCK:
        _MAP = None
        _MISSING_LOGGED = False
