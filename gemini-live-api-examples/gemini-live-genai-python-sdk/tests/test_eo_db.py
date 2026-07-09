"""eo_db.py — per-user contacts: legacy migration, (owner, phone) upsert, scoped access."""


def _seed_users(eo_db):
    admin = eo_db.create_user("admin", "Admin", "h", "s", role="eo_admin")
    agent = eo_db.create_user("agent", "Agent", "h", "s", role="eo_agent")
    return admin, agent


def test_legacy_contacts_migrate_to_seed_admin(fresh_eo_db):
    eo_db = fresh_eo_db
    conn = eo_db.get_conn()
    # Build the PRE-migration world by hand: legacy contacts table (phone UNIQUE, no
    # created_by/remark) + a users table with the seed admin.
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, name TEXT,
            password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'eo_admin', active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL DEFAULT 'upload', status TEXT NOT NULL DEFAULT 'valid',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO users (username, name, password_hash, password_salt, role, active, created_at, updated_at)
            VALUES ('eoadmin', 'EO', 'h', 's', 'eo_admin', 1, 't', 't');
        INSERT INTO contacts (name, phone, created_at, updated_at) VALUES ('Rohan', '+919824018000', 't', 't');
        INSERT INTO contacts (name, phone, created_at, updated_at) VALUES ('Percy', '+919824094215', 't', 't');
    """)
    conn.commit()

    eo_db.init()                                     # runs the rebuild migration
    admin_id = eo_db.get_user_by_username("eoadmin")["id"]
    rows = eo_db.list_contacts(created_by=None)["items"]
    assert len(rows) == 2
    assert all(r["created_by"] == admin_id for r in rows)

    eo_db.init()                                     # idempotent — second run is a no-op
    assert eo_db.count_contacts() == 2


def test_same_phone_lives_in_two_pools_and_upserts_within_one(fresh_eo_db):
    eo_db = fresh_eo_db
    eo_db.init()
    admin, agent = _seed_users(eo_db)

    id_a, created_a = eo_db.add_contact("Raj", "+919825227503", created_by=admin)
    id_b, created_b = eo_db.add_contact("Raj bhai", "+919825227503", created_by=agent)
    assert created_a and created_b and id_a != id_b   # per-owner pools

    id_a2, created_a2 = eo_db.add_contact("Raj Updated", "+919825227503", created_by=admin)
    assert id_a2 == id_a and created_a2 is False      # same-pool upsert, no duplicate

    assert eo_db.count_contacts(created_by=admin) == 1
    assert eo_db.count_contacts(created_by=agent) == 1


def test_bulk_upsert_counts_and_conflicts_per_owner(fresh_eo_db):
    eo_db = fresh_eo_db
    eo_db.init()
    admin, agent = _seed_users(eo_db)

    added, updated = eo_db.bulk_upsert_contacts(
        [("A", "+919000000001", "valid"), ("B", "+919000000002", "valid")], created_by=agent)
    assert (added, updated) == (2, 0)
    added, updated = eo_db.bulk_upsert_contacts(
        [("A2", "+919000000001", "valid"), ("C", "+919000000003", "valid")], created_by=agent)
    assert (added, updated) == (1, 1)
    # the ADMIN importing the same phone lands in the admin pool, not the agent's
    added, _ = eo_db.bulk_upsert_contacts([("A", "+919000000001", "valid")], created_by=admin)
    assert added == 1
    assert eo_db.count_contacts(created_by=agent) == 3


def test_scoped_get_delete_and_list(fresh_eo_db):
    eo_db = fresh_eo_db
    eo_db.init()
    admin, agent = _seed_users(eo_db)
    id_admin, _ = eo_db.add_contact("AdminC", "+919000000010", created_by=admin)
    id_agent, _ = eo_db.add_contact("AgentC", "+919000000011", created_by=agent)

    # the IDOR fix: an agent asking for the admin's contact id gets nothing
    assert eo_db.get_contacts_by_ids([id_admin], created_by=agent) == []
    assert len(eo_db.get_contacts_by_ids([id_admin, id_agent], created_by=agent)) == 1
    assert len(eo_db.get_contacts_by_ids([id_admin, id_agent], created_by=None)) == 2

    # scoped delete: the agent cannot delete the admin's row
    assert eo_db.delete_contacts([id_admin], created_by=agent) == 0
    assert eo_db.delete_contacts([id_agent], created_by=agent) == 1
    assert eo_db.count_contacts() == 1

    assert eo_db.list_contacts(created_by=agent)["total"] == 0
    assert eo_db.list_contacts(created_by=None)["total"] == 1


def test_contact_remark_setter(fresh_eo_db):
    eo_db = fresh_eo_db
    eo_db.init()
    admin, _ = _seed_users(eo_db)
    cid, _ = eo_db.add_contact("R", "+919000000020", created_by=admin)
    eo_db.set_contact_remark(cid, "VIP member")
    assert eo_db.get_contact(cid)["remark"] == "VIP member"
