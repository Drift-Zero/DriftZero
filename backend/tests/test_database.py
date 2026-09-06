import sqlalchemy as sa

from app.db.base import Base
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


def test_unique_constraint_names_do_not_collide_on_postgres() -> None:
    names = [
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ]

    assert len(names) == len(set(names))
