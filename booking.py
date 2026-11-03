"""Booking business logic. No Flask in here, so it can be tested on its own."""
import calendar
import sqlite3
from datetime import date, datetime

from db import transaction
from mailer import send_email

GST_RATE = 0.18


class BookingError(Exception):
    """A problem the user can fix; the message is safe to show."""


class SlotTakenError(BookingError):
    pass


def fmt_hour(h):
    h = h % 24
    return f"{(h % 12) or 12}:00 {'AM' if h < 12 else 'PM'}"


# ---------- queries ----------

def list_venues(conn, vtype=None, min_capacity=None, search=None):
    sql, params = "SELECT * FROM venues WHERE 1=1", []
    if vtype:
        sql += " AND type = ?"; params.append(vtype)
    if min_capacity:
        sql += " AND capacity >= ?"; params.append(min_capacity)
    if search:
        sql += " AND (name LIKE ? OR location LIKE ?)"; params += [f"%{search}%"] * 2
    return conn.execute(sql + " ORDER BY name", params).fetchall()


def get_venue(conn, venue_id):
    return conn.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone()


def list_addons(conn):
    return conn.execute("SELECT * FROM addons WHERE is_active = 1 ORDER BY id").fetchall()


def day_hours(conn, venue_id, day):
    """{hour: 'approved' | 'pending'} for every hour already taken on that date."""
    taken = {}
    rows = conn.execute(
        "SELECT start_hour, end_hour, status FROM bookings WHERE venue_id = ? AND event_date = ? AND status IN ('pending','approved')",
        (venue_id, day),
    ).fetchall()
    for r in rows:
        for h in range(r["start_hour"], r["end_hour"]):
            taken[h] = r["status"]
    return taken


def month_calendar(conn, venue, year, month):
    """Weeks of day cells for the availability calendar. State: free | partial | full | past."""
    first, last = f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    rows = conn.execute(
        "SELECT event_date, start_hour, end_hour FROM bookings WHERE venue_id = ? AND event_date BETWEEN ? AND ? AND status IN ('pending','approved')",
        (venue["id"], first, last),
    ).fetchall()
    busy = {}
    for r in rows:
        busy.setdefault(r["event_date"], set()).update(range(r["start_hour"], r["end_hour"]))
    open_hours = venue["close_hour"] - venue["open_hour"]
    today = date.today()
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        cells = []
        for d in week:
            iso = d.isoformat()
            used = len([h for h in busy.get(iso, ()) if venue["open_hour"] <= h < venue["close_hour"]])
            if d < today:
                state = "past"
            elif used == 0:
                state = "free"
            elif used >= open_hours:
                state = "full"
            else:
                state = "partial"
            cells.append({"date": iso, "day": d.day, "in_month": d.month == month, "state": state, "used": used})
        weeks.append(cells)
    return weeks


# ---------- pricing ----------

def compute_quote(venue, addons, start, end, guests):
    hours = end - start
    lines = [{
        "description": f"{venue['name']} venue hire ({fmt_hour(start)} to {fmt_hour(end)})",
        "quantity": hours, "unit_price": venue["price_per_hour"], "amount": hours * venue["price_per_hour"],
    }]
    for a in addons:
        if a["pricing"] == "per_hour":
            qty = hours
        elif a["pricing"] == "per_guest":
            qty = guests
        else:
            qty = 1
        lines.append({"description": a["name"], "quantity": qty, "unit_price": a["price"], "amount": qty * a["price"]})
    subtotal = sum(l["amount"] for l in lines)
    tax = round(subtotal * GST_RATE)
    return {"lines": lines, "subtotal": subtotal, "tax": tax, "total": subtotal + tax}


# ---------- creating a booking ----------

def validate_request(venue, event_date, start, end, guests, event_name):
    if not event_name.strip():
        raise BookingError("Enter a name for your event")
    if event_date < date.today():
        raise BookingError("Choose a date from today onwards")
    if not (venue["open_hour"] <= start < end <= venue["close_hour"]):
        raise BookingError(f"This venue can be booked between {fmt_hour(venue['open_hour'])} and {fmt_hour(venue['close_hour'])}, and the end time must be after the start time")
    if event_date == date.today() and start <= datetime.now().hour:
        raise BookingError("That start time has already passed today")
    if not (1 <= guests <= venue["capacity"]):
        raise BookingError(f"Guest count must be between 1 and {venue['capacity']} for this venue")


