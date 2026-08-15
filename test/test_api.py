import pytest
from fastapi.testclient import TestClient
from src.api.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "db_connected" in data
        assert "model_loaded" in data


def test_docs_redirect():
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code in [302, 307]
        assert response.headers["location"] == "/docs"


def test_search_min_length_validation():
    with TestClient(app) as client:
        # Should return 422 Unprocessable Entity if name length < 2
        response = client.get("/api/v1/search?name=a")
        assert response.status_code == 422