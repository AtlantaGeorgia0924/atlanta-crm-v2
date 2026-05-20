from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str   # server-side key (never sent to browser)
    SUPABASE_ANON_KEY: str

    # Google Sheets
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""   # path, raw JSON, or base64-encoded JSON
    GOOGLE_SHEET_ID: str = ""
    GOOGLE_SHEET_ID_STOCKS: str = ""
    GOOGLE_SHEET_ID_SERVICES: str = ""

    # App
    ALLOWED_ORIGINS: str = "http://localhost:5173,https://your-vercel-app.vercel.app"
    ENV: str = "development"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]


settings = Settings()
