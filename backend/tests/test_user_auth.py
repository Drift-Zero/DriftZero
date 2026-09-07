"""User sessions, password storage, CSRF, and tenant isolation."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import User
from app.main import create_app


def _register(
    client: TestClient, email: str, tenant: str
) -> tuple[dict[str, object], str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": email.split("@", 1)[0],
            "tenant_name": tenant,
        },
    )
    assert response.status_code == 201
    return response.json(), response.headers["set-cookie"]


def test_cookie_sessions_hash_passwords_require_csrf_and_isolate_tenants() -> None:
    app = create_app(
        Settings(database_url="sqlite://", environment="test", api_require_auth=True)
    )

    with TestClient(app) as first, TestClient(app) as second:
        first_auth, set_cookie = _register(first, "alice@example.com", "Alpha")
        cookie = first.cookies.get("driftzero_session")
        assert cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie

        csrf = first_auth["csrf_token"]
        blocked = first.post("/api/v1/models", json={"name": "Alpha AI"})
        created = first.post(
            "/api/v1/models",
            json={"name": "Alpha AI"},
            headers={"X-CSRF-Token": str(csrf)},
        )
        assert blocked.status_code == 403
        assert created.status_code == 201

        second_auth, _ = _register(second, "bob@example.com", "Beta")
        second_csrf = str(second_auth["csrf_token"])
        assert second.get("/api/v1/models").json() == []
        assert second.get(f"/api/v1/models/{created.json()['id']}").status_code == 404
        assert second.post(
            "/api/v1/models",
            json={"name": "Beta AI"},
            headers={"X-CSRF-Token": second_csrf},
        ).status_code == 201

        with app.state.database.session_factory() as session:
            alice = session.scalar(select(User).where(User.email == "alice@example.com"))
            assert alice is not None
            assert alice.password_hash.startswith("$argon2id$")
            assert "correct horse" not in alice.password_hash

        assert first.post("/api/v1/auth/logout").status_code == 403
        assert first.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": str(csrf)}
        ).status_code == 204
        assert first.get("/api/v1/auth/me").status_code == 401


def test_production_registration_requires_bootstrap_secret() -> None:
    app = create_app(
        Settings(
            database_url="sqlite://",
            environment="production",
            auth_registration_token="bootstrap-secret",
        )
    )

    with TestClient(app, base_url="https://testserver") as client:
        denied = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "password": "correct horse battery staple",
                "display_name": "Owner",
                "tenant_name": "Production",
            },
        )
        accepted = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "password": "correct horse battery staple",
                "display_name": "Owner",
                "tenant_name": "Production",
            },
            headers={"X-DriftZero-Registration-Token": "bootstrap-secret"},
        )

    assert denied.status_code == 400
    assert accepted.status_code == 201
    assert "Secure" in accepted.headers["set-cookie"]
