"""Runtime configuration for the DriftZero API."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _environment_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


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
    recovery_worker_interval_seconds: int = 2
    recovery_command_lease_seconds: int = 60
    recovery_command_max_attempts: int = 3
    retention_interval_seconds: int = 3600
    recovery_verification_requests: int = 50
    recovery_verification_coverage: float = 0.90
    recovery_control_url: str | None = None
    recovery_control_token: str | None = None
    recovery_control_timeout_seconds: float = 10.0
    recovery_allow_insecure_http: bool = False
    recovery_operator_api_key: str | None = None
    recovery_admin_api_key: str | None = None
    connection_secret_key: str | None = None
    connection_check_timeout_seconds: float = 8.0
    groq_api_key: str | None = None
    groq_timeout_seconds: float = 15.0
    api_require_auth: bool = False
    api_viewer_key: str | None = None
    api_operator_key: str | None = None
    api_admin_key: str | None = None
    api_rate_limit_per_minute: int = 300
    api_max_request_bytes: int = 1_048_576
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    telemetry_max_future_skew_seconds: int = 300
    docs_enabled: bool = True
    auth_registration_token: str | None = None
    auth_session_ttl_hours: int = 168
    auth_cookie_name: str = "driftzero_session"
    dashboard_cache_ttl_seconds: int = 30
    recovery_allow_local_identity: bool = False
    log_level: str = "INFO"
    log_file: str | None = None
    log_file_max_bytes: int = 10_485_760
    log_file_backup_count: int = 5
    slow_query_ms: float = 250.0
    otel_enabled: bool = False
    otel_service_name: str = "driftzero-api"
    frontend_dir: str | None = None
    cors_origins: tuple[str, ...] = ()
    cors_origin_regex: str | None = None

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
            recovery_worker_interval_seconds=max(
                1,
                int(
                    os.getenv(
                        "DRIFTZERO_RECOVERY_WORKER_INTERVAL_SECONDS",
                        str(defaults.recovery_worker_interval_seconds),
                    )
                ),
            ),
            recovery_command_lease_seconds=max(
                5,
                int(
                    os.getenv(
                        "DRIFTZERO_RECOVERY_COMMAND_LEASE_SECONDS",
                        str(defaults.recovery_command_lease_seconds),
                    )
                ),
            ),
            recovery_command_max_attempts=max(
                1,
                int(
                    os.getenv(
                        "DRIFTZERO_RECOVERY_COMMAND_MAX_ATTEMPTS",
                        str(defaults.recovery_command_max_attempts),
                    )
                ),
            ),
            retention_interval_seconds=max(
                1,
                int(
                    os.getenv(
                        "DRIFTZERO_RETENTION_INTERVAL_SECONDS",
                        str(defaults.retention_interval_seconds),
                    )
                ),
            ),
            recovery_verification_requests=max(
                1,
                int(
                    os.getenv(
                        "DRIFTZERO_RECOVERY_VERIFICATION_REQUESTS",
                        str(defaults.recovery_verification_requests),
                    )
                ),
            ),
            recovery_verification_coverage=min(
                1.0,
                max(
                    0.0,
                    float(
                        os.getenv(
                            "DRIFTZERO_RECOVERY_VERIFICATION_COVERAGE",
                            str(defaults.recovery_verification_coverage),
                        )
                    ),
                ),
            ),
            recovery_control_url=os.getenv("DRIFTZERO_RECOVERY_CONTROL_URL") or None,
            recovery_control_token=os.getenv("DRIFTZERO_RECOVERY_CONTROL_TOKEN") or None,
            recovery_control_timeout_seconds=max(
                0.1,
                float(
                    os.getenv(
                        "DRIFTZERO_RECOVERY_CONTROL_TIMEOUT_SECONDS",
                        str(defaults.recovery_control_timeout_seconds),
                    )
                ),
            ),
            recovery_allow_insecure_http=_environment_bool(
                "DRIFTZERO_RECOVERY_ALLOW_INSECURE_HTTP",
                defaults.recovery_allow_insecure_http,
            ),
            recovery_operator_api_key=os.getenv("DRIFTZERO_RECOVERY_OPERATOR_API_KEY") or None,
            recovery_admin_api_key=os.getenv("DRIFTZERO_RECOVERY_ADMIN_API_KEY") or None,
            connection_secret_key=os.getenv("DRIFTZERO_CONNECTION_SECRET_KEY") or None,
            connection_check_timeout_seconds=max(
                0.5,
                float(
                    os.getenv(
                        "DRIFTZERO_CONNECTION_CHECK_TIMEOUT_SECONDS",
                        str(defaults.connection_check_timeout_seconds),
                    )
                ),
            ),
            groq_api_key=os.getenv("DRIFTZERO_GROQ_API_KEY") or None,
            groq_timeout_seconds=max(
                0.5,
                float(
                    os.getenv(
                        "DRIFTZERO_GROQ_TIMEOUT_SECONDS",
                        str(defaults.groq_timeout_seconds),
                    )
                ),
            ),
            api_require_auth=_environment_bool(
                "DRIFTZERO_API_REQUIRE_AUTH", defaults.api_require_auth
            ),
            api_viewer_key=os.getenv("DRIFTZERO_API_VIEWER_KEY") or None,
            api_operator_key=os.getenv("DRIFTZERO_API_OPERATOR_KEY") or None,
            api_admin_key=os.getenv("DRIFTZERO_API_ADMIN_KEY") or None,
            api_rate_limit_per_minute=max(
                0,
                int(
                    os.getenv(
                        "DRIFTZERO_API_RATE_LIMIT_PER_MINUTE",
                        str(defaults.api_rate_limit_per_minute),
                    )
                ),
            ),
            api_max_request_bytes=max(
                1,
                int(
                    os.getenv(
                        "DRIFTZERO_API_MAX_REQUEST_BYTES",
                        str(defaults.api_max_request_bytes),
                    )
                ),
            ),
            trusted_hosts=_environment_list(
                "DRIFTZERO_TRUSTED_HOSTS", defaults.trusted_hosts
            ),
            telemetry_max_future_skew_seconds=max(
                0,
                int(
                    os.getenv(
                        "DRIFTZERO_TELEMETRY_MAX_FUTURE_SKEW_SECONDS",
                        str(defaults.telemetry_max_future_skew_seconds),
                    )
                ),
            ),
            docs_enabled=_environment_bool(
                "DRIFTZERO_DOCS_ENABLED",
                defaults.docs_enabled,
            ),
            auth_registration_token=os.getenv("DRIFTZERO_AUTH_REGISTRATION_TOKEN") or None,
            auth_session_ttl_hours=max(
                1,
                int(
                    os.getenv(
                        "DRIFTZERO_AUTH_SESSION_TTL_HOURS",
                        str(defaults.auth_session_ttl_hours),
                    )
                ),
            ),
            auth_cookie_name=os.getenv(
                "DRIFTZERO_AUTH_COOKIE_NAME", defaults.auth_cookie_name
            ),
            dashboard_cache_ttl_seconds=max(
                0,
                int(
                    os.getenv(
                        "DRIFTZERO_DASHBOARD_CACHE_TTL_SECONDS",
                        str(defaults.dashboard_cache_ttl_seconds),
                    )
                ),
            ),
            recovery_allow_local_identity=_environment_bool(
                "DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY",
                defaults.recovery_allow_local_identity,
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
            frontend_dir=os.getenv("DRIFTZERO_FRONTEND_DIR") or defaults.frontend_dir,
            cors_origins=_environment_list("DRIFTZERO_CORS_ORIGINS", defaults.cors_origins),
            cors_origin_regex=os.getenv("DRIFTZERO_CORS_ORIGIN_REGEX") or None,
        )
