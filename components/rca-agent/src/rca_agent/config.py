"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """RCA Agent settings loaded from env / ConfigMaps."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"
    log_format: str = "json"
    host: str = "0.0.0.0"
    port: int = 8080

    # External endpoints (from aiops-endpoints ConfigMap)
    prometheus_url: str = ""
    coroot_url: str = ""
    coroot_namespace: str = "coroot"
    incident_api_url: str = ""
    postgresql_host: str = ""
    postgresql_port: int = 5432
    postgresql_database: str = "aiops"

    # OpenAI (from Secret)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_max_tokens: int = 4096
    rca_request_timeout_seconds: int = 120

    # Platform
    platform_environment: str = "homelab"
    platform_cluster_name: str = "homelab-openshift"

    @property
    def is_ready(self) -> bool:
        """Readiness requires OpenAI key; other deps checked in Phase 3."""
        return bool(self.openai_api_key)


settings = Settings()
