"""Create the database and load demo data:  python init_db.py   (add --reset to start over)"""
import os
import sys
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

import booking
import db

PASSWORD = "Passw0rd!"


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]:
        print("Database already has data. Use --reset to start over.")
        return
    conn.execute("INSERT INTO users (name, email, password_hash, role) VALUES ('Site Admin', 'admin@venuebook.test', ?, 'admin')", (generate_password_hash(PASSWORD),))
    conn.execute("INSERT INTO users (name, email, password_hash, role) VALUES ('Asha Nair', 'user@venuebook.test', ?, 'user')", (generate_password_hash(PASSWORD),))

    venues = [
        ("Grand Banquet Hall", "banquet", "Palayamkottai, Tirunelveli", 300, 12000, 8, 23, "Chandeliers, a stage and a built-in kitchen. Suits galas, weddings and annual dinners."),
        ("Crystal Ballroom", "banquet", "Vannarpettai, Tirunelveli", 500, 20000, 10, 24, "Our largest hall with a dance floor and a private entrance for guests of honour."),
        ("Skyline Conference Room", "conference", "Technopark Road, Tirunelveli", 40, 3500, 8, 21, "Theatre or boardroom seating with a 4K display, video conferencing and high-speed Wi-Fi."),
        ("Boardroom One", "conference", "Technopark Road, Tirunelveli", 12, 1500, 8, 20, "Quiet room for leadership meetings and client presentations."),
        ("Garden Terrace", "party", "Melapalayam, Tirunelveli", 120, 6000, 10, 23, "Open-air terrace with string lights. Ideal for launches and team celebrations."),
        ("Loft Party Space", "party", "Junction, Tirunelveli", 60, 4000, 12, 24, "Industrial-style loft with a bar counter and a sound-ready floor."),
    ]
    conn.executemany("INSERT INTO venues (name, type, location, capacity, price_per_hour, open_hour, close_hour, description) VALUES (?,?,?,?,?,?,?,?)", venues)

    addons = [
        ("Buffet lunch catering", "per_guest", 650, "Vegetarian and non-vegetarian buffet, per guest."),
        ("Tea, coffee and snacks", "per_guest", 150, "Served in two rounds, per guest."),
        ("Audio system and microphones", "flat", 4500, "PA system, two wireless mics and a sound engineer."),
        ("Projector and screen", "flat", 2500, "Full HD projector with a 10 ft screen."),
        ("Stage and lighting", "flat", 9000, "Raised stage with programmable lights."),
        ("Decoration package", "flat", 12000, "Themed floral and fabric decoration."),
        ("Technical operator", "per_hour", 800, "On-site AV technician, per hour."),
    ]
    conn.executemany("INSERT INTO addons (name, pricing, price, description) VALUES (?,?,?,?)", addons)

    # A few sample bookings so the calendar has something to show.
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    demo_user = 2
    b1 = booking.create_booking(conn, demo_user, 1, d(3), 10, 14, 150, "Annual General Meeting", [1, 3])
    booking.create_booking(conn, demo_user, 1, d(3), 18, 22, 200, "Awards Night", [5, 6])
    b3 = booking.create_booking(conn, demo_user, 3, d(5), 9, 12, 30, "Quarterly Strategy Offsite", [2, 4])
    booking.create_booking(conn, demo_user, 5, d(1), 16, 20, 80, "Product Launch Party", [3])
    booking.decide(conn, b1, 1, "approved", "Looking forward to hosting you.")
    booking.decide(conn, b3, 1, "approved")


if __name__ == "__main__":
    if "--reset" in sys.argv and os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    conn = db.connect()
    db.init_schema(conn)
    seed(conn)
    print(f"Database ready at {db.DB_PATH}")
    print(f"Demo logins (password {PASSWORD}): admin@venuebook.test  |  user@venuebook.test")
