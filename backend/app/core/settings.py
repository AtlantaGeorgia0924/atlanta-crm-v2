from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "Atlanta CRM v2"
    api_prefix: str = "/api/v1"
    frontend_hosting: str = "Vercel"
    backend_hosting: str = "Render"
    database_provider: str = "Supabase PostgreSQL"
    source_of_truth: str = "Supabase"
    google_sheets_mode: str = "manual-sync-only"
    apply_payment_target_ms: int = 1000
    cash_flow_read_model: str = "precomputed_summary_tables"
    refresh_workspace_source: str = "supabase"

    model_config = SettingsConfigDict(
        env_prefix="ATLANTA_CRM_",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
