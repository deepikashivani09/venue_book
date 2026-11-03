"""End-to-end test through the Flask app: browse, book, double-book attempt, admin approval, email."""
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AppFlow(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.environ["DATABASE"] = self.path
        import importlib
        import db, init_db, app as app_module
        importlib.reload(db); importlib.reload(init_db); importlib.reload(app_module)
        conn = db.connect(self.path); db.init_schema(conn); init_db.seed(conn); conn.close()
        self.app = app_module.app
        self.app.config["TESTING"] = True

    def tearDown(self):
        os.remove(self.path)

    def client_with_csrf(self):
        c = self.app.test_client()
        html = c.get("/login").get_data(as_text=True)
        return c, re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

    def login(self, email):
        c, token = self.client_with_csrf()
        r = c.post("/login", data={"_csrf": token, "email": email, "password": "Passw0rd!"})
        self.assertEqual(r.status_code, 302)
        return c

    def token(self, c, url="/"):
        return re.search(r'name="_csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)

    def test_pages_and_full_flow(self):
        anon = self.app.test_client()
        self.assertIn(b"Grand Banquet Hall", anon.get("/").data)
        self.assertEqual(anon.get("/?type=conference").data.count(b"Check availability"), 2)
        self.assertEqual(anon.get("/venues/1").status_code, 200)
        self.assertEqual(anon.get("/venues/1?month=2030-02&date=2030-02-10").status_code, 200)
        self.assertEqual(anon.get("/admin").status_code, 302)
        self.assertEqual(anon.get("/venues/1/book").status_code, 302)

        user = self.login("user@venuebook.test")
        self.assertEqual(user.get("/admin").status_code, 403)
        day = (date.today() + timedelta(days=20)).isoformat()
        tok = self.token(user, "/venues/2/book")
        form = {"_csrf": tok, "event_name": "Gala", "date": day, "start": "18", "end": "22", "guests": "200", "addons": ["1", "3"]}
        r = user.post("/venues/2/book", data=form)
        self.assertEqual(r.status_code, 302)
        invoice = user.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("MOCK INVOICE", invoice)
        self.assertIn("Buffet lunch catering", invoice)

        # same slot again, even for another user -> blocked with a friendly message
        other = self.app.test_client()
        t = re.search(r'name="_csrf" value="([^"]+)"', other.get("/register").get_data(as_text=True)).group(1)
        other.post("/register", data={"_csrf": t, "name": "Ravi K", "email": "ravi@x.test", "password": "longenough1"})
        t2 = self.token(other, "/venues/2/book")
        r2 = other.post("/venues/2/book", data={**form, "_csrf": t2, "start": "20", "end": "23"}, follow_redirects=True)
        self.assertIn("just been taken", r2.get_data(as_text=True))

        # availability API sees the held hours
        taken = anon.get(f"/api/venues/2/day?date={day}").get_json()["taken"]
        self.assertEqual(sorted(map(int, taken)), [18, 19, 20, 21])
        quote = anon.get("/api/quote?venue_id=2&start=18&end=22&guests=200&addons=1,3").get_json()
        self.assertEqual(quote["total"], round((4 * 20000 + 200 * 650 + 4500) * 1.18))

        # admin approves and rejects
        admin = self.login("admin@venuebook.test")
        panel = admin.get("/admin").get_data(as_text=True)
        self.assertIn("Gala", panel)
        pending_id = int(re.search(r'/admin/bookings/(\d+)/decision', panel).group(1))
        tk = self.token(admin, "/admin")
        no_reason = admin.post(f"/admin/bookings/{pending_id}/decision", data={"_csrf": tk, "decision": "reject", "note": ""}, follow_redirects=True)
        self.assertIn("Add a short reason", no_reason.get_data(as_text=True))
        ok = admin.post(f"/admin/bookings/{pending_id}/decision", data={"_csrf": tk, "decision": "reject", "note": "Venue under maintenance"}, follow_redirects=True)
        self.assertIn("rejected", ok.get_data(as_text=True))
        emails = admin.get("/admin/emails").get_data(as_text=True)
        self.assertIn("Not approved", emails)
        self.assertIn("Venue under maintenance", emails)

        # missing CSRF is refused
        self.assertEqual(user.post("/logout", data={}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
