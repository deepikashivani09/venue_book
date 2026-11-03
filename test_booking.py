import os
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import booking  # noqa: E402
import db  # noqa: E402

DAY = (date.today() + timedelta(days=10)).isoformat()


class BookingTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = db.connect(self.path)
        db.init_schema(self.conn)
        c = self.conn
        c.execute("INSERT INTO users (name,email,password_hash,role) VALUES ('Admin','a@x.test','x','admin')")
        for i in range(2, 22):
            c.execute("INSERT INTO users (name,email,password_hash) VALUES (?,?,'x')", (f"U{i}", f"u{i}@x.test"))
        c.execute("INSERT INTO venues (name,type,location,capacity,price_per_hour,open_hour,close_hour) VALUES ('Hall','banquet','Here',100,1000,8,22)")
        c.execute("INSERT INTO addons (name,pricing,price) VALUES ('Catering','per_guest',100)")
        c.execute("INSERT INTO addons (name,pricing,price) VALUES ('Mic','flat',500)")

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def book(self, user, start, end, day=DAY, guests=10, addons=()):
        return booking.create_booking(self.conn, user, 1, day, start, end, guests, "Event", list(addons))

    def test_overlap_is_rejected(self):
        self.book(2, 10, 14)
        for start, end in [(10, 14), (12, 16), (8, 11), (11, 13), (9, 15)]:
            with self.assertRaises(booking.SlotTakenError, msg=f"{start}-{end}"):
                self.book(3, start, end)

    def test_back_to_back_and_other_days_are_allowed(self):
        self.book(2, 10, 12)
        self.book(3, 12, 14)
        self.book(4, 8, 10)
        self.book(5, 10, 12, day=(date.today() + timedelta(days=11)).isoformat())

    def test_rejection_frees_the_slot(self):
        first = self.book(2, 10, 14)
        with self.assertRaises(booking.SlotTakenError):
            self.book(3, 10, 14)
        booking.decide(self.conn, first, 1, "rejected", "Maintenance")
        self.book(3, 10, 14)

    def test_cancel_frees_the_slot(self):
        first = self.book(2, 10, 14)
        booking.cancel_booking(self.conn, first, 2)
        self.book(3, 10, 14)

    def test_approve_once_and_email_logged(self):
        bid = self.book(2, 10, 14)
        booking.decide(self.conn, bid, 1, "approved")
        with self.assertRaises(booking.BookingError):
            booking.decide(self.conn, bid, 1, "rejected", "late change")
        subjects = [r["subject"] for r in self.conn.execute("SELECT subject FROM emails ORDER BY id")]
        self.assertTrue(subjects[0].startswith("Booking request received"))
        self.assertTrue(subjects[1].startswith("Approved"))

    def test_reject_needs_reason(self):
        bid = self.book(2, 10, 14)
        with self.assertRaises(booking.BookingError):
            booking.decide(self.conn, bid, 1, "rejected", "  ")

    def test_invoice_maths(self):
        bid = self.book(2, 10, 14, guests=50, addons=[1, 2])
        inv = booking.invoice_data(self.conn, bid)["invoice"]
        # venue 4h x 1000 = 4000, catering 50 x 100 = 5000, mic 500 -> 9500; GST 18% = 1710
        self.assertEqual((inv["subtotal"], inv["tax"], inv["total"]), (9500, 1710, 11210))

    def test_validation(self):
        past = (date.today() - timedelta(days=1)).isoformat()
        for args in [dict(start=10, end=14, day=past), dict(start=6, end=9), dict(start=14, end=14), dict(start=20, end=23), dict(start=10, end=12, guests=500)]:
            with self.assertRaises(booking.BookingError, msg=str(args)):
                self.book(2, **args)

    def test_database_trigger_blocks_raw_sql(self):
        self.book(2, 10, 14)
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO bookings (user_id,venue_id,event_name,event_date,start_hour,end_hour,guests) VALUES (3,1,'x',?,11,13,5)", (DAY,))

    def test_concurrent_requests_only_one_wins(self):
        results = []

        def worker(uid):
            conn = db.connect(self.path)
            try:
                booking.create_booking(conn, uid, 1, DAY, 10, 14, 10, "Race", [])
                results.append("ok")
            except booking.SlotTakenError:
                results.append("taken")
            finally:
                conn.close()

        threads = [threading.Thread(target=worker, args=(uid,)) for uid in range(2, 22)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("taken"), 19)


if __name__ == "__main__":
    unittest.main()
