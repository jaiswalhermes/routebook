# Routebook — marketplace install

Tour & travel OTA desk CRM (FastAPI + SQLite). Plug in your agency name, packages, and Grok Bot teammate. The bundled Western markets catalog is **sample data** — replace it with your products.

**Repo:** https://github.com/jaiswalhermes/routebook  
(If that name is taken, use `https://github.com/jaiswalhermes/routebook-crm`.)

**Currency handling:** The UI displays the full set of current ISO 4217 alphabetic codes (178 codes), with USD, EUR, GBP, AED, SGD, AUD, CAD, CHF, JPY, and INR preferred first. There is no live FX conversion; amounts remain in their booking currency. The default is USD (`DEFAULT_CURRENCY`).

## Install & run

```bash
git clone https://github.com/jaiswalhermes/routebook.git
cd routebook
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# optional: export env from .env.example
export AGENCY_NAME="Your Agency Desk"
export CRM_BASE_URL="http://127.0.0.1:8787"
export DEFAULT_CURRENCY=USD
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8787
```

Open http://127.0.0.1:8787 — top brand shows `AGENCY_NAME`.

On first launch with no `routebook.db`, seeds recreate a `[SAMPLE]` / `[DEMO]` catalog and guests automatically. Do **not** commit a live `.db`.

## First desk steps

1. **Packages** — review the sample Western markets catalog; add your own and retire samples.
2. **Pipeline** — create a lead (destination, dates, currency, pax).
3. **Quote** — add quote versions + line items (package / hotel / ferry / flight / fee…).
4. **Confirm → Booking** — convert when the guest pays / commits.
5. **Bookings** — add travelers, docs checklist, hotels, ferries, flights, cabs.
6. **Itinerary** — `GET /bookings/{id}/itinerary.html` (print / PDF via browser).
7. **Desk home** — stage counts, balances by currency, missing docs, pending approvals.

## Human locks (do not automate)

These stay **human-approved** — bots must not flip the lock:

- **Hotels** — status + `human_approved` on each hotel row
- **Ferries** — same pattern
- **Tickets / flights** — treat ticketed / PNR confirmations as desk-owned; do not invent ticket refs

Use the Bookings forms to approve. Dashboard lists pending hotel/ferry approvals.

## What the Grok Bot template expects

When you attach a Grok Bot teammate to this app, configure (or tell it):

| Setting | Example | Notes |
|--------|---------|--------|
| **CRM URL** | `http://127.0.0.1:8787` | Same as `CRM_BASE_URL` |
| **Agency name** | `Your Agency Desk` | Same as `AGENCY_NAME` (UI brand) |
| **Default currency** | `USD` | Same as `DEFAULT_CURRENCY` |
| **Destinations** | Your markets (e.g. Hawaii, Iceland, Greece…) | Replace sample catalog focus |

Bot may draft quotes, follow-ups, WhatsApp/email copy, and itinerary HTML. It must **not** approve hotel/ferry locks or invent ticketed PNRs.

## Config reference

See `.env.example`. Variables are read at process start:

- `AGENCY_NAME` (default `Routebook Desk`)
- `CRM_BASE_URL` (default `http://127.0.0.1:8787`)
- `DEFAULT_CURRENCY` (default `USD`)

## Data

SQLite file: `routebook.db` (created locally; listed in `.gitignore`). Seed/demo rows are labeled `[SAMPLE]` / `[DEMO]` in package highlights and guest notes. Do not delete the DB when upgrading — migrations are additive.
