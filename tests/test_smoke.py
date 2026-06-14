"""Smoke tests: app boots, key routes respond, auth gate works.

Run inside the container:  docker compose exec app pytest
External APIs are not called by these tests (§15).
"""
import os
import tempfile

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("FLASK_ENV", "development")
os.environ["ENABLE_SCHEDULER"] = "0"


@pytest.fixture()
def app():
    os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
    from app import create_app, db

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with application.app_context():
        db.create_all()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def test_healthz(client):
    assert client.get("/healthz").status_code == 200


def test_root_redirects_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_login_page_renders(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"Log in" in resp.data


def test_create_requires_auth(client):
    resp = client.get("/create", follow_redirects=False)
    assert resp.status_code == 302


def test_register_creates_no_access_user(app, client):
    resp = client.post(
        "/auth/register",
        data={
            "username": "stephen",
            "display_name": "Stephen",
            "password": "testpassword1",
            "confirm": "testpassword1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    from app import db
    from app.models import User

    with app.app_context():
        user = User.query.filter_by(username="stephen").one()
        assert user.role == "no_access"
        assert user.auth_type == "local"


FAKE_QR_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="4"/></svg>'


def test_card_composer_svg():
    """Card SVG assembles without external calls (font check is mocked)."""
    from unittest.mock import patch

    from app.services import card_composer

    class T:
        background_color = "#1E395E"
        panel_color = "#FFFFFF"
        text_color = "#FFFFFF"
        corner_style = "rounded"
        corner_radius_px = 120
        effective_radius = 120
        effective_inner_radius = 40       # independent inner radius
        qr_size_px = 900
        cta_baseline_y = 1300
        url_baseline_y = 1500

    with patch.object(card_composer, "_font_path", return_value=None), patch.object(
        card_composer, "_fit_font_size", return_value=90
    ):
        svg = card_composer.compose_svg(FAKE_QR_SVG, T(), "Scan me!", "https://x.co/a", "")
    assert svg.startswith("<svg")
    assert "Scan me!" in svg
    assert 'rx="120"' in svg                 # outer radius from slider
    assert 'rx="40"' in svg                  # independent inner radius
    assert 'width="900"' in svg              # template-driven QR size
    assert 'y="1300"' in svg and 'y="1500"' in svg   # CTA / URL positions
    assert 'font-weight="600"' in svg        # CTA SemiBold
    assert 'font-weight="300"' in svg        # URL Light


def test_qr_monkey_generate_embeds_logo(monkeypatch):
    """generate() passes the logo token and bumps ecLevel to H; no real call."""
    from app.services import qr_monkey

    captured = {}

    class FakeResp:
        status_code = 200
        content = (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            b'<circle cx="5" cy="5" r="4"/></svg>'
        )

    def fake_post(url, json=None, timeout=None, **kw):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(qr_monkey.requests, "post", fake_post)
    body, config = qr_monkey.generate("https://x.co/a", "svg", 1275, logo_token="abc.png")

    assert body.lstrip().startswith(b"<svg")
    assert captured["payload"]["config"]["logo"] == "abc.png"
    assert captured["payload"]["config"]["ecLevel"] == "H"   # logo → high EC
    assert captured["payload"]["file"] == "svg"


def test_bitly_custom_backhalf_single_call(monkeypatch):
    """A custom back-half must be one POST to /bitlinks with keyword — not a
    /shorten followed by /custom_bitlinks (which created two links)."""
    from app.services import bitly

    monkeypatch.setenv("BITLY_API_TOKEN", "tok")
    calls = []

    class FakeResp:
        status_code = 200
        def json(self):
            return {"link": "https://example.co/Promo", "id": "example.co/Promo"}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        return FakeResp()

    monkeypatch.setattr(bitly.requests, "post", fake_post)
    out = bitly.shorten("https://x.org/p", domain="example.co", custom_backhalf="Promo")

    assert len(calls) == 1                          # exactly one Bitly link created
    assert calls[0][0].endswith("/bitlinks")        # single-call endpoint
    assert calls[0][1]["keyword"] == "Promo"        # back-half set inline
    assert "custom_bitlinks" not in calls[0][0]     # not the old two-step path
    assert out["link"] == "https://example.co/Promo"


def test_bitly_plain_uses_shorten(monkeypatch):
    from app.services import bitly

    monkeypatch.setenv("BITLY_API_TOKEN", "tok")
    calls = []

    class FakeResp:
        status_code = 200
        def json(self):
            return {"link": "https://bit.ly/abc", "id": "bit.ly/abc"}

    monkeypatch.setattr(bitly.requests, "post",
                        lambda url, json=None, headers=None, timeout=None: calls.append((url, json)) or FakeResp())
    bitly.shorten("https://x.org/p", domain="bit.ly")
    assert len(calls) == 1 and calls[0][0].endswith("/shorten")
    assert "keyword" not in calls[0][1]


def test_qr_monkey_extract_token_shapes():
    """Upload response may be plain text, a JSON string, or a JSON object."""
    from app.services import qr_monkey

    class R:
        def __init__(self, text):
            self.text = text
        def json(self):
            import json as _j
            return _j.loads(self.text)  # raises ValueError on plain text

    assert qr_monkey._extract_token(R('abc123.png')) == "abc123.png"        # plain
    assert qr_monkey._extract_token(R('"abc123.png"')) == "abc123.png"      # json string
    assert qr_monkey._extract_token(R('{"file": "abc123.png"}')) == "abc123.png"  # json obj
    assert qr_monkey._extract_token(R('{"image": "z.png"}')) == "z.png"     # alt key


def test_qr_monkey_token_reuse(monkeypatch):
    """A fresh cached token is reused; a stale one triggers a re-upload."""
    from datetime import datetime, timedelta, timezone

    from app.services import qr_monkey

    uploads = {"count": 0}
    monkeypatch.setattr(qr_monkey, "upload_logo", lambda path: (uploads.__setitem__("count", uploads["count"] + 1) or "tok"))
    monkeypatch.setattr(qr_monkey, "_store_token", lambda logo, token: None)

    class L:
        qrm_token = "tok"
        qrm_token_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Fresh token → no upload
    assert qr_monkey.get_logo_token(L(), "/tmp/x.png") == "tok"
    assert uploads["count"] == 0

    # Stale token → one upload
    L.qrm_token_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
    qr_monkey.get_logo_token(L(), "/tmp/x.png")
    assert uploads["count"] == 1


def test_branding_defaults_on_login_page(client):
    resp = client.get("/auth/login")
    assert b"QRS" in resp.data
    assert b"QR &amp; Shortlink Generator" in resp.data


def _login_admin(app, client, username="boss2"):
    from app import bcrypt, db
    from app.models import User

    with app.app_context():
        db.session.add(
            User(username=username, display_name=username, auth_type="local",
                 role="admin",
                 password_hash=bcrypt.generate_password_hash("password123").decode())
        )
        db.session.commit()
    client.post("/auth/login", data={"username": username, "password": "password123",
                                     "auth_method": "local"})


def test_dashboard_help_and_scoped_stats(app, client):
    _login_admin(app, client, "dash")
    assert client.get("/").status_code == 200
    assert client.get("/help").status_code == 200
    assert client.get("/stats/?scope=me").status_code == 200
    assert b"my data" in client.get("/stats/?scope=me").data


def test_manual_harvest_trigger(app, client):
    """v2.5 troubleshooting button: runs without error when there are no
    bitly-tracked records (no external calls made)."""
    _login_admin(app, client, "harv")
    resp = client.post("/admin/troubleshoot/harvest", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Harvest complete" in resp.data


def test_create_mode_preselect(app, client):
    _login_admin(app, client, "modes")
    resp = client.get("/create?mode=qr_only")
    assert b'id="mode-qr_only" value="qr_only"\n               checked' in resp.data or (
        b'value="qr_only"' in resp.data and resp.data.count(b"checked") >= 1
    )


def test_admin_can_create_local_user(app, client):
    from app import bcrypt, db
    from app.models import User

    with app.app_context():
        db.session.add(
            User(username="boss", display_name="Boss", auth_type="local", role="admin",
                 password_hash=bcrypt.generate_password_hash("password123").decode())
        )
        db.session.commit()
    client.post("/auth/login", data={"username": "boss", "password": "password123",
                                     "auth_method": "local"})
    resp = client.post(
        "/admin/users/new",
        data={"username": "newbie", "display_name": "New User", "role": "user"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Temporary password" in resp.data
    with app.app_context():
        user = User.query.filter_by(username="newbie").one()
        assert user.role == "user"
        assert user.force_password_reset is True
