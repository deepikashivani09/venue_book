import os
import secrets
from datetime import date
from functools import wraps

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import booking
import db

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")


# ---------- helpers ----------

def get_db():
    if "db" not in g:
        g.db = db.connect()
        db.init_schema(g.db)  # no-op once tables exist
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


@app.before_request
def load_user():
    g.user = None
    if "user_id" in session:
        g.user = get_db().execute("SELECT id, name, email, role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if g.user is None:
            session.clear()


@app.before_request
def csrf_protect():
    if request.method == "POST" and request.form.get("_csrf") != session.get("_csrf"):
        abort(400, "Your session expired. Go back, refresh the page and try again.")


@app.context_processor
def inject_helpers():
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]
    return {"csrf_token": csrf_token, "fmt_hour": booking.fmt_hour, "today": date.today().isoformat()}


@app.template_filter("inr")
def inr(n):
    return f"₹{int(n):,}"


@app.template_filter("longdate")
def longdate(iso):
    return date.fromisoformat(iso).strftime("%a, %d %b %Y")


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash("Log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        if g.user["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------- auth ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email, pw = request.form["name"].strip(), request.form["email"].strip().lower(), request.form["password"]
        if len(name) < 2 or "@" not in email or len(pw) < 8:
            flash("Enter your name, a valid email and a password of at least 8 characters.", "error")
        elif get_db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            flash("An account with this email already exists. Log in instead.", "error")
        else:
            cur = get_db().execute("INSERT INTO users (name, email, password_hash) VALUES (?,?,?)", (name, email, generate_password_hash(pw)))
            session.clear()
            session["user_id"] = cur.lastrowid
            return redirect(url_for("venues"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email, pw = request.form["email"].strip().lower(), request.form["password"]
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], pw):
            session.clear()
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("admin_panel") if user["role"] == "admin" else url_for("venues")
            return redirect(nxt)
        flash("Incorrect email or password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("venues"))


# ---------- browsing and availability ----------

@app.route("/")
def venues():
    vtype = request.args.get("type", "")
    items = booking.list_venues(get_db(), vtype or None, to_int(request.args.get("capacity")), request.args.get("q", "").strip() or None)
    return render_template("venues.html", venues=items, vtype=vtype)


@app.route("/venues/<int:venue_id>")
def venue_detail(venue_id):
    conn = get_db()
    venue = booking.get_venue(conn, venue_id) or abort(404)
    today = date.today()
    year, month = today.year, today.month
    if request.args.get("month"):
        try:
            year, month = map(int, request.args["month"].split("-"))
            date(year, month, 1)
        except ValueError:
            year, month = today.year, today.month
    selected = request.args.get("date")
    try:
        selected = date.fromisoformat(selected).isoformat() if selected else None
    except ValueError:
        selected = None

    prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    taken = booking.day_hours(conn, venue_id, selected) if selected else {}
    return render_template(
        "venue.html", venue=venue, weeks=booking.month_calendar(conn, venue, year, month),
        month_label=date(year, month, 1).strftime("%B %Y"),
        prev_month=f"{prev_m[0]}-{prev_m[1]:02d}", next_month=f"{next_m[0]}-{next_m[1]:02d}",
        current_month=f"{year}-{month:02d}", selected=selected, taken=taken,
        hours=range(venue["open_hour"], venue["close_hour"]),
    )


@app.get("/api/venues/<int:venue_id>/day")
def api_day(venue_id):
    iso = request.args.get("date", "")
    try:
        date.fromisoformat(iso)
    except ValueError:
        return jsonify(error="Invalid date"), 400
    return jsonify(taken={str(h): s for h, s in booking.day_hours(get_db(), venue_id, iso).items()})


@app.get("/api/quote")
def api_quote():
    conn = get_db()
    venue = booking.get_venue(conn, to_int(request.args.get("venue_id"), 0))
    start, end, guests = to_int(request.args.get("start"), 0), to_int(request.args.get("end"), 0), to_int(request.args.get("guests"), 1)
    if not venue or end <= start:
        return jsonify(error="Choose a valid time range"), 400
    ids = [i for i in map(to_int, request.args.get("addons", "").split(",")) if i]
    addons = conn.execute(f"SELECT * FROM addons WHERE is_active = 1 AND id IN ({','.join('?' * len(ids))}) ORDER BY id", ids).fetchall() if ids else []
    return jsonify(booking.compute_quote(venue, addons, start, end, max(guests, 1)))


# ---------- booking pipeline ----------

@app.route("/venues/<int:venue_id>/book", methods=["GET", "POST"])
@login_required
def book(venue_id):
    conn = get_db()
    venue = booking.get_venue(conn, venue_id) or abort(404)
    addons = booking.list_addons(conn)
    form = {"date": request.args.get("date", ""), "start": to_int(request.args.get("start"), venue["open_hour"]),
            "end": to_int(request.args.get("end"), venue["open_hour"] + 2), "guests": 10, "event_name": "", "addons": []}
    if request.method == "POST":
        form = {"date": request.form.get("date", ""), "start": to_int(request.form.get("start"), 0), "end": to_int(request.form.get("end"), 0),
                "guests": to_int(request.form.get("guests"), 0), "event_name": request.form.get("event_name", ""),
                "addons": [i for i in map(to_int, request.form.getlist("addons")) if i]}
        try:
            booking_id = booking.create_booking(conn, g.user["id"], venue_id, form["date"], form["start"], form["end"], form["guests"], form["event_name"], form["addons"])
            flash("Request sent. Your slot is on hold until an admin approves it. We have emailed you a confirmation.", "success")
            return redirect(url_for("invoice", booking_id=booking_id))
        except booking.BookingError as exc:
            flash(str(exc), "error")
    return render_template("book.html", venue=venue, addons=addons, form=form, hours=range(venue["open_hour"], venue["close_hour"] + 1))


@app.route("/bookings")
@login_required
def my_bookings():
    return render_template("my_bookings.html", bookings=booking.user_bookings(get_db(), g.user["id"]))


@app.post("/bookings/<int:booking_id>/cancel")
@login_required
def cancel(booking_id):
    try:
        booking.cancel_booking(get_db(), booking_id, g.user["id"])
        flash("Booking cancelled. The slot is open again.", "success")
    except booking.BookingError as exc:
        flash(str(exc), "error")
    return redirect(url_for("my_bookings"))


@app.route("/bookings/<int:booking_id>/invoice")
@login_required
def invoice(booking_id):
    data = booking.invoice_data(get_db(), booking_id) or abort(404)
    if data["booking"]["user_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(403)
    return render_template("invoice.html", **data)


# ---------- admin approval panel ----------

@app.route("/admin")
@admin_required
def admin_panel():
    status = request.args.get("status", "pending")
    if status not in ("pending", "approved", "rejected", "cancelled", "all"):
        status = "pending"
    conn = get_db()
    return render_template("admin.html", bookings=booking.admin_bookings(conn, None if status == "all" else status), status=status, counts=booking.status_counts(conn))


@app.post("/admin/bookings/<int:booking_id>/decision")
@admin_required
def admin_decision(booking_id):
    decision = {"approve": "approved", "reject": "rejected"}.get(request.form.get("decision"))
    try:
        b = booking.decide(get_db(), booking_id, g.user["id"], decision, request.form.get("note", ""))
        flash(f"Booking #{booking_id} {decision}. An email was sent to {b['email']}.", "success")
    except booking.BookingError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_panel", status=request.form.get("return_status", "pending")))


@app.route("/admin/emails")
@admin_required
def admin_emails():
    rows = get_db().execute("SELECT * FROM emails ORDER BY id DESC LIMIT 100").fetchall()
    return render_template("emails.html", emails=rows)


if __name__ == "__main__":
    app.run(debug=True)
