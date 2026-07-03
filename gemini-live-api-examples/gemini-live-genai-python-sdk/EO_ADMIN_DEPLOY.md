# EO AI Calling Platform — deploy notes

The EO admin platform is added **on top of** the existing GvoxAi app. Nothing about the
demo changes: `GET /` and the browser `/ws` stay exactly as-is.

## What runs where (all coexist)
| URL           | What it is                                   | Auth                          | Cost shown |
|---------------|----------------------------------------------|-------------------------------|------------|
| `/`           | Public RSVP **demo** (unchanged)             | none                          | —          |
| `/admin`      | **EO admin** React SPA (new)                 | EO user login (per-user)      | **never**  |
| `/superadmin` | Old vanilla admin (was `/admin`, URL rename) | shared secret `ANALYTICS_SECRET` | yes     |

## New Python deps
`requirements.txt` gained **`openpyxl`** (Excel import/template). Install:
```bash
pip install -r requirements.txt
```

## Build the SPA (Node 18+)
```bash
cd admin
npm install
npm run build      # emits admin/dist/, which FastAPI serves at /admin/*
```
FastAPI serves `admin/dist` automatically if present; if it's missing, `/admin` returns a
503 telling you to build. Re-run `npm run build` after any SPA change.

## Environment variables
Existing vars (Plivo, `PUBLIC_URL`, `GEMINI_API_KEY`, `ANALYTICS_SECRET`, `CALLBACK_*`) are
unchanged. New optional vars:

| Var | Default | Purpose |
|-----|---------|---------|
| `EO_ADMIN_USER` | `eoadmin` | Username of the first EO admin, seeded **only if the users table is empty**. |
| `EO_ADMIN_PASS` | `eoadmin123` | Password for that seed user. **Change in prod**, then change again from the Profile page. |
| `EO_SESSION_SECRET` | falls back to `ANALYTICS_SECRET` | HMAC key for EO login tokens (14-day expiry). |
| `EO_CAMPAIGN_RUNNER_ENABLED` | `true` | Master switch for the campaign dialer loop. |
| `EO_CAMPAIGN_MAX_CONCURRENT` | `5` | Max simultaneous campaign calls in flight. |
| `EO_CAMPAIGN_MAX_PER_TICK` | `3` | New campaign dials started per 30s tick (pacing). |
| `EO_CAMPAIGN_POLL_INTERVAL` | `30` | Runner tick interval (seconds). |
| `EO_CAMPAIGN_NOANSWER_SECONDS` | `90` | Ring window before a dial with no call record counts as no-answer. |

The EO "Scheduler: ON/OFF" toggle (Dashboard/Scheduler pages) controls **both** the RSVP
callback scheduler and the campaign runner — OFF pauses all outbound dialing.

## Data
- SQLite DB `eo.db` (users, contacts, campaigns, campaign_contacts) is created next to the JSON
  call store under `DATA_DIR`, auto-migrated on startup. Back it up with the rest of `DATA_DIR`.
- Calls stay JSON files; each campaign dial's record carries a `campaign_id` for per-campaign logs.

## Run (single worker — required)
The in-process callback scheduler **and** campaign runner assume ONE uvicorn worker (as today):
```bash
python main.py            # or: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
```
On boot you should see: `Callback scheduler started` **and** `Campaign runner started`.

## First login
Go to `https://eo.globalvoxinc.com/admin`, sign in with `EO_ADMIN_USER` / `EO_ADMIN_PASS`,
then create the real users from the **Users** page and change the seed password from **Profile**.

---

## Docker deployment (recommended — matches the gvox setup)
Files: `Dockerfile` (multi-stage: builds the SPA with Node, then runs uvicorn on Python),
`docker-compose.yml` (one service, `127.0.0.1:8000`, persistent `eo-data` volume for `eo.db` +
call logs), `.dockerignore`. The container runs **one** uvicorn worker.

**On the server (in this app directory):**
```bash
cp .env.example .env          # then edit .env — see below
docker compose up -d --build  # build image + start
docker compose logs -f        # expect "Callback scheduler started" + "Campaign runner started"
```

**`.env` must set (real values):**
- `PUBLIC_URL=https://eo.globalvoxinc.com`  ← REQUIRED (Plivo fetches /plivo/answer here)
- `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` / `PLIVO_FROM_NUMBER`, `GEMINI_API_KEY`, `MODEL`
- `EO_ADMIN_USER` / `EO_ADMIN_PASS`, `EO_SESSION_SECRET` (long random), `ANALYTICS_SECRET`
- leave `DATA_DIR` blank — compose sets it to `/var/eo-data` (the persistent volume)

**HTTPS via the host Caddy** (same pattern as gvox — add to the Caddyfile, then `caddy reload`):
```
eo.globalvoxinc.com {
    reverse_proxy localhost:8000
}
```
Point the `eo.globalvoxinc.com` DNS A record at the server IP; Caddy auto-provisions the TLS cert.

**Update after code changes:**
```bash
git pull
docker compose up -d --build   # rebuilds SPA + app; the eo-data volume persists
```
The `eo-data` volume survives rebuilds, so users/contacts/campaigns/call-logs are never lost.
