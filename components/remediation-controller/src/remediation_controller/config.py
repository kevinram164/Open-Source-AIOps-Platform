"""Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    log_level: str = "INFO"
    policy_path: str = "/policy/policy.yaml"
    platform_environment: str = "dev-ocp"
    max_scale_replicas_default: int = 10


settings = Settings()
