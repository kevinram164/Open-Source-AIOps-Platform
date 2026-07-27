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
    coroot_namespace: str = "observability"
        # Phase 7B — live topology from Coroot service map
    coroot_topology_enabled: bool = True
    coroot_project_id: str = ""  # from UI URL /api/project/<id>/...
    coroot_email: str = ""  # optional session login
    coroot_password: str = ""
    # Drop control-plane/monitoring/noise from blast-radius (like Coroot UI filter)
    coroot_topology_filter: bool = True
    coroot_topology_max_neighbors: int = 25
    incident_api_url: str = ""
    postgresql_host: str = ""
    postgresql_port: int = 5432
    postgresql_database: str = "aiops"

    # LLM provider: openai | ollama
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_max_tokens: int = 4096
    ollama_base_url: str = "http://ollama.aiops-core.svc:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: int = 180
    rca_request_timeout_seconds: int = 120

    # Platform
    platform_environment: str = "dev-ocp"
    platform_cluster_name: str = "ocp01"

    @property
    def is_ready(self) -> bool:
        provider = (self.llm_provider or "openai").lower()
        if provider == "ollama":
            return bool(self.ollama_base_url)
        return bool(self.openai_api_key)


settings = Settings()
