
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


# Verify the health endpoint returns the configured application identity.
def test_health_check():
    settings = get_settings()

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "application": settings.app_name,
        "version": settings.app_version,
    }
