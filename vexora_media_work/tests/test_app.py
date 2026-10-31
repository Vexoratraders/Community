"""Core integration smoke tests for the VEXORA local test build."""
import os
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_db_file = Path(tempfile.gettempdir()) / f"vexora_pytest_{os.getpid()}.db"
try:
    _db_file.unlink()
except FileNotFoundError:
    pass
os.environ["VEXORA_DATABASE_URL"] = f"sqlite:///{_db_file.as_posix()}"
os.environ["VEXORA_SECRET_KEY"] = "test-only-secret-key-long-enough-for-tests-123456"
os.environ["VEXORA_DEV_EMAIL_MODE"] = "true"

from fastapi.testclient import TestClient
from app.main import app


def test_email_signup_social_and_community_flow():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        ready = client.get("/ready")
        assert ready.status_code == 200 and ready.json()["database"] == "ok"
        csrf = client.get("/api/session").json()["csrf"]
        headers = {"X-CSRF-Token": csrf}

        bad_email = client.post("/api/auth/request-code", json={"email": "not-an-email"}, headers=headers)
        assert bad_email.status_code == 400

        requested = client.post("/api/auth/request-code", json={"email": "testplayer@example.com"}, headers=headers)
        assert requested.status_code == 200
        code = requested.json()["development_code"]
        assert len(code) == 6

        wrong = client.post("/api/auth/verify-code", json={"email": "testplayer@example.com", "code": "000000" if code != "000000" else "111111"}, headers=headers)
        assert wrong.status_code == 400
        verified = client.post("/api/auth/verify-code", json={"email": "testplayer@example.com", "code": code}, headers=headers)
        assert verified.status_code == 200

        reserved = client.post("/api/auth/complete-signup", json={
            "username": "VEXORA_Admin", "password": "SafeTestPassword123!", "confirm_password": "SafeTestPassword123!"
        }, headers=headers)
        assert reserved.status_code == 400
        signup = client.post("/api/auth/complete-signup", json={
            "username": "test_player", "password": "SafeTestPassword123!", "confirm_password": "SafeTestPassword123!"
        }, headers=headers)
        assert signup.status_code == 200
        assert signup.json()["user"]["email_verified"] if "email_verified" in signup.json()["user"] else signup.json()["user"]["email"] == "testplayer@example.com"
        csrf = signup.json()["csrf"]
        headers = {"X-CSRF-Token": csrf}

        unsafe_image = client.post("/api/posts", json={"body": "This must reject remote images.", "image_url": "https://evil.example/tracker.png"}, headers=headers)
        assert unsafe_image.status_code == 400
        post = client.post("/api/posts", json={"body": "Testing VEXORA from an integration test."}, headers=headers)
        assert post.status_code == 200
        assert len(client.get("/api/feed").json()["posts"]) == 1
        post_id = client.get("/api/feed").json()["posts"][0]["id"]
        report = client.post("/api/reports", json={"target_type": "post", "target_id": post_id, "reason": "Test report"}, headers=headers)
        assert report.status_code == 200
        assert client.get("/api/admin/overview").status_code == 403
        os.environ["VEXORA_TRADE_ADMINS"] = "test_player"
        assert client.get("/api/admin/overview").status_code == 200
        news = client.post("/api/posts", json={"body": "VEXORA community announcement", "post_kind": "news"}, headers=headers)
        assert news.status_code == 200, news.text
        feed_posts = client.get("/api/feed").json()["posts"]
        assert any(p["post_kind"] == "news" and p["body"] == "VEXORA community announcement" for p in feed_posts)
        signal = client.post("/api/trades", json={"title": "EURUSD test setup", "analysis": "This is a test analysis with sufficient detail.", "market": "EURUSD", "direction": "Buy"}, headers=headers)
        assert signal.status_code == 200
        assert len(client.get("/api/trades").json()["trades"]) == 1

        denied_community = client.post("/api/communities", json={"name": "Test Gamers", "description": "A test community"}, headers=headers)
        assert denied_community.status_code == 400
        community = client.post("/api/communities", json={"name": "Test Traders", "description": "A test community", "accepted_rules": True}, headers=headers)
        assert community.status_code == 200
        assert client.get("/api/communities").json()["communities"][0]["name"] == "Test Traders"

        prefs = client.put("/api/settings", json={"theme": "light", "notifications": True, "show_online": False}, headers=headers)
        assert prefs.status_code == 200 and prefs.json()["settings"]["theme"] == "light"
        assert client.get("/api/settings").json()["settings"]["show_online"] is False
        assert client.get("/api/contacts").status_code == 200
        assert client.get("/api/profile").json()["user"]["email"] == "testplayer@example.com"

        # Mobile-friendly profile avatar upload/remove endpoints accept standard image uploads.
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        avatar_upload = client.post("/api/profile/avatar", files={"avatar": ("phone-avatar.png", png, "image/png")}, headers=headers)
        assert avatar_upload.status_code == 200, avatar_upload.text
        avatar_url = avatar_upload.json()["avatar_url"]
        assert avatar_url.startswith("/static/uploads/avatar_")
        assert client.get("/api/profile").json()["user"]["avatar_url"] == avatar_url
        avatar_remove = client.delete("/api/profile/avatar", headers=headers)
        assert avatar_remove.status_code == 200 and avatar_remove.json()["user"]["avatar_url"] == ""

        # Ordinary members cannot publish official news; configured admins can.
        os.environ["VEXORA_TRADE_ADMINS"] = ""
        denied_news = client.post("/api/posts", json={"body": "Unauthorized news", "post_kind": "news"}, headers=headers)
        assert denied_news.status_code == 403
        image_upload = client.post("/api/posts/image", files={"image": ("phone-photo.png", png, "image/png")}, headers=headers)
        assert image_upload.status_code == 200, image_upload.text
        picture_only = client.post("/api/posts", json={"body": "", "image_url": image_upload.json()["image_url"]}, headers=headers)
        assert picture_only.status_code == 200, picture_only.text
        os.environ["VEXORA_TRADE_ADMINS"] = "test_player"

        client.post("/api/logout", json={}, headers=headers)
        login_csrf = client.get("/api/session").json()["csrf"]
        login = client.post("/api/login", json={"email": "testplayer@example.com", "password": "SafeTestPassword123!"}, headers={"X-CSRF-Token": login_csrf})
        assert login.status_code == 200
        assert login.json()["user"]["username"] == "test_player"
        support = client.post("/api/ai/support", json={"message": "How do I think about trading risk?"}, headers={"X-CSRF-Token": login.json()["csrf"]})
        assert support.status_code == 200 and support.json()["assistant"] == "VEXORA Admin" and support.json()["reply"]

        # Public trader lounge messages persist and are visible in the room history.
        csrf = login.json()["csrf"]
        posted = client.post("/api/lounge/messages", json={"body": "Hello traders — testing the live lounge."}, headers={"X-CSRF-Token": csrf})
        assert posted.status_code == 200
        history = client.get("/api/lounge/messages")
        assert history.status_code == 200
        bodies = [message["body"] for message in history.json()["messages"]]
        assert "Hello traders — testing the live lounge." in bodies
        assert any(message["username"] == "VEXORA Admin" and message["body"] for message in history.json()["messages"])
        # Bot replies must survive a fresh history request / reload.
        assert client.get("/api/lounge/messages").json()["messages"] == history.json()["messages"]
        # The WebSocket path accepts a signed-in session and broadcasts newly persisted messages.
        with client.websocket_connect("/ws/lounge") as websocket:
            assert websocket.receive_json()["type"] == "connected"
            websocket.send_json({"type": "message", "body": "WebSocket room test"})
            event = websocket.receive_json()
            assert event["type"] == "lounge_message"
            assert event["body"] == "WebSocket room test"


