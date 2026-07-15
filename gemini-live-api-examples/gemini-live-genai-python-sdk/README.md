# Zenon — AI Loan Tele-calling Platform

A real-time **AI tele-calling platform** built on the Gemini Live API
([Google Gen AI Python SDK](https://github.com/googleapis/python-genai) backend). **Aria**, a warm,
natural-sounding voice agent, calls customers **on behalf of Jio Financial** to discuss loan offers,
answer questions, and capture the customer's response — speaking **Hindi, English, or Gujarati** as
the conversation demands. Calls can run **in the browser** (caller UI) or be placed to a **real
phone via Plivo**.

The FastAPI backend proxies the browser/phone audio to Gemini Live, records each call, schedules
callbacks and campaign dials, and tracks token + telephony cost. A React **admin panel** manages
users, contacts, campaigns, and call logs.

## Quick Start

```bash
# 1. Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt

# 2. Set your Gemini API key (a .env file is easiest — see .env.example)
echo "GEMINI_API_KEY=your_api_key_here" > .env

# 3. Start the server
uv run main.py

# 4. Open the caller UI and click "Start the call" (allow the microphone)
#    http://localhost:8000
```

## How it works

1. **Caller UI** — open `/` for a browser call, or use the admin panel / `POST /call-me` to have
   Aria dial a customer's phone via Plivo.
2. **Aria greets first** — on connect she introduces herself, states she's calling on behalf of
   Jio Financial, and opens the loan conversation.
3. **The customer answers by voice** — Aria responds naturally (Hindi/English/Gujarati), handles
   questions and objections, and silently records the outcome via a tool call.
4. **Live transcript** — phone calls can be watched in real time at `/live`.
5. **Call records** — every call is logged with outcome, duration, transcript, recording, and cost,
   viewable in the admin panel.

## Customising

| What | Where |
| --- | --- |
| Aria's persona / script | `SYSTEM_INSTRUCTION` in `gemini_live.py` |
| Voice | `voice_name=` in `gemini_live.py` (`start_session`) |
| Accent / language | `language_code=` in `gemini_live.py` |
| Model id | `MODEL` in `.env` (default `gemini-3.1-flash-live-preview`) |
| Outcome tool (legacy name `record_rsvp`) | declaration in `gemini_live.py` + handler in `main.py` |
| Caller UI branding / theme | `frontend/index.html`, `frontend/style.css` |
| Call behaviour, VAD tuning, calling hours | env vars in `.env.example` (`EO_*` keys — legacy prefix, read by code) |

## Endpoints

| Route | Purpose |
| --- | --- |
| `GET /` | The caller UI (browser call) |
| `WS /ws` | Browser call (proxied to Gemini Live) |
| `POST /call-me` | Place an outbound Plivo call to a phone number |
| `GET/POST /plivo/answer`, `WS /plivo/media-stream` | Plivo phone-call bridge |
| `GET /live`, `WS /live/ws` | Live transcript viewer for phone calls |
| `GET /admin` | Zenon admin React SPA (per-user login) |
| `GET /superadmin` (+ `/api/admin/*`) | Legacy dashboard: call logs + token/telephony cost (key = `ANALYTICS_SECRET`) |

## Configuration

Set values via environment variables or a `.env` file (see `.env.example`). At minimum set
`GEMINI_API_KEY`. For the phone path, set the `PLIVO_*` values and a public `PUBLIC_URL` so Plivo
can reach `/plivo/answer`.

Note: many env var keys keep their legacy `EO_` prefix (`EO_ADMIN_USER`, `EO_VAD_*`,
`EO_HOLD_GRACE_SECONDS`, …). These names are read by code — do **not** rename them; only their
values are configurable.

## Deployment

See `EO_ADMIN_DEPLOY.md` for the Docker Compose deployment notes (single-worker uvicorn, persistent
data volume, reverse proxy).

## Project structure
```
/
├── main.py            # FastAPI server: /ws, Plivo webhooks, /call-me, /live, /admin, /superadmin
├── gemini_live.py     # Gemini Live wrapper: Aria's persona, tools, voice/language
├── plivo_handler.py   # Plivo phone-call bridge
├── recorder.py        # Per-call recording (outcome flag)
├── dialer.py, scheduler.py, callbacks.py, campaign_runner.py   # outbound dialing + campaigns
├── store.py, pricing.py                                        # call store + cost tracking
├── eo_db.py, eo_api.py, eo_auth.py, eo_import.py               # admin platform (SQLite, API, auth, Excel import)
├── frontend/          # Caller UI (index.html, style.css, main.js, audio transport)
└── admin/             # Zenon admin React SPA (built to admin/dist, served at /admin)
```
