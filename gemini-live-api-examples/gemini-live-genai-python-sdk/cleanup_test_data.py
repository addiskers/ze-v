"""
Backup-first removal of test data from DATA_DIR (call JSONs, recordings, eo.db rows).

Selectors (combine freely; each may repeat):
  --phone +916355412603      remove call records (incl. their callback blocks) and
                             recordings for this number, plus its campaign_contacts rows
  --campaign test-again      remove this campaign (exact name, case-insensitive), its
                             campaign_contacts, and every call that carries its id
  --purge-contact            also delete the --phone number(s) from the contacts pool

Safety: with no --apply it only PRINTS what would be deleted. With --apply it first
writes a full backup tar.gz (consistent eo.db snapshot via the sqlite backup API, plus
calls/, recordings/, scheduler_state.json) under DATA_DIR/backups/, then deletes.

Run it on the server from the app directory (the app can stay up, but restart it
afterwards — the call store keeps an in-memory index that only reloads on boot):

    python cleanup_test_data.py --phone +916355412603 \
        --campaign TEST --campaign test-again --campaign test-again-2 --campaign test-again-3
    python cleanup_test_data.py <same args> --apply
    sudo systemctl restart eo
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

DATA_DIR = os.getenv("DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CALLS_DIR = os.path.join(DATA_DIR, "calls")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
DB_PATH = os.path.join(DATA_DIR, "eo.db")


def digits(s):
    """Phone comparison key: digits only, so +91 63554..., 9163554... and spaces all match."""
    return re.sub(r"\D", "", str(s or ""))


def backup(dest_dir):
    """Consistent snapshot of DATA_DIR -> tar.gz. eo.db is copied with the sqlite
    backup API so the archive is valid even while the app is writing."""
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    out = os.path.join(dest_dir, f"eo-data-backup-{stamp}.tar.gz")
    with tempfile.TemporaryDirectory() as tmp:
        db_snap = os.path.join(tmp, "eo.db")
        if os.path.isfile(DB_PATH):
            src = sqlite3.connect(DB_PATH)
            dst = sqlite3.connect(db_snap)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        with tarfile.open(out, "w:gz") as tar:
            if os.path.isfile(db_snap):
                tar.add(db_snap, arcname="eo.db")
            for name in ("calls", "recordings"):
                p = os.path.join(DATA_DIR, name)
                if os.path.isdir(p):
                    tar.add(p, arcname=name)
            for name in ("scheduler_state.json", "members.csv"):
                p = os.path.join(DATA_DIR, name)
                if os.path.isfile(p):
                    tar.add(p, arcname=name)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phone", action="append", default=[], help="phone number to purge (repeatable)")
    ap.add_argument("--campaign", action="append", default=[], help="campaign name to purge, exact match (repeatable)")
    ap.add_argument("--purge-contact", action="store_true", help="also remove --phone numbers from the contacts pool")
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run print only)")
    args = ap.parse_args()

    if not args.phone and not args.campaign:
        ap.error("nothing selected — pass --phone and/or --campaign")

    phone_keys = {digits(p) for p in args.phone if digits(p)}
    camp_names = {c.strip().lower() for c in args.campaign if c.strip()}

    if not os.path.isfile(DB_PATH):
        sys.exit(f"eo.db not found at {DB_PATH} — is DATA_DIR right? (DATA_DIR={DATA_DIR})")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Resolve campaigns by name
    campaigns = [r for r in conn.execute("SELECT * FROM campaigns")
                 if (r["name"] or "").strip().lower() in camp_names]
    camp_ids = {r["id"] for r in campaigns}
    missing = camp_names - {(r["name"] or "").strip().lower() for r in campaigns}
    for m in sorted(missing):
        print(f"NOTE: no campaign named '{m}' found — skipping that name")

    # Collect call JSONs to delete
    doomed_calls = []           # (path, call_sid, caller, campaign_id, started_at)
    if os.path.isdir(CALLS_DIR):
        for name in sorted(os.listdir(CALLS_DIR)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(CALLS_DIR, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    call = json.load(f)
            except Exception as e:
                print(f"NOTE: skipping unreadable {name}: {e}")
                continue
            by_phone = digits(call.get("caller")) in phone_keys
            by_camp = call.get("campaign_id") in camp_ids
            if by_phone or by_camp:
                doomed_calls.append((path, call.get("call_sid"), call.get("caller"),
                                     call.get("campaign_id"), call.get("started_at")))

    recordings = []
    for _, sid, *_ in doomed_calls:
        p = os.path.join(RECORDINGS_DIR, f"{sid}.wav") if sid else None
        if p and os.path.isfile(p):
            recordings.append(p)

    # Collect DB rows
    cc_rows = [r for r in conn.execute("SELECT * FROM campaign_contacts")
               if r["campaign_id"] in camp_ids or digits(r["phone"]) in phone_keys]
    pool_rows = ([r for r in conn.execute("SELECT * FROM contacts")
                  if digits(r["phone"]) in phone_keys] if args.purge_contact else [])

    # Report
    print(f"\nDATA_DIR: {DATA_DIR}")
    print(f"\nCampaigns to delete ({len(campaigns)}):")
    for r in campaigns:
        print(f"  [{r['id']}] {r['name']}  status={r['status']}  contacts={r['contact_count']}")
    print(f"\nCampaign contact rows to delete ({len(cc_rows)}):")
    for r in cc_rows:
        print(f"  [{r['id']}] campaign={r['campaign_id']}  {r['name']}  {r['phone']}  "
              f"{r['call_status']}  attempts={r['attempts']}")
    print(f"\nCall records to delete ({len(doomed_calls)}) — includes their callback entries:")
    for path, sid, caller, cid, started in doomed_calls:
        print(f"  {os.path.basename(path)}  {caller}  campaign={cid or '—'}  {started or ''}")
    print(f"\nRecordings to delete ({len(recordings)}):")
    for p in recordings:
        print(f"  {os.path.basename(p)}")
    if args.purge_contact:
        print(f"\nContacts-pool rows to delete ({len(pool_rows)}):")
        for r in pool_rows:
            print(f"  [{r['id']}] {r['name']}  {r['phone']}")
    else:
        print("\nContacts pool: untouched (pass --purge-contact to remove the number there too)")

    if not (campaigns or cc_rows or doomed_calls or pool_rows):
        print("\nNothing matched — nothing to do.")
        return

    if not args.apply:
        print("\nDRY RUN — nothing deleted. Re-run with --apply to back up and delete.")
        return

    # Backup, then delete
    out = backup(os.path.join(DATA_DIR, "backups"))
    print(f"\nBackup written: {out}")

    with conn:
        conn.execute("PRAGMA foreign_keys=ON")
        if cc_rows:
            conn.executemany("DELETE FROM campaign_contacts WHERE id = ?",
                             [(r["id"],) for r in cc_rows])
        if campaigns:
            conn.executemany("DELETE FROM campaigns WHERE id = ?",
                             [(r["id"],) for r in campaigns])
        if pool_rows:
            conn.executemany("DELETE FROM contacts WHERE id = ?",
                             [(r["id"],) for r in pool_rows])
    conn.close()

    for path, *_ in doomed_calls:
        os.remove(path)
    for p in recordings:
        os.remove(p)

    print(f"Deleted: {len(campaigns)} campaigns, {len(cc_rows)} campaign contacts, "
          f"{len(doomed_calls)} call records, {len(recordings)} recordings"
          + (f", {len(pool_rows)} pool contacts" if pool_rows else "") + ".")
    print("Restart the app now (the call store's in-memory index reloads on boot): "
          "sudo systemctl restart eo   # or: docker compose restart")


if __name__ == "__main__":
    main()
