"""
Transfer campaign ownership (and with it, call-log visibility) to another admin.

Why: an eo_agent Admin only sees campaigns they created + those campaigns' calls.
Campaigns started while logged in as Superadmin carry created_by = NULL, so they are
invisible to every Admin. This reassigns created_by, which is all the scoping reads —
call records and campaign_contacts follow their campaign automatically; nothing else
moves or changes.

Usage (on the server, from the app directory; the app can stay up — no restart needed,
ownership is read live from eo.db on every request):

    python transfer_campaigns.py                          # dry-run: ALL campaigns -> loan_admin
    python transfer_campaigns.py --apply                  # back up eo.db, then transfer
    python transfer_campaigns.py --to someuser --apply    # different target admin

Selectors (combine freely):
  --to loan_admin        target username (default: loan_admin)
  --from someuser        only campaigns currently owned by this username
                         (special value "superadmin" = unassigned/NULL owner)
  --campaign NAME        only this campaign, exact name match, case-insensitive (repeatable)
  --with-contacts        also move the source owners' contacts-pool rows to the target
                         (rows whose phone the target already has are skipped)

Safety: with no --apply it only PRINTS what would change. With --apply it first writes
a consistent eo.db snapshot under DATA_DIR/backups/ (sqlite backup API — valid even
while the app is writing), then updates.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

DATA_DIR = os.getenv("DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CALLS_DIR = os.path.join(DATA_DIR, "calls")
DB_PATH = os.path.join(DATA_DIR, "eo.db")


def backup_db(dest_dir):
    """Consistent eo.db snapshot via the sqlite backup API (only the DB changes here,
    so no need for the full tar.gz that cleanup_test_data.py takes)."""
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    out = os.path.join(dest_dir, f"eo-db-backup-{stamp}.sqlite")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(out)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return out


def call_counts_by_campaign(camp_ids):
    """campaign_id -> number of call JSONs carrying it (report only; calls never change)."""
    counts = {cid: 0 for cid in camp_ids}
    if not os.path.isdir(CALLS_DIR):
        return counts
    for name in os.listdir(CALLS_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(CALLS_DIR, name), "r", encoding="utf-8") as f:
                cid = json.load(f).get("campaign_id")
        except Exception:
            continue
        if cid in counts:
            counts[cid] += 1
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", default="loan_admin", help="target username (default: loan_admin)")
    ap.add_argument("--from", dest="frm", default=None,
                    help="only campaigns owned by this username ('superadmin' = unassigned)")
    ap.add_argument("--campaign", action="append", default=[],
                    help="campaign name, exact match, case-insensitive (repeatable)")
    ap.add_argument("--with-contacts", action="store_true",
                    help="also move source owners' contacts-pool rows to the target")
    ap.add_argument("--apply", action="store_true", help="actually update (default: dry-run print only)")
    args = ap.parse_args()

    if not os.path.isfile(DB_PATH):
        sys.exit(f"eo.db not found at {DB_PATH} — is DATA_DIR right? (DATA_DIR={DATA_DIR})")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    users = {r["id"]: r for r in conn.execute("SELECT * FROM users")}
    by_username = {(r["username"] or "").lower(): r for r in users.values()}

    target = by_username.get(args.to.lower())
    if not target:
        sys.exit(f"No user named '{args.to}'. Users: " + ", ".join(sorted(by_username)))
    if not target["active"]:
        sys.exit(f"User '{args.to}' is deactivated — reactivate them first (Users page).")
    if target["role"] == "eo_admin":
        print(f"NOTE: '{args.to}' is a Superadmin and already sees every campaign; "
              f"transferring anyway (makes them the listed owner).")

    def owner_name(uid):
        if uid is None:
            return "Superadmin (unassigned)"
        u = users.get(uid)
        return u["username"] if u else f"deleted user #{uid}"

    campaigns = list(conn.execute("SELECT * FROM campaigns ORDER BY id"))
    picked = [c for c in campaigns if c["created_by"] != target["id"]]

    if args.frm:
        if args.frm.lower() == "superadmin":
            picked = [c for c in picked if c["created_by"] is None
                      or (users.get(c["created_by"]) or {"role": ""})["role"] == "eo_admin"]
        else:
            src = by_username.get(args.frm.lower())
            if not src:
                sys.exit(f"No user named '{args.frm}'. Users: " + ", ".join(sorted(by_username)))
            picked = [c for c in picked if c["created_by"] == src["id"]]

    if args.campaign:
        names = {n.strip().lower() for n in args.campaign if n.strip()}
        picked = [c for c in picked if (c["name"] or "").strip().lower() in names]
        missing = names - {(c["name"] or "").strip().lower() for c in picked}
        for m in sorted(missing):
            print(f"NOTE: no matching campaign named '{m}' — skipping that name")

    # Contacts pool (optional): rows owned by the campaigns' current owners (or the
    # --from user), minus phones the target already has (UNIQUE(created_by, phone)).
    pool_moves, pool_skips = [], []
    if args.with_contacts:
        src_ids = {c["created_by"] for c in picked}          # may include None (Superadmin)
        target_phones = {r["phone"] for r in conn.execute(
            "SELECT phone FROM contacts WHERE created_by = ?", (target["id"],))}
        for r in conn.execute("SELECT * FROM contacts"):
            if r["created_by"] == target["id"] or r["created_by"] not in src_ids:
                continue
            (pool_skips if r["phone"] in target_phones else pool_moves).append(r)

    # Report
    counts = call_counts_by_campaign({c["id"] for c in picked})
    print(f"\nDATA_DIR: {DATA_DIR}")
    print(f"Target: {target['username']} (id={target['id']}, role={target['role']})")
    print(f"\nCampaigns to transfer ({len(picked)}):")
    for c in picked:
        print(f"  [{c['id']}] {c['name']}  status={c['status']}  contacts={c['contact_count']}  "
              f"calls={counts[c['id']]}  owner: {owner_name(c['created_by'])} -> {target['username']}")
    if args.with_contacts:
        print(f"\nContacts-pool rows to move ({len(pool_moves)}):")
        for r in pool_moves:
            print(f"  [{r['id']}] {r['name']}  {r['phone']}  owner: {owner_name(r['created_by'])}")
        if pool_skips:
            print(f"Skipped — {target['username']} already has these phones ({len(pool_skips)}):")
            for r in pool_skips:
                print(f"  [{r['id']}] {r['name']}  {r['phone']}")
    else:
        print("\nContacts pool: untouched (pass --with-contacts to move those too)")

    if not picked and not pool_moves:
        print("\nNothing matched — nothing to do.")
        return

    if not args.apply:
        print("\nDRY RUN — nothing changed. Re-run with --apply to back up and transfer.")
        return

    out = backup_db(os.path.join(DATA_DIR, "backups"))
    print(f"\nBackup written: {out}")

    now = datetime.now(timezone.utc).isoformat()
    with conn:
        if picked:
            conn.executemany("UPDATE campaigns SET created_by = ?, updated_at = ? WHERE id = ?",
                             [(target["id"], now, c["id"]) for c in picked])
        if pool_moves:
            conn.executemany("UPDATE contacts SET created_by = ?, updated_at = ? WHERE id = ?",
                             [(target["id"], now, r["id"]) for r in pool_moves])
    conn.close()

    print(f"Transferred {len(picked)} campaigns"
          + (f" and {len(pool_moves)} pool contacts" if pool_moves else "")
          + f" to {target['username']}. No restart needed — scoping reads eo.db live.")


if __name__ == "__main__":
    main()
