"""Runtime configuration for the DriftZero API."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    alert_evaluation_interval_seconds: int = 60
    log_level: str = "INFO"
    log_file: str | None = None
    log_file_max_bytes: int = 10_485_760
    log_file_backup_count: int = 5
    slow_query_ms: float = 250.0
    otel_enabled: bool = False
    otel_service_name: str = "driftzero-api"

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
            alert_evaluation_interval_seconds=max(
                1,
                int(
                    os.getenv(
                        "DRIFTZERO_ALERT_EVALUATION_INTERVAL_SECONDS",
                        str(defaults.alert_evaluation_interval_seconds),
                    )
                ),
            ),
            log_level=os.getenv("DRIFTZERO_LOG_LEVEL", defaults.log_level),
            log_file=os.getenv("DRIFTZERO_LOG_FILE") or defaults.log_file,
            log_file_max_bytes=int(
                os.getenv("DRIFTZERO_LOG_FILE_MAX_BYTES", str(defaults.log_file_max_bytes))
            ),
            log_file_backup_count=int(
                os.getenv(
                    "DRIFTZERO_LOG_FILE_BACKUP_COUNT",
                    str(defaults.log_file_backup_count),
                )
            ),
            slow_query_ms=float(
                os.getenv("DRIFTZERO_SLOW_QUERY_MS", str(defaults.slow_query_ms))
            ),
            otel_enabled=_environment_bool("DRIFTZERO_OTEL_ENABLED", defaults.otel_enabled),
            otel_service_name=os.getenv(
                "DRIFTZERO_OTEL_SERVICE_NAME", defaults.otel_service_name
            ),
        )
