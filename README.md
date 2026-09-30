# Routebook

Tour & travel OTA CRM (FastAPI + SQLite) for domestic and international desk work.

**Public companion repo:** https://github.com/jaiswalhermes/routebook  
(If that name is taken on create, use `routebook-crm` instead and update this URL.)

**Sample Western markets catalog — replace with your packages.** Seed packages/guests are demo data labeled `[SAMPLE]` / `[DEMO]` (Hawaii, California, Iceland, Greek islands, NYC / New England). No live database is shipped; an empty install recreates the demo SQLite DB on first run.

## Run

```bash
git clone https://github.com/jaiswalhermes/routebook.git
cd routebook
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# optional branding — see .env.example
# export AGENCY_NAME="Your Agency Desk"
# export CRM_BASE_URL="http://127.0.0.1:8787"
# export DEFAULT_CURRENCY=USD
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8787
```

Open http://127.0.0.1:8787

For new OTA owners (install, first desk steps, human locks, Grok Bot settings): see **[MARKETPLACE.md](MARKETPLACE.md)**.

## Desk layer

- Quote versions + line items (package/hotel/ferry/flight/cab/fee/discount/other) on Pipeline
- Hotels & ferries with status + `human_approved` lock (forms on Bookings)
- Travelers + doc checklist (Missing/Received/Verified)
- Booking itinerary: `GET /bookings/{id}/itinerary.html` (print-friendly; weasyprint optional)
- Desk reports on home: stage counts, balances by currency, missing docs, pending approvals
- Balance/docs follow-up suggestions; WhatsApp/email drafts (copy only, no send)
- Multi-currency display (no FX)

## Sample letterhead / itinerary

See `letterhead/western_sample_*` and `itinerary/western_sample_*` for printable demo HTML/PDF (fictional Sample Tour Agency contacts).

## Config

Optional env (defaults in parentheses): `AGENCY_NAME` (Routebook Desk), `CRM_BASE_URL` (http://127.0.0.1:8787), `DEFAULT_CURRENCY` (USD). Agency name appears in the top brand bar.

## Bot

Pair a Grok Bot teammate with this CRM URL, your agency name, default currency, and destinations. Hotel/ferry/ticket locks stay human — see MARKETPLACE.md.

## License

MIT — Copyright (c) 2026 Anan Jaiswal
