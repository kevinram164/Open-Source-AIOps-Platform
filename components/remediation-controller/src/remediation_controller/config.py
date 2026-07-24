"""Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    log_level: str = "INFO"
    policy_path: str = "/policy/policy.yaml"
    gitops_targets_path: str = "/gitops/targets.yaml"
    platform_environment: str = "dev-ocp"
    max_scale_replicas_default: int = 10

    database_url: str = (
        "postgresql+asyncpg://aiops:aiops@postgres-ha-postgresql.postgres.svc.cluster.local:5432/aiops"
    )

    github_token: str = ""
    github_username: str = ""
    github_api_url: str = "https://api.github.com"

    ansible_job_namespace: str = "aiops-automation"
    ansible_job_service_account: str = "remediation-controller"
    ansible_job_image: str = ""  # default: same as controller image via env
    ansible_job_ttl_seconds: int = 600


settings = Settings()
