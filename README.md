# VenueBook: Corporate Event & Venue Booking System

Python (Flask) + SQL (SQLite). Browse venues, check a calendar of free and taken slots, pick add-ons, get a mock invoice, and let an admin approve or reject, with an automatic email to the customer.

## Run it

Requires Python 3.9+.

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python init_db.py                 # creates venuebook.db with demo venues, add-ons and bookings
python app.py                     # open http://127.0.0.1:5000
```

Demo logins (password `Passw0rd!`): `user@venuebook.test` (customer) and `admin@venuebook.test` (admin).
Start over any time with `python init_db.py --reset`.

## Features

| Feature | Where |
| --- | --- |
| Venue browsing with filters (type, guests, search) | `/` |
| **Availability checker**: month calendar (free / partly booked / fully booked) plus an hourly grid for the chosen day | `/venues/<id>` |
| **Booking pipeline**: venue, date, time slot, guests, add-ons, live price estimate, then a mock invoice (printable) | `/venues/<id>/book`, `/bookings/<id>/invoice` |
| **Admin approval panel**: pending requests with Approve / Reject (reject needs a reason) | `/admin` |
| **Automatic emails** on request received, approved and rejected | `mailer.py`, log at `/admin/emails` |
| Customer can view and cancel their bookings | `/bookings` |

## How double-booking is prevented

Each booking covers whole hours `[start_hour, end_hour)` on one date. Two bookings overlap when
`new.start < existing.end AND new.end > existing.start`, so back-to-back bookings (10-12, then 12-14) are allowed.

1. **A database trigger** (`prevent_double_booking` in `schema.sql`) aborts any `INSERT` that overlaps a pending or approved booking for the same venue and date. Even hand-written SQL cannot bypass it.
2. **Transactions**: `create_booking` runs inside `BEGIN IMMEDIATE`, so simultaneous requests queue up instead of racing. A test fires 20 threads at one slot and exactly one wins.
3. **Pending requests hold the slot.** Rejecting or cancelling frees it again.

On PostgreSQL you would use an exclusion constraint instead of the trigger: `EXCLUDE USING gist (venue_id WITH =, tsrange(...) WITH &&)`.

## Emails

By default emails are printed to the console and stored in the `emails` table (visible to admins at `/admin/emails`). To send real emails, set these before `python app.py`:

```bash
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com SMTP_PASSWORD=app-password MAIL_FROM="VenueBook <you@gmail.com>"
```

(Gmail needs an app password.) If sending fails, the booking decision still goes through and the email is marked `failed`.

## Tests

```bash
python -m unittest discover -s tests -v
```

Covers overlaps, back-to-back slots, rejection and cancellation freeing slots, invoice maths, validation, the database trigger, a 20-thread race, and a full browser-style flow through the Flask app.

## Files

```
app.py            Flask routes (auth, venues, booking, admin)
booking.py        business logic: availability, pricing, create/approve/cancel
schema.sql        tables, constraints and the double-booking trigger
db.py             connection and transaction helper
mailer.py         email sending and logging
init_db.py        creates the database and demo data
templates/ static/   pages, CSS and the small booking-form script
tests/            unit and end-to-end tests
```

## Notes and limits

- Bookings are for a single day in whole-hour blocks. Multi-day events would need a datetime range per booking.
- Set `SECRET_KEY` in the environment before deploying, and run with a production server (e.g. `gunicorn app:app`) instead of `python app.py`.
- Invoices are mock invoices: no payment is collected.
