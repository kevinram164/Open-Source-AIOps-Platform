"""Configuration for Incident API."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    log_format: str = "json"

    database_url: str = (
        "postgresql+asyncpg://aiops:CHANGE_ME@postgresql.aiops-core.svc:5432/aiops"
    )

    rca_agent_url: str = "http://rca-agent.aiops-core.svc:8080"
    remediation_controller_url: str = (
        "http://remediation-controller.aiops-automation.svc:8080"
    )
    nba_enabled: bool = True
    api_token: str = ""
    correlation_time_window_seconds: int = 300
    correlation_max_alerts_per_incident: int = 50

    platform_environment: str = "dev-ocp"
    platform_cluster_name: str = "ocp01"

    @property
    def is_ready(self) -> bool:
        return bool(self.database_url) and "CHANGE_ME" not in self.database_url


settings = Settings()
