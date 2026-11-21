import tempfile
import unittest
import json
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import app as civic


class CivicTrackTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        civic.DATABASE = Path(self.temporary_directory.name) / "test.db"
        civic.app.config["TESTING"] = True
        civic.initialize_db()
        self.client = civic.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def signup(self):
        return self.client.post("/api/auth/signup", json={
            "full_name": "Demo Volunteer",
            "birthdate": "2008-04-12",
            "email": "demo@example.test",
            "phone": "",
            "username": "volunteer",
            "password": "first-password-123",
        })

    def test_session_signing_key_is_persistent(self):
        original_path = civic.SESSION_SECRET_FILE
        try:
            civic.SESSION_SECRET_FILE = Path(self.temporary_directory.name) / "session_secret.key"
            first_key = civic.load_secret_key()
            second_key = civic.load_secret_key()
        finally:
            civic.SESSION_SECRET_FILE = original_path
        self.assertEqual(first_key, second_key)
        self.assertEqual(len(first_key), 64)

    def test_main_routes_require_demo_login(self):
        self.assertEqual(civic.app.config["PERMANENT_SESSION_LIFETIME"], timedelta(days=14))
        self.assertTrue(civic.app.config["SESSION_REFRESH_EACH_REQUEST"])
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertNotIn(b"demo", home.data.lower())
        self.assertIn(b"/static/fonts/bitter-latin.woff2", home.data)
        self.assertIn(b"/static/site-logo.png", home.data)
        home.close()
        logo = self.client.get("/static/site-logo.png")
        self.assertEqual(logo.status_code, 200)
        self.assertTrue(logo.data.startswith(b"\x89PNG\r\n\x1a\n"))
        logo.close()
        font = self.client.get("/static/fonts/bitter-latin.woff2")
        self.assertEqual(font.status_code, 200)
        self.assertTrue(font.data.startswith(b"wOF2"))
        font.close()
        manifest = self.client.get("/static/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(json.loads(manifest.data)["display"], "standalone")
        self.assertEqual(
            [icon["src"] for icon in json.loads(manifest.data)["icons"]],
            ["/static/icons/civic-track-192.png", "/static/icons/civic-track-512.png"],
        )
        manifest.close()
        service_worker = self.client.get("/static/sw.js")
        self.assertEqual(service_worker.status_code, 200)
        service_worker.close()
        scoped_worker = self.client.get("/sw.js")
        self.assertEqual(scoped_worker.status_code, 200)
        self.assertEqual(scoped_worker.headers["Service-Worker-Allowed"], "/")
        self.assertIn(b"/static/fonts/bitter-latin.woff2", scoped_worker.data)
        scoped_worker.close()
        icon = self.client.get("/static/icons/civic-track-192.png")
        self.assertEqual(icon.mimetype, "image/png")
        icon.close()
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        signup_response = self.signup()
        self.assertEqual(signup_response.status_code, 201)
        self.assertEqual(signup_response.json["message"], "Account created.")
        cookie = signup_response.headers.get("Set-Cookie", "")
        self.assertIn("Expires=", cookie)
        expiration_text = cookie.split("Expires=", 1)[1].split(";", 1)[0]
        remaining = parsedate_to_datetime(expiration_text) - datetime.now(timezone.utc)
        self.assertGreater(remaining, timedelta(days=13, hours=23))
        self.assertLessEqual(remaining, timedelta(days=14, seconds=1))
        dashboard_response = self.client.get("/api/dashboard")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Expires=", dashboard_response.headers.get("Set-Cookie", ""))
        duplicate_signup = self.signup()
        self.assertEqual(duplicate_signup.status_code, 409)
        self.assertNotIn("demo", duplicate_signup.json["error"].lower())
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/volunteer").status_code, 401)

    def test_verification_code_expiration_and_uploaded_image_validation(self):
        self.assertEqual(self.signup().status_code, 201)
        code_response = self.client.post("/api/auth/code", json={"purpose": "reset"})
        self.assertTrue(code_response.json["message"].startswith("Verification code for "))
        code = code_response.json["demo_code"]
        with self.client.session_transaction() as session:
            session["verification"]["expires"] = (date.today() - timedelta(days=1)).isoformat()
        self.assertEqual(self.client.post("/api/auth/reset", json={
            "code": code, "password": "replacement-password",
        }).status_code, 400)
        result = self.client.post("/api/volunteer", json={
            "date": date.today().isoformat(), "activity": "Cleanup",
            "location": "Park", "hours": 1,
            "proof_photo": "data:image/png;base64,aGVsbG8=",
        })
        self.assertEqual(result.status_code, 400)

    def test_reset_change_and_account_deletion(self):
        self.assertEqual(self.signup().status_code, 201)
        code = self.client.post("/api/auth/code", json={"purpose": "reset"}).json["demo_code"]
        self.assertEqual(self.client.post("/api/auth/reset", json={
            "code": code, "password": "replacement-password",
        }).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "volunteer", "password": "replacement-password",
        }).status_code, 200)
        code = self.client.post("/api/auth/code", json={"purpose": "change"}).json["demo_code"]
        self.assertEqual(self.client.post("/api/auth/change-password", json={
            "code": code, "current_password": "replacement-password",
            "new_password": "another-password",
        }).status_code, 200)
        self.client.post("/api/volunteer", json={
            "date": date.today().isoformat(), "activity": "Garden",
            "location": "School", "hours": 2,
        })
        self.assertEqual(self.client.delete("/api/account", json={
            "password": "another-password",
        }).status_code, 200)
        status = self.client.get("/api/auth/status").json
        self.assertFalse(status["has_account"])
        self.assertEqual(self.client.get("/api/volunteer").status_code, 401)

    def test_tracking_reports_preferences_and_profile_features(self):
        self.assertEqual(self.signup().status_code, 201)
        test_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Rc8AAAAASUVORK5CYII="
        self.assertEqual(self.client.put("/api/profile", json={
            "full_name": "Demo Volunteer", "birthdate": "2008-04-12",
            "email": "demo@example.test", "phone": "", "username": "volunteer",
            "photo": test_png,
        }).status_code, 200)
        self.assertEqual(self.client.get("/api/profile").json["profile"]["photo"], test_png)
        self.assertEqual(self.client.put("/api/profile", json={
            "full_name": "Demo Volunteer", "birthdate": "2008-04-12",
            "email": "demo@example.test", "phone": "", "username": "volunteer",
            "remove_photo": True,
        }).status_code, 200)
        self.assertEqual(self.client.get("/api/profile").json["profile"]["photo"], "")
        self.assertEqual(self.client.post("/api/volunteer", json={
            "date": date.today().isoformat(), "activity": "Park cleanup",
            "location": "Maple Park", "hours": 10, "advisor": "Coach",
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/goals", json={
            "target": 10, "starts_on": date.today().isoformat(),
            "ends_on": (date.today() + timedelta(days=7)).isoformat(),
        }).status_code, 201)
        self.assertEqual(self.client.get("/api/dashboard").json["goal"]["percent"], 100)
        self.assertTrue(any(
            badge["name"].startswith("Personal goal")
            for badge in self.client.get("/api/badges").json["badges"]
        ))

        on_time = self.client.post("/api/assignments", json={
            "title": "Project", "subject": "Science",
            "due_date": (date.today() + timedelta(days=1)).isoformat(),
            "reminder_at": (date.today() + timedelta(days=1)).isoformat() + "T12:00:00",
        })
        late = self.client.post("/api/assignments", json={
            "title": "Essay", "subject": "English",
            "due_date": (date.today() - timedelta(days=1)).isoformat(),
        })
        self.assertEqual(on_time.status_code, 201)
        self.assertEqual(late.status_code, 201)
        self.client.patch(f"/api/assignments/{on_time.json['id']}", json={"completed": True})
        self.client.patch(f"/api/assignments/{late.json['id']}", json={"completed": True})
        report = self.client.get("/api/reports").json
        self.assertEqual(report["assignments_completed"], 2)
        self.assertEqual(report["assignments_on_time"], 1)

        self.assertEqual(self.client.put("/api/profile", json={
            "full_name": "Demo Volunteer", "birthdate": "2008-04-12",
            "email": "demo@example.test", "phone": "", "username": "volunteer",
        }).status_code, 200)
        self.assertEqual(self.client.post("/api/organizations", json={
            "name": "Community Club", "kind": "Club",
        }).status_code, 200)
        organization_id = self.client.get("/api/organizations").json["organizations"][0]["id"]
        organization_name = self.client.get("/api/organizations").json["organizations"][0]["name"]
        grouped_entry = self.client.post("/api/volunteer", json={
            "date": date.today().isoformat(), "activity": "Garden day",
            "location": "School garden", "hours": 1, "organization": organization_name,
        })
        self.assertEqual(grouped_entry.status_code, 201)
        self.assertEqual(grouped_entry.json["organization"], organization_name)
        self.assertGreater(organization_id, 0)
        self.assertEqual(self.client.post("/api/signatures", json={
            "name": "Advisor sample",
            "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Rc8AAAAASUVORK5CYII=",
        }).status_code, 200)
        self.assertEqual(len(self.client.get("/api/profile").json["organizations"]), 1)
        self.assertEqual(len(self.client.get("/api/profile").json["signatures"]), 1)
        self.assertEqual(self.client.put("/api/settings", json={
            "theme": "#18aabb", "font_scale": 1.15, "notifications": False,
            "reminder_time": "19:30", "period": "month", "impact_rate": 23.5,
        }).status_code, 200)
        self.assertEqual(self.client.get("/api/settings").json["impact_rate"], 23.5)

    def test_badges_at_all_milestones_and_pin_limit(self):
        self.assertEqual(self.signup().status_code, 201)
        for index in range(25):
            response = self.client.post("/api/volunteer", json={
                "date": date.today().isoformat(), "activity": f"Service {index}",
                "location": "Community", "hours": 10,
            })
            self.assertEqual(response.status_code, 201)
        badges = self.client.get("/api/badges").json["badges"]
        for milestone in (10, 25, 50, 100, 150, 200, 250):
            self.assertIn(f"{milestone}-hour milestone", {badge["name"] for badge in badges})
        for badge in badges[:3]:
            self.assertEqual(self.client.patch(
                f"/api/badges/{badge['id']}", json={"pinned": True},
            ).status_code, 200)
        self.assertEqual(self.client.patch(
            f"/api/badges/{badges[3]['id']}", json={"pinned": True},
        ).status_code, 400)


if __name__ == "__main__":
    unittest.main()
