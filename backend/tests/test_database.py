from app.db.session import normalize_database_url


def test_managed_postgres_urls_use_the_installed_psycopg_driver() -> None:
    assert normalize_database_url("postgres://user:pass@db.example/demo") == (
        "postgresql+psycopg://user:pass@db.example/demo"
    )
    assert normalize_database_url("postgresql://user:pass@db.example/demo") == (
        "postgresql+psycopg://user:pass@db.example/demo"
    )
    assert normalize_database_url("postgresql+psycopg://user:pass@db.example/demo") == (
        "postgresql+psycopg://user:pass@db.example/demo"
    )
