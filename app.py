#!/usr/bin/env python3
"""Routebook — marketplace-ready tour & travel OTA CRM (domestic and international desk)."""
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from currencies import CURRENCIES

ROOT = Path(__file__).parent
DB = ROOT / "routebook.db"

# Optional marketplace config (env or defaults). See .env.example / MARKETPLACE.md
AGENCY_NAME = os.environ.get("AGENCY_NAME", "Routebook Desk").strip() or "Routebook Desk"
CRM_BASE_URL = os.environ.get("CRM_BASE_URL", "http://127.0.0.1:8787").strip().rstrip("/") or "http://127.0.0.1:8787"
_DEFAULT_CUR = (os.environ.get("DEFAULT_CURRENCY", "USD") or "USD").strip().upper()
DEFAULT_CURRENCY = _DEFAULT_CUR if _DEFAULT_CUR else "USD"

app = FastAPI(title=AGENCY_NAME)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
jinja_env = Environment(
    loader=FileSystemLoader(str(ROOT / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
    cache_size=0,
)

def render(name, context):
    ctx = {
        "agency_name": AGENCY_NAME,
        "crm_base_url": CRM_BASE_URL,
        "default_currency": DEFAULT_CURRENCY,
    }
    ctx.update(context or {})
    html = jinja_env.get_template(name).render(ctx)
    return HTMLResponse(html)

STAGES = ["Inquiry", "Quoted", "Confirmed", "Travelling", "Completed", "Lost"]
FLIGHT_STATUSES = ["Inquiry", "Quoted", "Booked", "Ticketed", "Cancelled"]
CAB_STATUSES = ["Needed", "Quoted", "Confirmed", "Done", "Cancelled"]
FLIGHT_DIRECTIONS = ["outbound", "return", "internal"]
SUPPLIER_STATUSES = ["Inquiry", "Quoted", "Held", "Confirmed", "Cancelled"]
DOC_STATUSES = ["Missing", "Received", "Verified"]
DOC_TYPES = [
    ("passport_copy", "Passport copy"),
    ("visa", "Visa / e-visa"),
    ("photo", "Passport photo"),
    ("insurance", "Travel insurance"),
    ("ticket", "Flight / ferry ticket"),
    ("other", "Other document"),
]
LINE_TYPES = ["package", "hotel", "ferry", "flight", "cab", "fee", "discount", "other"]
DRAFT_KINDS = ["quote", "balance", "docs"]


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _table_cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def migrate(con):
    """Safe ALTER TABLE adds + new desk tables; preserve existing rows."""
    cust_cols = _table_cols(con, "customers")
    if "nationality" not in cust_cols:
        con.execute("ALTER TABLE customers ADD COLUMN nationality TEXT")

    lead_cols = _table_cols(con, "leads")
    if "currency" not in lead_cols:
        con.execute("ALTER TABLE leads ADD COLUMN currency TEXT DEFAULT 'INR'")
    if "country" not in lead_cols:
        con.execute("ALTER TABLE leads ADD COLUMN country TEXT")

    book_cols = _table_cols(con, "bookings")
    if "currency" not in book_cols:
        con.execute("ALTER TABLE bookings ADD COLUMN currency TEXT DEFAULT 'INR'")
    if "human_lock" not in book_cols:
        con.execute("ALTER TABLE bookings ADD COLUMN human_lock INTEGER DEFAULT 0")
    if "approval_note" not in book_cols:
        con.execute("ALTER TABLE bookings ADD COLUMN approval_note TEXT")

    pkg_cols = _table_cols(con, "packages")
    if "currency" not in pkg_cols:
        con.execute("ALTER TABLE packages ADD COLUMN currency TEXT DEFAULT 'INR'")

    con.execute("UPDATE leads SET currency=? WHERE currency IS NULL OR TRIM(currency)=''", (DEFAULT_CURRENCY,))
    con.execute("UPDATE bookings SET currency=? WHERE currency IS NULL OR TRIM(currency)=''", (DEFAULT_CURRENCY,))
    con.execute("UPDATE packages SET currency=? WHERE currency IS NULL OR TRIM(currency)=''", (DEFAULT_CURRENCY,))
    con.execute(
        """UPDATE customers SET nationality='United States'
           WHERE (nationality IS NULL OR TRIM(nationality)='')
             AND city IN ('Austin','Chicago','Boston','San Francisco')"""
    )

    con.executescript("""
    CREATE TABLE IF NOT EXISTS travelers (
      id INTEGER PRIMARY KEY,
      customer_id INTEGER,
      booking_id INTEGER,
      name TEXT NOT NULL,
      phone TEXT,
      email TEXT,
      dob TEXT,
      passport_no TEXT,
      passport_expiry TEXT,
      nationality TEXT,
      notes TEXT,
      FOREIGN KEY(customer_id) REFERENCES customers(id),
      FOREIGN KEY(booking_id) REFERENCES bookings(id)
    );
    CREATE TABLE IF NOT EXISTS quote_versions (
      id INTEGER PRIMARY KEY,
      lead_id INTEGER NOT NULL,
      version_no INTEGER NOT NULL,
      currency TEXT DEFAULT 'INR',
      label TEXT,
      notes TEXT,
      total_amount INTEGER DEFAULT 0,
      created_at TEXT,
      is_current INTEGER DEFAULT 1,
      FOREIGN KEY(lead_id) REFERENCES leads(id)
    );
    CREATE TABLE IF NOT EXISTS quote_line_items (
      id INTEGER PRIMARY KEY,
      quote_version_id INTEGER NOT NULL,
      line_type TEXT NOT NULL,
      description TEXT,
      qty INTEGER DEFAULT 1,
      unit_amount INTEGER DEFAULT 0,
      currency TEXT DEFAULT 'INR',
      sort_order INTEGER DEFAULT 0,
      FOREIGN KEY(quote_version_id) REFERENCES quote_versions(id)
    );
    CREATE TABLE IF NOT EXISTS hotels (
      id INTEGER PRIMARY KEY,
      booking_id INTEGER NOT NULL,
      name TEXT,
      location TEXT,
      check_in TEXT,
      check_out TEXT,
      rooms INTEGER DEFAULT 1,
      room_type TEXT,
      cost_inr INTEGER,
      currency TEXT DEFAULT 'INR',
      status TEXT DEFAULT 'Inquiry',
      human_approved INTEGER DEFAULT 0,
      approved_at TEXT,
      approval_note TEXT,
      notes TEXT,
      confirmation_no TEXT,
      FOREIGN KEY(booking_id) REFERENCES bookings(id)
    );
    CREATE TABLE IF NOT EXISTS ferries (
      id INTEGER PRIMARY KEY,
      booking_id INTEGER NOT NULL,
      operator TEXT,
      from_port TEXT,
      to_port TEXT,
      depart_at TEXT,
      arrive_at TEXT,
      pax INTEGER,
      cost_inr INTEGER,
      currency TEXT DEFAULT 'INR',
      status TEXT DEFAULT 'Inquiry',
      human_approved INTEGER DEFAULT 0,
      approved_at TEXT,
      approval_note TEXT,
      notes TEXT,
      ticket_ref TEXT,
      FOREIGN KEY(booking_id) REFERENCES bookings(id)
    );
    CREATE TABLE IF NOT EXISTS doc_checklist (
      id INTEGER PRIMARY KEY,
      booking_id INTEGER NOT NULL,
      traveler_id INTEGER,
      doc_type TEXT NOT NULL,
      label TEXT,
      status TEXT DEFAULT 'Missing',
      notes TEXT,
      updated_at TEXT,
      FOREIGN KEY(booking_id) REFERENCES bookings(id),
      FOREIGN KEY(traveler_id) REFERENCES travelers(id)
    );
    """)

def init():
    with closing(db()) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS packages (
          id INTEGER PRIMARY KEY, name TEXT, destination TEXT, nights INTEGER,
          days INTEGER, price_inr INTEGER, highlights TEXT, active INTEGER DEFAULT 1,
          currency TEXT DEFAULT 'INR'
        );
        CREATE TABLE IF NOT EXISTS customers (
          id INTEGER PRIMARY KEY, name TEXT, phone TEXT, email TEXT, city TEXT,
          passport_expiry TEXT, visa_expiry TEXT, notes TEXT, nationality TEXT
        );
        CREATE TABLE IF NOT EXISTS leads (
          id INTEGER PRIMARY KEY, customer_id INTEGER, name TEXT, phone TEXT, email TEXT,
          source TEXT, pax INTEGER, travel_from TEXT, travel_to TEXT, destination TEXT,
          stage TEXT, notes TEXT, package_id INTEGER, quoted_inr INTEGER,
          created_at TEXT, currency TEXT DEFAULT 'INR', country TEXT,
          FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS bookings (
          id INTEGER PRIMARY KEY, lead_id INTEGER, customer_id INTEGER, package_id INTEGER,
          ref TEXT, travel_from TEXT, travel_to TEXT, pax INTEGER, quoted_inr INTEGER,
          status TEXT, itinerary TEXT, created_at TEXT, currency TEXT DEFAULT 'INR',
          human_lock INTEGER DEFAULT 0, approval_note TEXT
        );
        CREATE TABLE IF NOT EXISTS payments (
          id INTEGER PRIMARY KEY, booking_id INTEGER, amount_inr INTEGER, kind TEXT,
          paid_on TEXT, note TEXT
        );
        CREATE TABLE IF NOT EXISTS followups (
          id INTEGER PRIMARY KEY, lead_id INTEGER, booking_id INTEGER, due_on TEXT,
          title TEXT, done INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS flights (
          id INTEGER PRIMARY KEY,
          booking_id INTEGER NOT NULL,
          direction TEXT,
          airline TEXT,
          flight_no TEXT,
          from_airport TEXT,
          to_airport TEXT,
          depart_at TEXT,
          arrive_at TEXT,
          pax INTEGER,
          pnr TEXT,
          cost_inr INTEGER,
          status TEXT,
          notes TEXT,
          FOREIGN KEY(booking_id) REFERENCES bookings(id)
        );
        CREATE TABLE IF NOT EXISTS cabs (
          id INTEGER PRIMARY KEY,
          booking_id INTEGER NOT NULL,
          when_at TEXT,
          from_place TEXT,
          to_place TEXT,
          vehicle TEXT,
          vendor TEXT,
          driver_phone TEXT,
          cost_inr INTEGER,
          status TEXT,
          notes TEXT,
          FOREIGN KEY(booking_id) REFERENCES bookings(id)
        );
        """)
        migrate(con)
        if con.execute("SELECT COUNT(*) FROM packages").fetchone()[0] == 0:
            seed(con)
        seed_transport(con)
        seed_intl_demo(con)
        seed_desk_demo(con)
        seed_reminders(con)
        label_sample_catalog(con)
        con.commit()


def label_sample_catalog(con):
    """Mark existing demo packages as SAMPLE in highlights without wiping rows."""
    for row in con.execute("SELECT id, name, highlights FROM packages").fetchall():
        h = (row["highlights"] or "").strip()
        if "[SAMPLE]" in h or "SAMPLE catalog" in h:
            continue
        # Only label known seed / demo catalog names; leave owner-added packages alone
        name = row["name"] or ""
        demo_names = (
            "Hawaii Honeymoon",
            "California Coast",
            "Iceland Ring",
            "Greek Islands",
            "NYC New England",
            "Maui Day Hop",
        )
        if any(name.startswith(n) or n in name for n in demo_names):
            con.execute(
                "UPDATE packages SET highlights=? WHERE id=?",
                (f"[SAMPLE] {h}".strip() if h else "[SAMPLE] demo catalog — replace with your packages", row["id"]),
            )
    # Soft-label obvious demo customer notes once
    for row in con.execute("SELECT id, notes FROM customers").fetchall():
        n = (row["notes"] or "").strip()
        if not n or n.startswith("[DEMO]"):
            continue
        # Only touch classic seed guests by leaving non-demo notes that already look custom alone:
        # skip if already tagged; otherwise prefix only when notes look like the stock seed phrases
        stock = (
            "Honeymoon, prefers beach villa",
            "Family of 4, kids 8 and 11",
            "Solo, photography",
            "Corporate 12 pax",
            "UK honeymoon",
        )
        if any(s in n for s in stock):
            con.execute("UPDATE customers SET notes=? WHERE id=?", (f"[DEMO] {n}", row["id"]))


def seed(con):
    pkgs = [
        ("Hawaii Honeymoon 6N", "Hawaii", 6, 7, 4200, "[SAMPLE] Honolulu + Maui, Waikiki, Road to Hana — replace with your packages", "USD"),
        ("California Coast + Yosemite 4N", "California", 4, 5, 2800, "[SAMPLE] Big Sur, Monterey, Yosemite Valley — demo catalog", "USD"),
        ("Iceland Ring Road 5N", "Iceland", 5, 6, 3600, "[SAMPLE] Reykjavik, Golden Circle, South Coast — demo catalog", "USD"),
        ("Greek Islands Escape 6N", "Greece", 6, 7, 3900, "[SAMPLE] Santorini + Mykonos, caldera sunset, island ferry — demo catalog", "EUR"),
        ("NYC New England Weekend 3N", "New York / New England", 3, 4, 1900, "[SAMPLE] Manhattan, Boston day trip, Amtrak — demo catalog", "USD"),
    ]
    con.executemany(
        "INSERT INTO packages(name,destination,nights,days,price_inr,highlights,active,currency) VALUES(?,?,?,?,?,?,1,?)",
        pkgs,
    )
    custs = [
        ("Emma & Noah Carter", "+1 512 555 0101", "emma.noah@example.com", "Austin", "2029-04-12", "", "[DEMO] Honeymoon, prefers beach villa", "United States"),
        ("Liam Brooks", "+1 312 555 0144", "liam.brooks@example.com", "Chicago", "2027-11-01", "2026-12-15", "[DEMO] Family of 4, kids 8 and 11", "United States"),
        ("Olivia Bennett", "+1 617 555 0188", "olivia.b@example.com", "Boston", "", "", "[DEMO] Solo, photography", "United States"),
        ("Summit Labs team outing", "+1 415 555 0199", "admin@summitlabs.example", "San Francisco", "", "", "[DEMO] Corporate 12 pax", "United States"),
    ]
    con.executemany(
        "INSERT INTO customers(name,phone,email,city,passport_expiry,visa_expiry,notes,nationality) VALUES(?,?,?,?,?,?,?,?)",
        custs,
    )
    today = date.today()
    leads = [
        (1, "Emma & Noah Carter", "+1 512 555 0101", "emma.noah@example.com", "Instagram", 2,
         str(today + timedelta(days=40)), str(today + timedelta(days=47)), "Hawaii", "Quoted",
         "Wants ocean-view villa. Quoted Hawaii Honeymoon.", 1, 4200, "USD", "United States"),
        (2, "Liam Brooks", "+1 312 555 0144", "liam.brooks@example.com", "Referral", 4,
         str(today + timedelta(days=21)), str(today + timedelta(days=26)), "California", "Inquiry",
         "School holidays. Need connecting flights from ORD.", 2, None, "USD", "United States"),
        (3, "Olivia Bennett", "+1 617 555 0188", "olivia.b@example.com", "Website", 1,
         str(today + timedelta(days=12)), str(today + timedelta(days=16)), "Greece", "Confirmed",
         "Paid $800 advance. Santorini sunset shoot; ferry to Mykonos optional.", 4, 3900, "EUR", "United States"),
        (4, "Summit Labs team outing", "+1 415 555 0199", "admin@summitlabs.example", "Walk-in", 12,
         str(today + timedelta(days=5)), str(today + timedelta(days=7)), "New York / New England", "Confirmed",
         "Amtrak + 2 floors Midtown. Invoice to Summit Labs.", 5, 18600, "USD", "United States"),
        (None, "Ethan Price", "+1 206 555 0177", "ethan.price@example.com", "WhatsApp", 2,
         str(today + timedelta(days=60)), str(today + timedelta(days=67)), "Iceland", "Lost",
         "Went with another agent on price.", 3, 3600, "USD", "United States"),
    ]
    for row in leads:
        con.execute(
            """INSERT INTO leads(customer_id,name,phone,email,source,pax,travel_from,travel_to,destination,stage,notes,package_id,quoted_inr,created_at,currency,country)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row[:13] + (datetime.now().isoformat(timespec="seconds"),) + row[13:],
        )
    for lead_id, ref, status, itin in (
        (3, "RB-1042", "Confirmed",
         "Day 1 Arrive Athens (ATH) → evening ferry to Santorini\nDay 2–3 Oia / caldera\nDay 4 Mykonos ferry + town\nDay 5 Depart ATH"),
        (4, "RB-1043", "Confirmed",
         "Day 1 SFO→JFK, Midtown check-in\nDay 2 Manhattan walking + Broadway\nDay 3 Amtrak day trip Boston (BOS)\nDay 4 Return SFO"),
    ):
        lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        con.execute(
            """INSERT INTO bookings(lead_id,customer_id,package_id,ref,travel_from,travel_to,pax,quoted_inr,status,itinerary,created_at,currency)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lead["id"], lead["customer_id"], lead["package_id"], ref, lead["travel_from"], lead["travel_to"],
             lead["pax"], lead["quoted_inr"], status, itin,
             datetime.now().isoformat(timespec="seconds"), lead["currency"] or "USD"),
        )
    b3 = con.execute("SELECT id, quoted_inr FROM bookings WHERE ref='RB-1042'").fetchone()
    b4 = con.execute("SELECT id, quoted_inr FROM bookings WHERE ref='RB-1043'").fetchone()
    con.execute("INSERT INTO payments(booking_id,amount_inr,kind,paid_on,note) VALUES(?,?,?,?,?)",
                (b3["id"], 800, "Advance", str(today), "Zelle"))
    con.execute("INSERT INTO payments(booking_id,amount_inr,kind,paid_on,note) VALUES(?,?,?,?,?)",
                (b4["id"], 9000, "Advance", str(today - timedelta(days=2)), "ACH Summit Labs"))
    con.executemany(
        "INSERT INTO followups(lead_id,booking_id,due_on,title,done) VALUES(?,?,?,?,?)",
        [
            (1, None, str(today), "Call Emma: Waikiki villa vs Maui cottage", 0),
            (2, None, str(today - timedelta(days=1)), "Send ORD–SFO / FAT flight options to Liam", 0),
            (3, b3["id"], str(today + timedelta(days=1)), "Collect remaining balance from Olivia", 0),
            (4, b4["id"], str(today + timedelta(days=3)), "Confirm Midtown floors for Summit", 0),
        ],
    )


def seed_intl_demo(con):
    """Idempotent UK couple Iceland SAMPLE/demo (GBP) for international desk testing."""
    email = "ava.mason@example.co.uk"
    existing = con.execute(
        "SELECT id FROM customers WHERE email=? OR email=? OR name LIKE ?",
        (email, "emma.james@example.co.uk", "Ava & Mason Reed%"),
    ).fetchone()
    if existing:
        return
    today = date.today()
    con.execute(
        """INSERT INTO customers(name,phone,email,city,passport_expiry,visa_expiry,notes,nationality)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            "Ava & Mason Reed",
            "+44 7700 900123",
            email,
            "London",
            "2030-06-15",
            "2026-11-30",
            "[DEMO] UK honeymoon, Iceland 5N — prefer Blue Lagoon suite, Schengen OK",
            "United Kingdom",
        ),
    )
    cust_id = con.execute("SELECT id FROM customers WHERE email=?", (email,)).fetchone()["id"]
    pkg = con.execute(
        "SELECT id FROM packages WHERE name LIKE 'Iceland Ring%' OR name LIKE 'Hawaii Honeymoon%' LIMIT 1"
    ).fetchone()
    pkg_id = pkg["id"] if pkg else 3
    travel_from = str(today + timedelta(days=55))
    travel_to = str(today + timedelta(days=62))
    con.execute(
        """INSERT INTO leads(customer_id,name,phone,email,source,pax,travel_from,travel_to,destination,stage,notes,package_id,quoted_inr,created_at,currency,country)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            cust_id, "Ava & Mason Reed", "+44 7700 900123", email, "Website", 2,
            travel_from, travel_to, "Iceland", "Confirmed",
            "Intl GBP quote. Blue Lagoon suite + Golden Circle. Passports on file (UK, no visa).",
            pkg_id, 2850, datetime.now().isoformat(timespec="seconds"), "GBP", "United Kingdom",
        ),
    )
    lead_id = con.execute("SELECT id FROM leads WHERE email=? ORDER BY id DESC LIMIT 1", (email,)).fetchone()["id"]
    n = con.execute("SELECT COUNT(*) c FROM bookings").fetchone()["c"] + 1001
    ref = f"RB-{n}"
    # Prefer a stable demo ref if free
    if not con.execute("SELECT id FROM bookings WHERE ref='RB-UK01'").fetchone():
        ref = "RB-UK01"
    con.execute(
        """INSERT INTO bookings(lead_id,customer_id,package_id,ref,travel_from,travel_to,pax,quoted_inr,status,itinerary,created_at,currency)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            lead_id, cust_id, pkg_id, ref, travel_from, travel_to, 2, 2850, "Confirmed",
            "Day 1 Arrive KEF → Reykjavik\nDay 2 Golden Circle\nDay 3–4 South Coast / glacier\nDay 5 Blue Lagoon + depart",
            datetime.now().isoformat(timespec="seconds"), "GBP",
        ),
    )
    booking_id = con.execute("SELECT id FROM bookings WHERE ref=?", (ref,)).fetchone()["id"]
    con.execute(
        "INSERT INTO payments(booking_id,amount_inr,kind,paid_on,note) VALUES(?,?,?,?,?)",
        (booking_id, 500, "Advance", str(today), "Card GBP"),
    )
    con.execute(
        "INSERT INTO followups(lead_id,booking_id,due_on,title,done) VALUES(?,?,?,?,?)",
        (lead_id, booking_id, str(today + timedelta(days=2)), "Confirm Blue Lagoon suite for Reeds", 0),
    )
    # Intl flight legs — Western airport codes
    dep = datetime.combine(today + timedelta(days=55), datetime.strptime("21:40", "%H:%M").time())
    arr = datetime.combine(today + timedelta(days=56), datetime.strptime("00:05", "%H:%M").time())
    con.execute(
        """INSERT INTO flights(booking_id,direction,airline,flight_no,from_airport,to_airport,
           depart_at,arrive_at,pax,pnr,cost_inr,status,notes)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            booking_id, "outbound", "Icelandair", "FI 451", "LHR", "KEF",
            dep.isoformat(timespec="minutes"), arr.isoformat(timespec="minutes"),
            2, "PNR-UKH1", 420, "Booked", "Direct LHR→KEF overnight",
        ),
    )
    dep2 = datetime.combine(today + timedelta(days=62), datetime.strptime("14:30", "%H:%M").time())
    arr2 = datetime.combine(today + timedelta(days=62), datetime.strptime("16:55", "%H:%M").time())
    con.execute(
        """INSERT INTO flights(booking_id,direction,airline,flight_no,from_airport,to_airport,
           depart_at,arrive_at,pax,pnr,cost_inr,status,notes)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            booking_id, "return", "Icelandair", "FI 450", "KEF", "LHR",
            dep2.isoformat(timespec="minutes"), arr2.isoformat(timespec="minutes"),
            2, "PNR-UKH1", 390, "Booked", "Return same PNR",
        ),
    )