def test_password_reset_and_passkey_guardrails():
    with TestClient(app) as client:
        csrf = client.get("/api/session").json()["csrf"]
        headers = {"X-CSRF-Token": csrf}
        requested = client.post("/api/auth/request-code", json={"email": "resetuser@example.com", "language": "English"}, headers=headers)
        assert requested.status_code == 200
        verified = client.post("/api/auth/verify-code", json={"email": "resetuser@example.com", "code": requested.json()["development_code"]}, headers=headers)
        assert verified.status_code == 200
        signup = client.post("/api/auth/complete-signup", json={"username": "reset_user", "password": "OriginalPassword123!", "confirm_password": "OriginalPassword123!"}, headers=headers)
        assert signup.status_code == 200
        csrf = signup.json()["csrf"]
        headers = {"X-CSRF-Token": csrf}
        reset = client.post("/api/auth/password-reset/request", json={"email": "resetuser@example.com"}, headers=headers)
        assert reset.status_code == 200
        code = reset.json().get("development_code")
        assert code and len(code) == 6
        changed = client.post("/api/auth/password-reset/complete", json={"email": "resetuser@example.com", "code": code, "password": "NewSecurePassword456!"}, headers=headers)
        assert changed.status_code == 200
        login_csrf = client.get("/api/session").json()["csrf"]
        login = client.post("/api/login", json={"email": "resetuser@example.com", "password": "NewSecurePassword456!"}, headers={"X-CSRF-Token": login_csrf})
        assert login.status_code == 200
        assert login.json()["user"]["username"] == "reset_user"
        assert client.get("/api/passkeys/status").status_code == 200


