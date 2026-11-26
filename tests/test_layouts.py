import os

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.config import settings
from app.main import app

GOOD = {
    "type": "Stack",
    "props": {"gap": 4, "onClick": "alert(1)"},
    "children": [
        {"type": "Card", "props": {"title": "Hi", "color": "Blue"}},
    ],
}
BODY = {"prompt": "pytest: hello", "title": "Hello", "ui": GOOD}


@pytest.fixture(autouse=True)
def reset_limits():
    ratelimit._hits.clear()


def test_sharing_disabled_without_database(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    with TestClient(app) as client:
        assert client.post("/api/layouts", json=BODY).status_code == 503
        assert client.get("/api/layouts/abcdefgh").status_code == 503


def test_invalid_ui_rejected_before_touching_the_database(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    body = {**BODY, "ui": {"type": "Script"}}
    with TestClient(app) as client:
        assert client.post("/api/layouts", json=body).status_code == 422


def test_malformed_slug_is_404(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    with TestClient(app) as client:
        assert client.get("/api/layouts/a").status_code == 404
        assert client.get("/api/layouts/bad.slug!").status_code == 404


# The tests below need a real Postgres. Point TEST_DATABASE_URL at a throwaway
# database (for example a free Neon branch); they are skipped otherwise.
needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@pytest.fixture
def db_client(monkeypatch):
    monkeypatch.setattr(settings, "database_url", os.environ["TEST_DATABASE_URL"])
    with TestClient(app) as client:
        yield client
    import psycopg

    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as conn:
        conn.execute("delete from layouts where prompt like 'pytest:%'")


@needs_db
def test_save_then_load_round_trip(db_client):
    saved = db_client.post("/api/layouts", json=BODY)
    assert saved.status_code == 200
    slug = saved.json()["slug"]
    assert len(slug) >= 6

    got = db_client.get(f"/api/layouts/{slug}")
    assert got.status_code == 200
    data = got.json()
    assert data["title"] == "Hello"
    assert data["prompt"] == "pytest: hello"
    # Stored copy is the cleaned one: invented props dropped, color normalised.
    assert data["ui"]["props"] == {"gap": 4.0}
    assert data["ui"]["children"][0]["props"]["color"] == "blue"
    assert "max-age" in got.headers["cache-control"]


@needs_db
def test_unknown_slug_is_404(db_client):
    assert db_client.get("/api/layouts/doesnotexist").status_code == 404


@needs_db
def test_oversized_ui_rejected(db_client):
    huge = {"type": "Text", "props": {"text": "x" * 120_000}}
    assert db_client.post("/api/layouts", json={**BODY, "ui": huge}).status_code == 413


@needs_db
def test_slugs_are_unique(db_client):
    slugs = {db_client.post("/api/layouts", json=BODY).json()["slug"] for _ in range(5)}
    assert len(slugs) == 5