def seed_transport(con):
    """Seed SAMPLE/demo flights/cabs once, tied to existing bookings."""
    if con.execute("SELECT COUNT(*) FROM flights").fetchone()[0] > 0:
        return
    by_ref = {
        r["ref"]: r
        for r in con.execute("SELECT id, ref, pax, travel_from, travel_to FROM bookings").fetchall()
    }
    olivia = by_ref.get("RB-1042")
    summit = by_ref.get("RB-1043")
    smoke = by_ref.get("RB-1003")
    today = date.today()
    flights = []
    if olivia:
        dep = datetime.combine(today + timedelta(days=12), datetime.strptime("09:40", "%H:%M").time())
        arr = datetime.combine(today + timedelta(days=12), datetime.strptime("14:05", "%H:%M").time())
        flights.append((
            olivia["id"], "outbound", "Delta", "DL 184", "BOS", "ATH",
            dep.isoformat(timespec="minutes"), arr.isoformat(timespec="minutes"),
            olivia["pax"] or 1, "PNR-OLIV1", 980, "Booked", "Awaiting e-ticket mail",
        ))
        dep2 = datetime.combine(today + timedelta(days=16), datetime.strptime("13:20", "%H:%M").time())
        arr2 = datetime.combine(today + timedelta(days=16), datetime.strptime("17:40", "%H:%M").time())
        flights.append((
            olivia["id"], "return", "Delta", "DL 185", "ATH", "BOS",
            dep2.isoformat(timespec="minutes"), arr2.isoformat(timespec="minutes"),
            olivia["pax"] or 1, "", 1020, "Quoted", "Hold till balance received",
        ))
    if summit:
        dep = datetime.combine(today + timedelta(days=5), datetime.strptime("06:15", "%H:%M").time())
        arr = datetime.combine(today + timedelta(days=5), datetime.strptime("14:50", "%H:%M").time())
        flights.append((
            summit["id"], "outbound", "United", "UA 526", "SFO", "JFK",
            dep.isoformat(timespec="minutes"), arr.isoformat(timespec="minutes"),
            summit["pax"] or 12, "PNR-SUM99", 8400, "Ticketed", "Group PNR locked",
        ))
    if smoke:
        dep = datetime.combine(today + timedelta(days=41), datetime.strptime("10:00", "%H:%M").time())
        arr = datetime.combine(today + timedelta(days=41), datetime.strptime("13:30", "%H:%M").time())
        flights.append((
            smoke["id"], "outbound", "Alaska", "AS 332", "LAX", "HNL",
            dep.isoformat(timespec="minutes"), arr.isoformat(timespec="minutes"),
            smoke["pax"] or 2, "SMOKE-PNR", 640, "Inquiry", "Smoke demo leg",
        ))
    if flights:
        con.executemany(
            """INSERT INTO flights(booking_id,direction,airline,flight_no,from_airport,to_airport,
               depart_at,arrive_at,pax,pnr,cost_inr,status,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            flights,
        )
    cabs = []
    if olivia:
        when = datetime.combine(today + timedelta(days=12), datetime.strptime("15:30", "%H:%M").time())
        cabs.append((
            olivia["id"], when.isoformat(timespec="minutes"),
            "Athens Airport (ATH)", "Piraeus ferry terminal", "Sedan", "Attica Transfers",
            "+30 210 555 0199", 85, "Needed", "Meet-and-greet board",
        ))
    if summit:
        when = datetime.combine(today + timedelta(days=5), datetime.strptime("16:00", "%H:%M").time())
        cabs.append((
            summit["id"], when.isoformat(timespec="minutes"),
            "JFK Terminal 7", "Midtown Marriott", "12-seat van", "NYC Black Car Co",
            "+1 212 555 0144", 320, "Confirmed", "Staff outing transfer",
        ))
    if smoke and len(cabs) < 2:
        when = datetime.combine(today + timedelta(days=41), datetime.strptime("14:00", "%H:%M").time())
        cabs.append((
            smoke["id"], when.isoformat(timespec="minutes"),
            "HNL Airport", "Waikiki Beach hotel", "SUV", "Aloha Transfers",
            "", 95, "Quoted", "Smoke demo cab",
        ))
    if cabs:
        con.executemany(
            """INSERT INTO cabs(booking_id,when_at,from_place,to_place,vehicle,vendor,
               driver_phone,cost_inr,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            cabs,
        )




def seed_desk_demo(con):
    """Idempotent travelers, quote lines, hotels, ferries, docs for SAMPLE/demo bookings."""
    for b in con.execute("SELECT id, customer_id, pax FROM bookings").fetchall():
        if not b["customer_id"]:
            continue
        exists = con.execute(
            "SELECT id FROM travelers WHERE booking_id=? LIMIT 1", (b["id"],)
        ).fetchone()
        if exists:
            continue
        cust = con.execute("SELECT * FROM customers WHERE id=?", (b["customer_id"],)).fetchone()
        if not cust:
            continue
        con.execute(
            """INSERT INTO travelers(customer_id,booking_id,name,phone,email,passport_expiry,nationality,notes)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                cust["id"], b["id"], cust["name"], cust["phone"], cust["email"],
                cust["passport_expiry"], cust["nationality"], "Primary guest",
            ),
        )

    carter = con.execute(
        "SELECT * FROM leads WHERE name LIKE 'Emma & Noah%' ORDER BY id LIMIT 1"
    ).fetchone()
    if carter and con.execute(
        "SELECT id FROM quote_versions WHERE lead_id=? LIMIT 1", (carter["id"],)
    ).fetchone() is None:
        ensure_quote_version(con, carter["id"], label="v1 honeymoon", notes="Villa package rollup")
        qv = current_quote(con, carter["id"])
        if qv:
            add_line(con, qv["id"], "package", "Hawaii Honeymoon 6N", 1, 4200, "USD")
            add_line(con, qv["id"], "flight", "Inter-island HNL–OGG", 2, 180, "USD")
            add_line(con, qv["id"], "fee", "Service fee", 1, 150, "USD")
            add_line(con, qv["id"], "discount", "Early-bird discount", 1, -200, "USD")
            rollup_quote(con, qv["id"])

    olivia_b = con.execute("SELECT id, currency, pax, travel_from, travel_to FROM bookings WHERE ref='RB-1042'").fetchone()
    if olivia_b and con.execute("SELECT id FROM hotels WHERE booking_id=? LIMIT 1", (olivia_b["id"],)).fetchone() is None:
        con.execute(
            """INSERT INTO hotels(booking_id,name,location,check_in,check_out,rooms,room_type,cost_inr,currency,status,human_approved,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,0,?)""",
            (
                olivia_b["id"], "Canaves Oia Suites", "Santorini",
                olivia_b["travel_from"], olivia_b["travel_to"], 1, "Caldera suite",
                1400, olivia_b["currency"] or "EUR", "Quoted", "Hold pending balance",
            ),
        )
        con.execute(
            """INSERT INTO ferries(booking_id,operator,from_port,to_port,depart_at,arrive_at,pax,cost_inr,currency,status,human_approved,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,0,?)""",
            (
                olivia_b["id"], "Seajets", "Santorini", "Mykonos",
                f"{olivia_b['travel_from']}T08:00", f"{olivia_b['travel_from']}T10:30",
                olivia_b["pax"] or 1, 75, olivia_b["currency"] or "EUR", "Inquiry", "Morning high-speed ferry",
            ),
        )

    uk = con.execute("SELECT id, currency, pax, travel_from, travel_to FROM bookings WHERE ref='RB-UK01'").fetchone()
    if uk and con.execute("SELECT id FROM hotels WHERE booking_id=? LIMIT 1", (uk["id"],)).fetchone() is None:
        con.execute(
            """INSERT INTO hotels(booking_id,name,location,check_in,check_out,rooms,room_type,cost_inr,currency,status,human_approved,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,0,?)""",
            (
                uk["id"], "Ion Adventure Hotel", "Reykjavik",
                uk["travel_from"], uk["travel_to"], 1, "Lagoon-view suite",
                920, uk["currency"] or "GBP", "Held", "Awaiting human lock before confirm",
            ),
        )
        # No island ferry for Iceland — airport coach / Blue Lagoon transfer instead (cab-side handled elsewhere)
        # Skip ferry row for UK booking

    for b in con.execute("SELECT id FROM bookings").fetchall():
        if con.execute("SELECT id FROM doc_checklist WHERE booking_id=? LIMIT 1", (b["id"],)).fetchone():
            continue
        trav = con.execute(
            "SELECT id FROM travelers WHERE booking_id=? ORDER BY id LIMIT 1", (b["id"],)
        ).fetchone()
        tid = trav["id"] if trav else None
        now = datetime.now().isoformat(timespec="seconds")
        for dtype, label in DOC_TYPES[:4]:
            con.execute(
                """INSERT INTO doc_checklist(booking_id,traveler_id,doc_type,label,status,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                (b["id"], tid, dtype, label, "Missing", now),
            )


def seed_reminders(con):
    """Suggest balance-due and missing-doc followups (idempotent by title)."""
    today = date.today()
    bookings = con.execute(
        """SELECT b.*, l.name as traveller,
           (SELECT COALESCE(SUM(amount_inr),0) FROM payments WHERE booking_id=b.id) as paid
           FROM bookings b LEFT JOIN leads l ON l.id=b.lead_id"""
    ).fetchall()
    for b in bookings:
        due = max((b["quoted_inr"] or 0) - (b["paid"] or 0), 0)
        if due > 0:
            title = f"[balance] Collect {due} {normalize_currency(b['currency'] if 'currency' in b.keys() else None)} · {b['ref']}"
            exists = con.execute(
                "SELECT id FROM followups WHERE booking_id=? AND title=? AND done=0",
                (b["id"], title),
            ).fetchone()
            if not exists:
                con.execute(
                    "INSERT INTO followups(lead_id,booking_id,due_on,title,done) VALUES(?,?,?,?,0)",
                    (b["lead_id"], b["id"], str(today), title),
                )
        missing = con.execute(
            "SELECT COUNT(*) c FROM doc_checklist WHERE booking_id=? AND status='Missing'",
            (b["id"],),
        ).fetchone()["c"]
        if missing:
            title = f"[docs] Chase {missing} missing doc(s) · {b['ref']}"
            exists = con.execute(
                "SELECT id FROM followups WHERE booking_id=? AND title=? AND done=0",
                (b["id"], title),
            ).fetchone()
            if not exists:
                con.execute(
                    "INSERT INTO followups(lead_id,booking_id,due_on,title,done) VALUES(?,?,?,?,0)",
                    (b["lead_id"], b["id"], str(today + timedelta(days=1)), title),
                )


def paid_for(con, booking_id):
    row = con.execute("SELECT COALESCE(SUM(amount_inr),0) s FROM payments WHERE booking_id=?", (booking_id,)).fetchone()
    return row["s"]


def normalize_currency(code):
    cur = (code or DEFAULT_CURRENCY).strip().upper()
    return cur if cur in CURRENCIES else DEFAULT_CURRENCY


def money(n, currency=DEFAULT_CURRENCY):
    """Format a numeric amount with ISO currency code (no FX conversion)."""
    if n is None:
        return "—"
    cur = normalize_currency(currency)
    try:
        amount = int(n)
    except (TypeError, ValueError):
        return "—"
    return f"{amount:,} {cur}"


jinja_env.filters["money"] = money
jinja_env.filters["inr"] = lambda n: money(n, "INR")


def outstanding_by_currency(bookings):
    """Sum due amounts per currency (no cross-currency conversion)."""
    by_cur = defaultdict(int)
    for b in bookings:
        due = max((b["quoted_inr"] or 0) - (b["paid"] or 0), 0)
        if due:
            by_cur[normalize_currency(b["currency"] if "currency" in b.keys() else None)] += due
    if not by_cur:
        return money(0, DEFAULT_CURRENCY)
    return " · ".join(money(v, k) for k, v in sorted(by_cur.items()))


def current_quote(con, lead_id):
    return con.execute(
        "SELECT * FROM quote_versions WHERE lead_id=? AND is_current=1 ORDER BY version_no DESC LIMIT 1",
        (lead_id,),
    ).fetchone()


def ensure_quote_version(con, lead_id, label=None, notes=None):
    lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        return None
    cur = current_quote(con, lead_id)
    if cur:
        return cur
    currency = normalize_currency(lead["currency"] if "currency" in lead.keys() else None)
    con.execute(
        """INSERT INTO quote_versions(lead_id,version_no,currency,label,notes,total_amount,created_at,is_current)
           VALUES(?,?,?,?,?,0,?,1)""",
        (lead_id, 1, currency, label or "v1", notes or "", datetime.now().isoformat(timespec="seconds")),
    )
    return current_quote(con, lead_id)


def add_line(con, quote_version_id, line_type, description, qty, unit_amount, currency):
    sort = con.execute(
        "SELECT COALESCE(MAX(sort_order),0)+1 s FROM quote_line_items WHERE quote_version_id=?",
        (quote_version_id,),
    ).fetchone()["s"]
    con.execute(
        """INSERT INTO quote_line_items(quote_version_id,line_type,description,qty,unit_amount,currency,sort_order)
           VALUES(?,?,?,?,?,?,?)""",
        (quote_version_id, line_type, description, qty, unit_amount, normalize_currency(currency), sort),
    )


def rollup_quote(con, quote_version_id):
    rows = con.execute(
        "SELECT qty, unit_amount FROM quote_line_items WHERE quote_version_id=?",
        (quote_version_id,),
    ).fetchall()
    total = sum((r["qty"] or 1) * (r["unit_amount"] or 0) for r in rows)
    qv = con.execute("SELECT * FROM quote_versions WHERE id=?", (quote_version_id,)).fetchone()
    con.execute("UPDATE quote_versions SET total_amount=? WHERE id=?", (total, quote_version_id))
    if qv:
        con.execute("UPDATE leads SET quoted_inr=? WHERE id=?", (total, qv["lead_id"]))
    return total


def group_by(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


def booking_detail(con, booking_id):
    return con.execute(
        """SELECT b.*, p.name as package_name, p.highlights as package_highlights,
                  l.name as traveller, l.phone as lead_phone, l.email as lead_email,
                  c.nationality as guest_nationality, c.passport_expiry as guest_passport,
                  c.visa_expiry as guest_visa, c.phone as guest_phone, c.city as guest_city,
                  c.email as guest_email, c.name as guest_name,
                  (SELECT COALESCE(SUM(amount_inr),0) FROM payments WHERE booking_id=b.id) as paid
           FROM bookings b
           LEFT JOIN packages p ON p.id=b.package_id
           LEFT JOIN leads l ON l.id=b.lead_id
           LEFT JOIN customers c ON c.id=b.customer_id
           WHERE b.id=?""",
        (booking_id,),
    ).fetchone()


def build_draft(con, booking_id, kind):
    b = booking_detail(con, booking_id)
    if not b:
        return None, "Booking not found"
    cur = normalize_currency(b["currency"] if "currency" in b.keys() else None)
    name = b["traveller"] or b["guest_name"] or "Guest"
    phone = b["lead_phone"] or b["guest_phone"] or ""
    email = b["lead_email"] or b["guest_email"] or ""
    due = max((b["quoted_inr"] or 0) - (b["paid"] or 0), 0)
    if kind == "quote":
        lines = []
        total = b["quoted_inr"] or 0
        if b["lead_id"]:
            qv = current_quote(con, b["lead_id"])
            if qv:
                for li in con.execute(
                    "SELECT * FROM quote_line_items WHERE quote_version_id=? ORDER BY sort_order, id",
                    (qv["id"],),
                ).fetchall():
                    amt = (li["qty"] or 1) * (li["unit_amount"] or 0)
                    lines.append(f"• {li['description'] or li['line_type']}: {li['qty']} × {li['unit_amount']} = {amt} {li['currency']}")
                total = qv["total_amount"]
        body = (
            f"Hi {name},\n\n"
            f"Sharing the quote for {b['ref']} ({b['package_name'] or 'custom itinerary'}).\n"
            f"Travel: {b['travel_from']} → {b['travel_to']} · {b['pax']} pax\n\n"
        )
        if lines:
            body += "Line items:\n" + "\n".join(lines) + "\n\n"
        body += f"Quoted total: {money(total, cur)}\n\nHappy to adjust hotels/ferries — reply here or WhatsApp.\n\n— {AGENCY_NAME}"
        channel = "WhatsApp" if phone else "Email"
        to = phone or email
    elif kind == "balance":
        body = (
            f"Hi {name},\n\n"
            f"Gentle reminder on file {b['ref']}.\n"
            f"Quoted: {money(b['quoted_inr'], cur)} · Paid: {money(b['paid'], cur)} · Balance due: {money(due, cur)}\n\n"
            f"Please share payment confirmation when convenient so we can lock hotels/ferries.\n\n— {AGENCY_NAME}"
        )
        channel = "WhatsApp" if phone else "Email"
        to = phone or email
    else:
        docs = con.execute(
            "SELECT * FROM doc_checklist WHERE booking_id=? AND status='Missing' ORDER BY id",
            (booking_id,),
        ).fetchall()
        missing = [f"• {d['label'] or d['doc_type']}" for d in docs] or ["• (none listed — please confirm passport/visa)"]
        body = (
            f"Hi {name},\n\n"
            f"Before travel on {b['travel_from']} (file {b['ref']}), we still need:\n"
            + "\n".join(missing)
            + f"\n\nYou can share scans on WhatsApp/email. Thanks!\n\n— {AGENCY_NAME}"
        )
        channel = "Email" if email else "WhatsApp"
        to = email or phone
    return {
        "kind": kind,
        "channel": channel,
        "to": to,
        "subject": f"Routebook · {b['ref']} · {kind}",
        "body": body,
        "booking": b,
    }, None


@app.on_event("startup")
def _start():
    init()


@app.get("/")
def dashboard(request: Request):
    with closing(db()) as con:
        seed_reminders(con)
        con.commit()
        stages = {s: con.execute("SELECT COUNT(*) c FROM leads WHERE stage=?", (s,)).fetchone()["c"] for s in STAGES}
        followups = con.execute(
            """SELECT f.*, l.name as lead_name FROM followups f
               LEFT JOIN leads l ON l.id=f.lead_id
               WHERE f.done=0 ORDER BY f.due_on"""
        ).fetchall()
        bookings = con.execute(
            """SELECT b.*, p.name as package_name,
               (SELECT COALESCE(SUM(amount_inr),0) FROM payments WHERE booking_id=b.id) as paid
               FROM bookings b LEFT JOIN packages p ON p.id=b.package_id
               ORDER BY b.travel_from"""
        ).fetchall()
        upcoming = [b for b in bookings if b["travel_from"] and b["travel_from"] >= str(date.today())][:6]
        outstanding = outstanding_by_currency(bookings)
        balance_due = [b for b in bookings if max((b["quoted_inr"] or 0) - (b["paid"] or 0), 0) > 0]
        leads = con.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        open_flights = con.execute(
            """SELECT COUNT(*) c FROM flights WHERE status NOT IN ('Ticketed','Cancelled')"""
        ).fetchone()["c"]
        open_cabs = con.execute(
            """SELECT COUNT(*) c FROM cabs WHERE status NOT IN ('Confirmed','Done','Cancelled')"""
        ).fetchone()["c"]
        missing_docs = con.execute(
            "SELECT COUNT(*) c FROM doc_checklist WHERE status='Missing'"
        ).fetchone()["c"]
        pending_approvals = con.execute(
            """SELECT
                 (SELECT COUNT(*) FROM hotels WHERE human_approved=0 AND status NOT IN ('Cancelled'))
               + (SELECT COUNT(*) FROM ferries WHERE human_approved=0 AND status NOT IN ('Cancelled'))
               as c"""
        ).fetchone()["c"]
        now = datetime.now().isoformat(timespec="minutes")
        upcoming_legs = con.execute(
            """SELECT f.id, f.direction, f.airline, f.flight_no, f.from_airport, f.to_airport,
                      f.depart_at, f.arrive_at, f.status, f.pnr, b.ref, l.name as traveller
               FROM flights f
               JOIN bookings b ON b.id=f.booking_id
               LEFT JOIN leads l ON l.id=b.lead_id
               WHERE f.depart_at >= ? AND f.status != 'Cancelled'
               ORDER BY f.depart_at LIMIT 6""",
            (now,),
        ).fetchall()
        upcoming_cabs = con.execute(
            """SELECT c.id, c.when_at, c.from_place, c.to_place, c.vehicle, c.status, c.vendor,
                      b.ref, l.name as traveller
               FROM cabs c
               JOIN bookings b ON b.id=c.booking_id
               LEFT JOIN leads l ON l.id=b.lead_id
               WHERE c.when_at >= ? AND c.status != 'Cancelled'
               ORDER BY c.when_at LIMIT 4""",
            (now,),
        ).fetchall()
        pending_hotels = con.execute(
            """SELECT h.*, b.ref FROM hotels h JOIN bookings b ON b.id=h.booking_id
               WHERE h.human_approved=0 AND h.status NOT IN ('Cancelled')
               ORDER BY h.id DESC LIMIT 8"""
        ).fetchall()
        pending_ferries = con.execute(
            """SELECT f.*, b.ref FROM ferries f JOIN bookings b ON b.id=f.booking_id
               WHERE f.human_approved=0 AND f.status NOT IN ('Cancelled')
               ORDER BY f.id DESC LIMIT 8"""
        ).fetchall()
    return render("dashboard.html", {
        "request": request, "stages": stages, "followups": followups, "upcoming": upcoming,
        "outstanding": outstanding, "today": str(date.today()), "leads": leads, "nav": "home",
        "open_flights": open_flights, "open_cabs": open_cabs,
        "upcoming_legs": upcoming_legs, "upcoming_cabs": upcoming_cabs,
        "missing_docs": missing_docs, "pending_approvals": pending_approvals,
        "balance_due": balance_due, "pending_hotels": pending_hotels,
        "pending_ferries": pending_ferries,
    })


@app.get("/leads")
def leads_page(request: Request):
    with closing(db()) as con:
        leads = con.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        packages = con.execute("SELECT * FROM packages WHERE active=1").fetchall()
        quotes = {}
        lines_by_qv = {}
        for l in leads:
            qv = current_quote(con, l["id"])
            if qv:
                quotes[l["id"]] = qv
                lines_by_qv[qv["id"]] = con.execute(
                    "SELECT * FROM quote_line_items WHERE quote_version_id=? ORDER BY sort_order, id",
                    (qv["id"],),
                ).fetchall()
    by_stage = {s: [l for l in leads if l["stage"] == s] for s in STAGES}
    return render("leads.html", {
        "request": request, "by_stage": by_stage, "stages": STAGES, "packages": packages, "nav": "leads",
        "currencies": CURRENCIES, "line_types": LINE_TYPES, "quotes": quotes, "lines_by_qv": lines_by_qv,
    })


@app.post("/leads")
def create_lead(
    name: str = Form(), phone: str = Form(""), email: str = Form(""), source: str = Form("WhatsApp"),
    pax: int = Form(2), destination: str = Form(""), travel_from: str = Form(""), travel_to: str = Form(""),
    notes: str = Form(""), country: str = Form(""), currency: str = Form(DEFAULT_CURRENCY),
):
    cur = normalize_currency(currency)
    with closing(db()) as con:
        con.execute(
            """INSERT INTO leads(name,phone,email,source,pax,destination,travel_from,travel_to,stage,notes,created_at,currency,country)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, phone, email, source, pax, destination, travel_from, travel_to, "Inquiry", notes,
             datetime.now().isoformat(timespec="seconds"), cur, country or None),
        )
        con.commit()
    return RedirectResponse("/leads", status_code=303)


@app.post("/leads/{lead_id}/stage")
def move_stage(lead_id: int, stage: str = Form()):
    if stage not in STAGES:
        return RedirectResponse("/leads", status_code=303)
    with closing(db()) as con:
        con.execute("UPDATE leads SET stage=? WHERE id=?", (stage, lead_id))
        con.commit()
    return RedirectResponse("/leads", status_code=303)


@app.post("/leads/{lead_id}/convert")
def convert(lead_id: int):
    with closing(db()) as con:
        lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            return RedirectResponse("/leads", status_code=303)
        n = con.execute("SELECT COUNT(*) c FROM bookings").fetchone()["c"] + 1001
        ref = f"RB-{n}"
        cur = normalize_currency(lead["currency"] if "currency" in lead.keys() else None)
        qv = current_quote(con, lead_id)
        quoted = (qv["total_amount"] if qv else None) or lead["quoted_inr"] or 0
        con.execute("UPDATE leads SET stage='Confirmed', quoted_inr=? WHERE id=?", (quoted, lead_id))
        con.execute(
            """INSERT INTO bookings(lead_id,customer_id,package_id,ref,travel_from,travel_to,pax,quoted_inr,status,itinerary,created_at,currency)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lead["id"], lead["customer_id"], lead["package_id"], ref, lead["travel_from"], lead["travel_to"],
             lead["pax"], quoted, "Confirmed", "", datetime.now().isoformat(timespec="seconds"), cur),
        )
        booking_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        if lead["customer_id"]:
            cust = con.execute("SELECT * FROM customers WHERE id=?", (lead["customer_id"],)).fetchone()
            if cust:
                con.execute(
                    """INSERT INTO travelers(customer_id,booking_id,name,phone,email,passport_expiry,nationality,notes)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (cust["id"], booking_id, cust["name"], cust["phone"], cust["email"],
                     cust["passport_expiry"], cust["nationality"], "Primary guest"),
                )
                trav = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                now = datetime.now().isoformat(timespec="seconds")
                for dtype, label in DOC_TYPES[:4]:
                    con.execute(
                        """INSERT INTO doc_checklist(booking_id,traveler_id,doc_type,label,status,updated_at)
                           VALUES(?,?,?,?,?,?)""",
                        (booking_id, trav, dtype, label, "Missing", now),
                    )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/leads/{lead_id}/quote")
def create_or_bump_quote(
    lead_id: int,
    label: str = Form("quote"),
    notes: str = Form(""),
    bump: str = Form(""),
):
    with closing(db()) as con:
        lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            return RedirectResponse("/leads", status_code=303)
        currency = normalize_currency(lead["currency"] if "currency" in lead.keys() else None)
        cur_q = current_quote(con, lead_id)
        if bump == "1" and cur_q:
            con.execute("UPDATE quote_versions SET is_current=0 WHERE lead_id=?", (lead_id,))
            next_v = (cur_q["version_no"] or 1) + 1
            con.execute(
                """INSERT INTO quote_versions(lead_id,version_no,currency,label,notes,total_amount,created_at,is_current)
                   VALUES(?,?,?,?,?,0,?,1)""",
                (lead_id, next_v, currency, label or f"v{next_v}", notes,
                 datetime.now().isoformat(timespec="seconds")),
            )
            new_q = current_quote(con, lead_id)
            for li in con.execute(
                "SELECT * FROM quote_line_items WHERE quote_version_id=?", (cur_q["id"],)
            ).fetchall():
                add_line(con, new_q["id"], li["line_type"], li["description"], li["qty"], li["unit_amount"], li["currency"])
            rollup_quote(con, new_q["id"])
        else:
            ensure_quote_version(con, lead_id, label=label, notes=notes)
        if lead["stage"] == "Inquiry":
            con.execute("UPDATE leads SET stage='Quoted' WHERE id=?", (lead_id,))
        con.commit()
    return RedirectResponse("/leads", status_code=303)


@app.post("/leads/{lead_id}/quote/lines")
def add_quote_line(
    lead_id: int,
    line_type: str = Form("other"),
    description: str = Form(""),
    qty: int = Form(1),
    unit_amount: int = Form(0),
    currency: str = Form(DEFAULT_CURRENCY),
):
    if line_type not in LINE_TYPES:
        line_type = "other"
    with closing(db()) as con:
        qv = ensure_quote_version(con, lead_id)
        if not qv:
            return RedirectResponse("/leads", status_code=303)
        cur = normalize_currency(currency or qv["currency"])
        add_line(con, qv["id"], line_type, description or line_type, max(qty, 1), unit_amount, cur)
        rollup_quote(con, qv["id"])
        lead = con.execute("SELECT stage FROM leads WHERE id=?", (lead_id,)).fetchone()
        if lead and lead["stage"] == "Inquiry":
            con.execute("UPDATE leads SET stage='Quoted' WHERE id=?", (lead_id,))
        con.commit()
    return RedirectResponse("/leads", status_code=303)


@app.post("/quote/lines/{line_id}/edit")
def edit_quote_line(
    line_id: int,
    line_type: str = Form("other"),
    description: str = Form(""),
    qty: int = Form(1),
    unit_amount: int = Form(0),
):
    if line_type not in LINE_TYPES:
        line_type = "other"
    with closing(db()) as con:
        li = con.execute("SELECT * FROM quote_line_items WHERE id=?", (line_id,)).fetchone()
        if not li:
            return RedirectResponse("/leads", status_code=303)
        con.execute(
            """UPDATE quote_line_items SET line_type=?, description=?, qty=?, unit_amount=? WHERE id=?""",
            (line_type, description, max(qty, 1), unit_amount, line_id),
        )
        rollup_quote(con, li["quote_version_id"])
        con.commit()
    return RedirectResponse("/leads", status_code=303)


@app.post("/quote/lines/{line_id}/delete")
def delete_quote_line(line_id: int):
    with closing(db()) as con:
        li = con.execute("SELECT * FROM quote_line_items WHERE id=?", (line_id,)).fetchone()
        if li:
            con.execute("DELETE FROM quote_line_items WHERE id=?", (line_id,))
            rollup_quote(con, li["quote_version_id"])
            con.commit()
    return RedirectResponse("/leads", status_code=303)


@app.get("/bookings")
def bookings_page(request: Request):
    with closing(db()) as con:
        bookings = con.execute(
            """SELECT b.*, p.name as package_name, l.name as traveller,
               c.nationality as guest_nationality, c.passport_expiry as guest_passport,
               c.visa_expiry as guest_visa, c.phone as guest_phone, c.city as guest_city,
               (SELECT COALESCE(SUM(amount_inr),0) FROM payments WHERE booking_id=b.id) as paid
               FROM bookings b
               LEFT JOIN packages p ON p.id=b.package_id
               LEFT JOIN leads l ON l.id=b.lead_id
               LEFT JOIN customers c ON c.id=b.customer_id
               ORDER BY b.id DESC"""
        ).fetchall()
        payments = con.execute("SELECT * FROM payments ORDER BY id DESC").fetchall()
        flights = con.execute("SELECT * FROM flights ORDER BY depart_at, id").fetchall()
        cabs = con.execute("SELECT * FROM cabs ORDER BY when_at, id").fetchall()
        hotels = con.execute("SELECT * FROM hotels ORDER BY check_in, id").fetchall()
        ferries = con.execute("SELECT * FROM ferries ORDER BY depart_at, id").fetchall()
        docs = con.execute("SELECT * FROM doc_checklist ORDER BY id").fetchall()
        travelers = con.execute("SELECT * FROM travelers ORDER BY id").fetchall()
    return render("bookings.html", {
        "request": request, "bookings": bookings, "payments": payments, "nav": "bookings",
        "flights_by": group_by(flights, "booking_id"),
        "cabs_by": group_by(cabs, "booking_id"),
        "hotels_by": group_by(hotels, "booking_id"),
        "ferries_by": group_by(ferries, "booking_id"),
        "docs_by": group_by(docs, "booking_id"),
        "travelers_by": group_by(travelers, "booking_id"),
        "flight_statuses": FLIGHT_STATUSES, "cab_statuses": CAB_STATUSES,
        "flight_directions": FLIGHT_DIRECTIONS,
        "supplier_statuses": SUPPLIER_STATUSES,
        "doc_statuses": DOC_STATUSES,
        "doc_types": DOC_TYPES,
        "draft_kinds": DRAFT_KINDS,
        "currencies": CURRENCIES,
    })


@app.post("/bookings/{booking_id}/pay")
def add_payment(booking_id: int, amount_inr: int = Form(), kind: str = Form("Advance"), note: str = Form("")):
    with closing(db()) as con:
        con.execute(
            "INSERT INTO payments(booking_id,amount_inr,kind,paid_on,note) VALUES(?,?,?,?,?)",
            (booking_id, amount_inr, kind, str(date.today()), note),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/bookings/{booking_id}/flights")
def add_flight(
    booking_id: int,
    direction: str = Form("outbound"),
    airline: str = Form(""),
    flight_no: str = Form(""),
    from_airport: str = Form(""),
    to_airport: str = Form(""),
    depart_at: str = Form(""),
    arrive_at: str = Form(""),
    pax: int = Form(1),
    pnr: str = Form(""),
    cost_inr: int = Form(0),
    status: str = Form("Inquiry"),
    notes: str = Form(""),
):
    if direction not in FLIGHT_DIRECTIONS:
        direction = "outbound"
    if status not in FLIGHT_STATUSES:
        status = "Inquiry"
    with closing(db()) as con:
        con.execute(
            """INSERT INTO flights(booking_id,direction,airline,flight_no,from_airport,to_airport,
               depart_at,arrive_at,pax,pnr,cost_inr,status,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (booking_id, direction, airline, flight_no, from_airport, to_airport,
             depart_at, arrive_at, pax, pnr, cost_inr or None, status, notes),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/flights/{flight_id}/status")
def update_flight_status(flight_id: int, status: str = Form()):
    if status not in FLIGHT_STATUSES:
        return RedirectResponse("/bookings", status_code=303)
    with closing(db()) as con:
        con.execute("UPDATE flights SET status=? WHERE id=?", (status, flight_id))
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/bookings/{booking_id}/cabs")
def add_cab(
    booking_id: int,
    when_at: str = Form(""),
    from_place: str = Form(""),
    to_place: str = Form(""),
    vehicle: str = Form(""),
    vendor: str = Form(""),
    driver_phone: str = Form(""),
    cost_inr: int = Form(0),
    status: str = Form("Needed"),
    notes: str = Form(""),
):
    if status not in CAB_STATUSES:
        status = "Needed"
    with closing(db()) as con:
        con.execute(
            """INSERT INTO cabs(booking_id,when_at,from_place,to_place,vehicle,vendor,
               driver_phone,cost_inr,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (booking_id, when_at, from_place, to_place, vehicle, vendor,
             driver_phone, cost_inr or None, status, notes),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/cabs/{cab_id}/status")
def update_cab_status(cab_id: int, status: str = Form()):
    if status not in CAB_STATUSES:
        return RedirectResponse("/bookings", status_code=303)
    with closing(db()) as con:
        con.execute("UPDATE cabs SET status=? WHERE id=?", (status, cab_id))
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/bookings/{booking_id}/hotels")
def add_hotel(
    booking_id: int,
    name: str = Form(""),
    location: str = Form(""),
    check_in: str = Form(""),
    check_out: str = Form(""),
    rooms: int = Form(1),
    room_type: str = Form(""),
    cost_inr: int = Form(0),
    currency: str = Form(""),
    status: str = Form("Inquiry"),
    notes: str = Form(""),
    confirmation_no: str = Form(""),
):
    if status not in SUPPLIER_STATUSES:
        status = "Inquiry"
    with closing(db()) as con:
        b = con.execute("SELECT currency FROM bookings WHERE id=?", (booking_id,)).fetchone()
        cur = normalize_currency(currency or (b["currency"] if b else None))
        con.execute(
            """INSERT INTO hotels(booking_id,name,location,check_in,check_out,rooms,room_type,
               cost_inr,currency,status,human_approved,notes,confirmation_no)
               VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (booking_id, name, location, check_in, check_out, rooms or 1, room_type,
             cost_inr or None, cur, status, notes, confirmation_no),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/hotels/{hotel_id}/status")
def update_hotel_status(hotel_id: int, status: str = Form()):
    if status not in SUPPLIER_STATUSES:
        return RedirectResponse("/bookings", status_code=303)
    with closing(db()) as con:
        con.execute("UPDATE hotels SET status=? WHERE id=?", (status, hotel_id))
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/hotels/{hotel_id}/approve")
def approve_hotel(hotel_id: int, approval_note: str = Form(""), human_approved: str = Form("1")):
    with closing(db()) as con:
        approved = 1 if human_approved in ("1", "on", "true", "yes") else 0
        con.execute(
            """UPDATE hotels SET human_approved=?, approved_at=?, approval_note=? WHERE id=?""",
            (approved, datetime.now().isoformat(timespec="seconds") if approved else None, approval_note, hotel_id),
        )
        if approved:
            row = con.execute("SELECT status FROM hotels WHERE id=?", (hotel_id,)).fetchone()
            if row and row["status"] in ("Inquiry", "Quoted", "Held"):
                con.execute("UPDATE hotels SET status='Confirmed' WHERE id=?", (hotel_id,))
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/bookings/{booking_id}/ferries")
def add_ferry(
    booking_id: int,
    operator: str = Form(""),
    from_port: str = Form(""),
    to_port: str = Form(""),
    depart_at: str = Form(""),
    arrive_at: str = Form(""),
    pax: int = Form(1),
    cost_inr: int = Form(0),
    currency: str = Form(""),
    status: str = Form("Inquiry"),
    notes: str = Form(""),
    ticket_ref: str = Form(""),
):
    if status not in SUPPLIER_STATUSES:
        status = "Inquiry"
    with closing(db()) as con:
        b = con.execute("SELECT currency FROM bookings WHERE id=?", (booking_id,)).fetchone()
        cur = normalize_currency(currency or (b["currency"] if b else None))
        con.execute(
            """INSERT INTO ferries(booking_id,operator,from_port,to_port,depart_at,arrive_at,pax,
               cost_inr,currency,status,human_approved,notes,ticket_ref)
               VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (booking_id, operator, from_port, to_port, depart_at, arrive_at, pax or 1,
             cost_inr or None, cur, status, notes, ticket_ref),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/ferries/{ferry_id}/status")
def update_ferry_status(ferry_id: int, status: str = Form()):
    if status not in SUPPLIER_STATUSES:
        return RedirectResponse("/bookings", status_code=303)
    with closing(db()) as con:
        con.execute("UPDATE ferries SET status=? WHERE id=?", (status, ferry_id))
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/ferries/{ferry_id}/approve")
def approve_ferry(ferry_id: int, approval_note: str = Form(""), human_approved: str = Form("1")):
    with closing(db()) as con:
        approved = 1 if human_approved in ("1", "on", "true", "yes") else 0
        con.execute(
            """UPDATE ferries SET human_approved=?, approved_at=?, approval_note=? WHERE id=?""",
            (approved, datetime.now().isoformat(timespec="seconds") if approved else None, approval_note, ferry_id),
        )
        if approved:
            row = con.execute("SELECT status FROM ferries WHERE id=?", (ferry_id,)).fetchone()
            if row and row["status"] in ("Inquiry", "Quoted", "Held"):
                con.execute("UPDATE ferries SET status='Confirmed' WHERE id=?", (ferry_id,))
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/bookings/{booking_id}/travelers")
def add_traveler(
    booking_id: int,
    name: str = Form(),
    phone: str = Form(""),
    email: str = Form(""),
    dob: str = Form(""),
    passport_no: str = Form(""),
    passport_expiry: str = Form(""),
    nationality: str = Form(""),
    notes: str = Form(""),
):
    with closing(db()) as con:
        b = con.execute("SELECT customer_id FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not b:
            return RedirectResponse("/bookings", status_code=303)
        con.execute(
            """INSERT INTO travelers(customer_id,booking_id,name,phone,email,dob,passport_no,passport_expiry,nationality,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (b["customer_id"], booking_id, name, phone, email, dob or None, passport_no or None,
             passport_expiry or None, nationality or None, notes),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/bookings/{booking_id}/docs")
def add_doc(
    booking_id: int,
    doc_type: str = Form("other"),
    label: str = Form(""),
    traveler_id: int = Form(0),
    status: str = Form("Missing"),
    notes: str = Form(""),
):
    if status not in DOC_STATUSES:
        status = "Missing"
    label_map = dict(DOC_TYPES)
    with closing(db()) as con:
        con.execute(
            """INSERT INTO doc_checklist(booking_id,traveler_id,doc_type,label,status,notes,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                booking_id,
                traveler_id or None,
                doc_type,
                label or label_map.get(doc_type, doc_type),
                status,
                notes,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.post("/docs/{doc_id}/status")
def update_doc_status(doc_id: int, status: str = Form(), notes: str = Form("")):
    if status not in DOC_STATUSES:
        return RedirectResponse("/bookings", status_code=303)
    with closing(db()) as con:
        con.execute(
            "UPDATE doc_checklist SET status=?, notes=COALESCE(NULLIF(?, ''), notes), updated_at=? WHERE id=?",
            (status, notes, datetime.now().isoformat(timespec="seconds"), doc_id),
        )
        con.commit()
    return RedirectResponse("/bookings", status_code=303)


@app.get("/bookings/{booking_id}/itinerary.html")
def booking_itinerary(request: Request, booking_id: int):
    with closing(db()) as con:
        b = booking_detail(con, booking_id)
        if not b:
            return HTMLResponse("<h1>Booking not found</h1>", status_code=404)
        flights = con.execute(
            "SELECT * FROM flights WHERE booking_id=? AND status != 'Cancelled' ORDER BY depart_at, id",
            (booking_id,),
        ).fetchall()
        cabs = con.execute(
            "SELECT * FROM cabs WHERE booking_id=? AND status != 'Cancelled' ORDER BY when_at, id",
            (booking_id,),
        ).fetchall()
        hotels = con.execute(
            "SELECT * FROM hotels WHERE booking_id=? AND status != 'Cancelled' ORDER BY check_in, id",
            (booking_id,),
        ).fetchall()
        ferries = con.execute(
            "SELECT * FROM ferries WHERE booking_id=? AND status != 'Cancelled' ORDER BY depart_at, id",
            (booking_id,),
        ).fetchall()
        travelers = con.execute(
            "SELECT * FROM travelers WHERE booking_id=? ORDER BY id", (booking_id,)
        ).fetchall()
        days_notes = (b["itinerary"] or "").strip().splitlines()
    return render("itinerary.html", {
        "request": request, "b": b, "flights": flights, "cabs": cabs,
        "hotels": hotels, "ferries": ferries, "travelers": travelers,
        "days_notes": days_notes, "nav": "bookings",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


@app.get("/bookings/{booking_id}/draft")
def draft_message(request: Request, booking_id: int, kind: str = "balance"):
    if kind not in DRAFT_KINDS:
        kind = "balance"
    with closing(db()) as con:
        draft, err = build_draft(con, booking_id, kind)
        if err:
            return HTMLResponse(f"<h1>{err}</h1>", status_code=404)
    return render("draft.html", {
        "request": request, "draft": draft, "nav": "bookings", "draft_kinds": DRAFT_KINDS,
    })


@app.get("/bookings/{booking_id}/draft.txt")
def draft_message_txt(booking_id: int, kind: str = "balance"):
    if kind not in DRAFT_KINDS:
        kind = "balance"
    with closing(db()) as con:
        draft, err = build_draft(con, booking_id, kind)
        if err:
            return PlainTextResponse(err, status_code=404)
    text = f"To: {draft['to']}\nChannel: {draft['channel']}\nSubject: {draft['subject']}\n\n{draft['body']}\n"
    return PlainTextResponse(text)


@app.post("/bookings/{booking_id}/followup-balance")
def followup_balance(booking_id: int):
    with closing(db()) as con:
        b = booking_detail(con, booking_id)
        if not b:
            return RedirectResponse("/bookings", status_code=303)
        due = max((b["quoted_inr"] or 0) - (b["paid"] or 0), 0)
        cur = normalize_currency(b["currency"] if "currency" in b.keys() else None)
        title = f"[balance] Collect {due} {cur} · {b['ref']}"
        exists = con.execute(
            "SELECT id FROM followups WHERE booking_id=? AND title=? AND done=0",
            (booking_id, title),
        ).fetchone()
        if not exists and due > 0:
            con.execute(
                "INSERT INTO followups(lead_id,booking_id,due_on,title,done) VALUES(?,?,?,?,0)",
                (b["lead_id"], booking_id, str(date.today()), title),
            )
            con.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/packages")
def packages_page(request: Request):
    with closing(db()) as con:
        packages = con.execute("SELECT * FROM packages ORDER BY id").fetchall()
    return render("packages.html", {
        "request": request, "packages": packages, "nav": "packages", "currencies": CURRENCIES,
    })


@app.post("/packages")
def add_package(name: str = Form(), destination: str = Form(""), nights: int = Form(3),
                days: int = Form(4), price_inr: int = Form(0), highlights: str = Form(""),
                currency: str = Form(DEFAULT_CURRENCY)):
    cur = normalize_currency(currency)
    with closing(db()) as con:
        con.execute(
            "INSERT INTO packages(name,destination,nights,days,price_inr,highlights,active,currency) VALUES(?,?,?,?,?,?,1,?)",
            (name, destination, nights, days, price_inr, highlights, cur),
        )
        con.commit()
    return RedirectResponse("/packages", status_code=303)


@app.get("/customers")
def customers_page(request: Request):
    with closing(db()) as con:
        customers = con.execute("SELECT * FROM customers ORDER BY id").fetchall()
    return render("customers.html", {
        "request": request, "customers": customers, "nav": "customers",
    })


@app.post("/customers")
def add_customer(
    name: str = Form(), phone: str = Form(""), email: str = Form(""), city: str = Form(""),
    nationality: str = Form(""), passport_expiry: str = Form(""), visa_expiry: str = Form(""),
    notes: str = Form(""),
):
    with closing(db()) as con:
        con.execute(
            """INSERT INTO customers(name,phone,email,city,passport_expiry,visa_expiry,notes,nationality)
               VALUES(?,?,?,?,?,?,?,?)""",
            (name, phone, email, city, passport_expiry or None, visa_expiry or None, notes, nationality or None),
        )
        con.commit()
    return RedirectResponse("/customers", status_code=303)


@app.post("/followups/{fid}/done")
def followup_done(fid: int):
    with closing(db()) as con:
        con.execute("UPDATE followups SET done=1 WHERE id=?", (fid,))
        con.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/followups")
def add_followup(title: str = Form(), due_on: str = Form(), lead_id: int = Form(0), booking_id: int = Form(0)):
    with closing(db()) as con:
        con.execute(
            "INSERT INTO followups(lead_id,booking_id,due_on,title,done) VALUES(?,?,?,?,0)",
            (lead_id or None, booking_id or None, due_on, title),
        )
        con.commit()
    return RedirectResponse("/", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8787, reload=False)