def _register_test_member(client, email, username, password):
    csrf = client.get('/api/session').json()['csrf']
    headers = {'X-CSRF-Token': csrf}
    requested = client.post('/api/auth/request-code', json={'email': email}, headers=headers)
    assert requested.status_code == 200, requested.text
    verified = client.post('/api/auth/verify-code', json={'email': email, 'code': requested.json()['development_code']}, headers=headers)
    assert verified.status_code == 200, verified.text
    created = client.post('/api/auth/complete-signup', json={
        'username': username, 'password': password, 'confirm_password': password
    }, headers=headers)
    assert created.status_code == 200, created.text
    return {'X-CSRF-Token': created.json()['csrf']}, created.json()['user']


def test_presence_friend_profile_and_block_privacy_between_accounts():
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_headers, alice_user = _register_test_member(alice, 'alice2@example.com', 'alice_two', 'AliceSecurePassword123!')
        bob_headers, bob_user = _register_test_member(bob, 'bob2@example.com', 'bob_two', 'BobSecurePassword123!')

        # Presence heartbeat is available on every authenticated app page, not only the Lounge.
        heartbeat = alice.post('/api/presence/heartbeat', json={}, headers=alice_headers)
        assert heartbeat.status_code == 200 and heartbeat.json()['online'] is True

        # Discover reflects the successful friend action as a Friends state.
        added = alice.post(f"/api/contacts/{bob_user['id']}", json={}, headers=alice_headers)
        assert added.status_code == 200
        people = alice.get('/api/users').json()['users']
        bob_in_discover = next(u for u in people if u['id'] == bob_user['id'])
        assert bob_in_discover['is_contact'] is True
        assert 'email' not in bob_in_discover
        contact_rows = alice.get('/api/contacts').json()['contacts']
        assert any(u['id'] == bob_user['id'] for u in contact_rows)
        assert all('email' not in u for u in contact_rows)

        # Profiles show public bio/posts, while private account identifiers are not exposed.
        profile = alice.get(f"/api/users/{bob_user['id']}/profile")
        assert profile.status_code == 200
        assert 'email' not in profile.json()['user']
        assert isinstance(profile.json()['posts'], list)

        # Blocking must make profile and DM history unavailable in either direction.
        blocked = alice.post(f"/api/users/{bob_user['id']}/block", json={}, headers=alice_headers)
        assert blocked.status_code == 200
        assert alice.get(f"/api/users/{bob_user['id']}/profile").status_code == 403
        assert alice.get(f"/api/messages/{bob_user['id']}").status_code == 403
        assert bob.get(f"/api/users/{alice_user['id']}/profile").status_code == 403


def test_security_headers_and_branding():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Powered by" in response.text and "NeeTech" in response.text
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "Content-Security-Policy" in response.headers
        assert "Referrer-Policy" in response.headers
