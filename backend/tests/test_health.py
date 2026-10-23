from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoints():
    for path in ("/health", "/api/v1/health"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


def test_no_default_mubit_key(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("MUBIT_API_KEY", raising=False)
    assert Settings(_env_file=None).MUBIT_API_KEY == ""
