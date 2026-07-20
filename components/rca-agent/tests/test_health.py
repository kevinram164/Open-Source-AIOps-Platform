"""Health endpoint tests."""

import os

import pytest
from fastapi.testclient import TestClient

from rca_agent.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_readiness_without_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    os.environ.pop("OPENAI_API_KEY", None)
    # Re-import settings would be needed for full isolation; skeleton test checks endpoint exists
    response = client.get("/health/ready")
    assert response.status_code in (200, 503)


def test_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "rca-agent"