def create_booking(conn, user_id, venue_id, event_date, start, end, guests, event_name, addon_ids):
    try:
        day = date.fromisoformat(event_date)
    except (TypeError, ValueError):
        raise BookingError("Choose a valid date")
    venue = get_venue(conn, venue_id)
    if not venue:
        raise BookingError("Venue not found")
    validate_request(venue, day, start, end, guests, event_name)

    addons = []
    if addon_ids:
        marks = ",".join("?" * len(addon_ids))
        addons = conn.execute(f"SELECT * FROM addons WHERE is_active = 1 AND id IN ({marks}) ORDER BY id", list(addon_ids)).fetchall()
    quote = compute_quote(venue, addons, start, end, guests)

    with transaction(conn):
        try:
            cur = conn.execute(
                "INSERT INTO bookings (user_id, venue_id, event_name, event_date, start_hour, end_hour, guests) VALUES (?,?,?,?,?,?,?)",
                (user_id, venue_id, event_name.strip(), event_date, start, end, guests),
            )
        except sqlite3.IntegrityError as exc:
            if "SLOT_TAKEN" in str(exc):
                raise SlotTakenError("Sorry, that time slot has just been taken. Pick another time or date")
            raise
        booking_id = cur.lastrowid
        for l in quote["lines"]:
            conn.execute(
                "INSERT INTO booking_lines (booking_id, description, quantity, unit_price, amount) VALUES (?,?,?,?,?)",
                (booking_id, l["description"], l["quantity"], l["unit_price"], l["amount"]),
            )
        conn.execute(
            "INSERT INTO invoices (booking_id, invoice_number, subtotal, tax, total) VALUES (?,?,?,?,?)",
            (booking_id, f"INV-{day:%Y%m}-{booking_id:05d}", quote["subtotal"], quote["tax"], quote["total"]),
        )

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    send_email(
        conn, user["email"], f"Booking request received: {event_name.strip()}",
        f"Hi {user['name']},\n\nWe have received your request for {venue['name']} on {event_date}, "
        f"{fmt_hour(start)} to {fmt_hour(end)}. The slot is on hold while our team reviews it.\n"
        f"Estimated total (incl. GST): Rs {quote['total']:,}\n\nYou will get another email once it is approved or rejected.\n\nVenueBook",
    )
    return booking_id


# ---------- admin decisions and cancellations ----------

def decide(conn, booking_id, admin_id, decision, note=""):
    if decision not in ("approved", "rejected"):
        raise BookingError("Unknown decision")
    note = (note or "").strip()
    if decision == "rejected" and not note:
        raise BookingError("Add a short reason so the customer knows why it was rejected")
    with transaction(conn):
        cur = conn.execute(
            "UPDATE bookings SET status = ?, admin_note = ?, decided_by = ?, decided_at = datetime('now') WHERE id = ? AND status = 'pending'",
            (decision, note or None, admin_id, booking_id),
        )
        if cur.rowcount == 0:
            raise BookingError("This request has already been handled or no longer exists")

    b = conn.execute(
        """SELECT b.*, v.name AS venue_name, u.name AS user_name, u.email, i.invoice_number, i.total
             FROM bookings b JOIN venues v ON v.id = b.venue_id JOIN users u ON u.id = b.user_id
             JOIN invoices i ON i.booking_id = b.id WHERE b.id = ?""", (booking_id,)).fetchone()
    when = f"{b['event_date']}, {fmt_hour(b['start_hour'])} to {fmt_hour(b['end_hour'])}"
    if decision == "approved":
        subject = f"Approved: {b['event_name']} at {b['venue_name']}"
        body = (f"Hi {b['user_name']},\n\nGood news! Your booking has been approved.\n\nEvent: {b['event_name']}\nVenue: {b['venue_name']}\n"
                f"When: {when}\nInvoice: {b['invoice_number']} (Rs {b['total']:,})\n" + (f"Note from our team: {note}\n" if note else "") + "\nVenueBook")
    else:
        subject = f"Not approved: {b['event_name']} at {b['venue_name']}"
        body = (f"Hi {b['user_name']},\n\nUnfortunately we could not approve your request for {b['venue_name']} on {when}.\n"
                f"Reason: {note}\n\nThe slot has been released. You are welcome to book another time.\n\nVenueBook")
    send_email(conn, b["email"], subject, body)
    return b


def cancel_booking(conn, booking_id, user_id):
    with transaction(conn):
        b = conn.execute("SELECT * FROM bookings WHERE id = ? AND user_id = ?", (booking_id, user_id)).fetchone()
        if not b:
            raise BookingError("Booking not found")
        if b["status"] not in ("pending", "approved"):
            raise BookingError("This booking can no longer be cancelled")
        if date.fromisoformat(b["event_date"]) < date.today():
            raise BookingError("Past events cannot be cancelled")
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))


# ---------- listings ----------

BOOKING_SELECT = """
  SELECT b.*, v.name AS venue_name, v.type AS venue_type, u.name AS user_name, u.email AS user_email,
         i.invoice_number, i.total
    FROM bookings b
    JOIN venues v ON v.id = b.venue_id
    JOIN users u ON u.id = b.user_id
    JOIN invoices i ON i.booking_id = b.id"""


def user_bookings(conn, user_id):
    return conn.execute(BOOKING_SELECT + " WHERE b.user_id = ? ORDER BY b.event_date DESC, b.start_hour", (user_id,)).fetchall()


def admin_bookings(conn, status=None):
    if status:
        return conn.execute(BOOKING_SELECT + " WHERE b.status = ? ORDER BY b.event_date, b.start_hour", (status,)).fetchall()
    return conn.execute(BOOKING_SELECT + " ORDER BY b.created_at DESC").fetchall()


def status_counts(conn):
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM bookings GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def invoice_data(conn, booking_id):
    b = conn.execute(BOOKING_SELECT + " WHERE b.id = ?", (booking_id,)).fetchone()
    if not b:
        return None
    inv = conn.execute("SELECT * FROM invoices WHERE booking_id = ?", (booking_id,)).fetchone()
    lines = conn.execute("SELECT * FROM booking_lines WHERE booking_id = ? ORDER BY id", (booking_id,)).fetchall()
    return {"booking": b, "invoice": inv, "lines": lines}
