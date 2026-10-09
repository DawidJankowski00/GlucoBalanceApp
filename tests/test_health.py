from fastapi.testclient import TestClient

from glucobalance.config import Settings
from glucobalance.main import create_app


def test_health_returns_ok() -> None:
    settings = Settings(app_name="TestApp", environment="test")
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "TestApp", "environment": "test"}
