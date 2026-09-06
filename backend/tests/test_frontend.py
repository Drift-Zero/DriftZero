from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_optional_dashboard_is_served_without_shadowing_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>DriftZero dashboard</h1>")
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="test",
            frontend_dir=str(tmp_path),
        )
    )

    with TestClient(app) as client:
        assert client.get("/").text == "<h1>DriftZero dashboard</h1>"
        assert client.get("/healthz").json() == {"status": "ok", "environment": "test"}
        assert client.post("/api/v1/demo/reset").status_code == 200


def test_missing_dashboard_directory_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="DRIFTZERO_FRONTEND_DIR does not exist"):
        create_app(Settings(frontend_dir=str(tmp_path / "missing")))
