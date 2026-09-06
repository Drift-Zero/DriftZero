"""Runtime configuration for the DriftZero API."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Application settings loaded from environment variables.

    Defaults intentionally favor a zero-setup local demo. Deployments should set
    ``DRIFTZERO_DATABASE_URL`` to a managed database connection string.
    """

    database_url: str = "sqlite:///./driftzero.db"
    api_prefix: str = "/api/v1"
    environment: str = "development"
    minimum_sample_size: int = 20
    minimum_coverage: float = 0.30
    forecast_horizon_minutes: int = 30

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            database_url=os.getenv("DRIFTZERO_DATABASE_URL", defaults.database_url),
            api_prefix=os.getenv("DRIFTZERO_API_PREFIX", defaults.api_prefix),
            environment=os.getenv("DRIFTZERO_ENVIRONMENT", defaults.environment),
            minimum_sample_size=int(
                os.getenv("DRIFTZERO_MINIMUM_SAMPLE_SIZE", str(defaults.minimum_sample_size))
            ),
            minimum_coverage=float(
                os.getenv("DRIFTZERO_MINIMUM_COVERAGE", str(defaults.minimum_coverage))
            ),
            forecast_horizon_minutes=int(
                os.getenv(
                    "DRIFTZERO_FORECAST_HORIZON_MINUTES",
                    str(defaults.forecast_horizon_minutes),
                )
            ),
        )
