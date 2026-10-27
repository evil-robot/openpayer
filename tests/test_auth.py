import pytest
from fastapi.testclient import TestClient

from openpayer import auth


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENPAYER_AUTH_SECRET", "test-secret-for-tests-only")
    monkeypatch.setenv("OPENPAYER_AUTH_DB", str(tmp_path / "auth.sqlite"))
    monkeypatch.setenv("OPENPAYER_ALLOWED_DOMAINS", "medtruth.care")
    monkeypatch.setenv("OPENPAYER_ADMIN_EMAILS", "boss@example.com")
    return tmp_path


def test_allowed_domains(env):
    assert auth.is_allowed("Person@MedTruth.care")
    assert auth.is_allowed("boss@example.com")
    assert not auth.is_allowed("person@gmail.com")
    assert not auth.is_allowed("not-an-email")


def test_token_is_single_use(env):
    raw = auth.create_token("a@medtruth.care")
    assert auth.verify_token(raw) == "a@medtruth.care"
    assert auth.verify_token(raw) is None
    assert auth.verify_token("bogus") is None


def test_gate(env):
    from openpayer.api import app

    client = TestClient(app, follow_redirects=False)
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 303
    assert client.get("/api/summary").status_code == 401
    assert client.get("/sign-in").status_code == 200

    sent = {}
    import openpayer.api as api

    monkeypatch_orig = auth.create_token("a@medtruth.care")
    resp = client.get(f"/auth/verify?token={monkeypatch_orig}", follow_redirects=False)
    assert resp.status_code == 303
    assert client.get("/").status_code == 200
