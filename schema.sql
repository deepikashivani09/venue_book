PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS venues (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL,
  type           TEXT NOT NULL CHECK (type IN ('banquet', 'conference', 'party')),
  location       TEXT NOT NULL,
  capacity       INTEGER NOT NULL CHECK (capacity > 0),
  price_per_hour INTEGER NOT NULL CHECK (price_per_hour >= 0),   -- rupees
  open_hour      INTEGER NOT NULL DEFAULT 8  CHECK (open_hour BETWEEN 0 AND 23),
  close_hour     INTEGER NOT NULL DEFAULT 23 CHECK (close_hour BETWEEN 1 AND 24),
  description    TEXT NOT NULL DEFAULT '',
  CHECK (close_hour > open_hour)
);

CREATE TABLE IF NOT EXISTS addons (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  pricing     TEXT NOT NULL CHECK (pricing IN ('flat', 'per_hour', 'per_guest')),
  price       INTEGER NOT NULL CHECK (price >= 0),
  description TEXT NOT NULL DEFAULT '',
  is_active   INTEGER NOT NULL DEFAULT 1
);

-- One booking = one venue, one date, one continuous block of whole hours [start_hour, end_hour).
CREATE TABLE IF NOT EXISTS bookings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id),
  venue_id    INTEGER NOT NULL REFERENCES venues(id),
  event_name  TEXT NOT NULL,
  event_date  TEXT NOT NULL,                       -- YYYY-MM-DD
  start_hour  INTEGER NOT NULL CHECK (start_hour BETWEEN 0 AND 23),
  end_hour    INTEGER NOT NULL CHECK (end_hour BETWEEN 1 AND 24),
  guests      INTEGER NOT NULL CHECK (guests > 0),
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
  admin_note  TEXT,
  decided_by  INTEGER REFERENCES users(id),
  decided_at  TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (end_hour > start_hour)
);
CREATE INDEX IF NOT EXISTS idx_bookings_lookup ON bookings(venue_id, event_date, status);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);

-- Double-booking guard enforced by the database itself, so no code path can bypass it.
-- Two time blocks overlap when new.start < existing.end AND new.end > existing.start.
-- Back-to-back bookings (10-12 then 12-14) are allowed. Pending requests hold the slot;
-- rejected and cancelled bookings release it.
CREATE TRIGGER IF NOT EXISTS prevent_double_booking
BEFORE INSERT ON bookings
WHEN NEW.status IN ('pending', 'approved')
BEGIN
  SELECT RAISE(ABORT, 'SLOT_TAKEN')
  WHERE EXISTS (
    SELECT 1 FROM bookings b
     WHERE b.venue_id   = NEW.venue_id
       AND b.event_date = NEW.event_date
       AND b.status IN ('pending', 'approved')
       AND NEW.start_hour < b.end_hour
       AND NEW.end_hour   > b.start_hour
  );
END;

-- Prices are copied onto the booking so later price changes never alter an issued invoice.
CREATE TABLE IF NOT EXISTS booking_lines (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id  INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  quantity    INTEGER NOT NULL,
  unit_price  INTEGER NOT NULL,
  amount      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id     INTEGER NOT NULL UNIQUE REFERENCES bookings(id) ON DELETE CASCADE,
  invoice_number TEXT NOT NULL UNIQUE,
  subtotal       INTEGER NOT NULL,
  tax            INTEGER NOT NULL,
  total          INTEGER NOT NULL,
  issued_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every email the system sends (or would send) is recorded here.
CREATE TABLE IF NOT EXISTS emails (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  to_addr    TEXT NOT NULL,
  subject    TEXT NOT NULL,
  body       TEXT NOT NULL,
  status     TEXT NOT NULL,                        -- sent | logged | failed
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
