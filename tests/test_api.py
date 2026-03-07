"""FastAPI integration tests using TestClient (no Firestore, no browser)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def mock_all_db(monkeypatch):
    """Patch db module for every test."""
    import main
    mock = MagicMock()
    mock.list_jobs.return_value = []
    mock.get_job.return_value = None
    mock.create_job.return_value = None
    mock.update_job.return_value = None
    mock.append_log.return_value = None
    mock.delete_job.return_value = None
    mock.get_logs.return_value = []
    monkeypatch.setattr(main, "db", mock)
    return mock


@pytest.fixture()
def client():
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def get_db():
    import main
    return main.db


# ── POST /scrape ─────────────────────────────────────────────────────────────

def test_post_scrape_creates_job(client, monkeypatch):
    """POST /scrape → 202 + job_id が返る。"""
    import main
    # _enqueue_job をモックして実際のCloud Tasks呼び出しを走らせない
    monkeypatch.setattr(main, "_enqueue_job", MagicMock())
    monkeypatch.setattr(main.asyncio, "create_task", MagicMock())

    resp = client.post("/scrape", json={"url": "https://maps.google.com/test", "source": "google"})
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "queued"
    get_db().create_job.assert_called_once()


def test_post_scrape_missing_url(client):
    """url が空 → 400"""
    resp = client.post("/scrape", json={"url": "", "source": "google"})
    assert resp.status_code == 400


def test_post_scrape_duplicate_url(client, monkeypatch):
    """同じURLが実行中 → 409"""
    import main
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    get_db().list_jobs.return_value = [{
        "job_id": "existing",
        "url": "https://maps.google.com/test",
        "status": "running",
        "created_at": now,
    }]

    monkeypatch.setattr(main, "_enqueue_job", MagicMock())
    monkeypatch.setattr(main.asyncio, "create_task", MagicMock())
    resp = client.post("/scrape", json={"url": "https://maps.google.com/test", "source": "google"})
    assert resp.status_code == 409


# ── GET /jobs ─────────────────────────────────────────────────────────────────

def test_get_jobs_returns_list(client):
    """GET /jobs → 200 + list"""
    get_db().list_jobs.return_value = [
        {"job_id": "j1", "status": "done", "url": "https://example.com"}
    ]
    resp = client.get("/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["job_id"] == "j1"


# ── GET /jobs/{id} ────────────────────────────────────────────────────────────

def test_get_job_found(client):
    """GET /jobs/{id} → 200 + job details"""
    get_db().get_job.return_value = {
        "job_id": "abc123",
        "url": "https://maps.google.com/test",
        "source": "google",
        "status": "done",
        "progress": 10,
        "message": "完了",
        "created_at": "2024-01-01T00:00:00+00:00",
        "review_count": 10,
    }
    resp = client.get("/jobs/abc123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "abc123"
    assert body["status"] == "done"


def test_get_job_not_found(client):
    """GET /jobs/{id} で存在しない → 404"""
    get_db().get_job.return_value = None
    resp = client.get("/jobs/notexist")
    assert resp.status_code == 404


def test_get_job_includes_error_field(client):
    """エラーフィールドが存在する場合、レスポンスに含める。"""
    get_db().get_job.return_value = {
        "job_id": "e1",
        "url": "https://x.com",
        "source": "google",
        "status": "failed",
        "progress": 0,
        "message": "エラー",
        "created_at": "2024-01-01T00:00:00+00:00",
        "review_count": 0,
        "error": "ネットワークエラー",
    }
    resp = client.get("/jobs/e1")
    assert resp.status_code == 200
    assert resp.json()["error"] == "ネットワークエラー"


# ── POST /jobs/{id}/cancel ───────────────────────────────────────────────────

def test_cancel_running_job(client):
    """running ジョブをキャンセル → 200 + cancelled"""
    get_db().get_job.return_value = {"status": "running"}
    resp = client.post("/jobs/abc/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    get_db().update_job.assert_called_once()


def test_cancel_not_running_job(client):
    """running でないジョブをキャンセル → 400"""
    get_db().get_job.return_value = {"status": "done"}
    resp = client.post("/jobs/abc/cancel")
    assert resp.status_code == 400


def test_cancel_nonexistent_job(client):
    """存在しないジョブをキャンセル → 404"""
    get_db().get_job.return_value = None
    resp = client.post("/jobs/ghost/cancel")
    assert resp.status_code == 404


# ── DELETE /jobs/{id} ────────────────────────────────────────────────────────

def test_delete_job(client):
    """DELETE /jobs/{id} → 200 + ok"""
    resp = client.delete("/jobs/abc")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    get_db().delete_job.assert_called_once_with("abc")


# ── GET /build-info ───────────────────────────────────────────────────────────

def test_build_info(client):
    """GET /build-info → revision と build_timestamp を返す。"""
    resp = client.get("/build-info")
    assert resp.status_code == 200
    body = resp.json()
    assert "revision" in body
    assert "build_timestamp" in body
