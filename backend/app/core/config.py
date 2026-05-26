import base64
import json
import re
from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


_PLACEHOLDER_PATTERNS = (
    "your-",
    "your_",
    "example",
    "changeme",
    "replace-me",
    "placeholder",
)


@dataclass(frozen=True)
class EnvValidationIssue:
    name: str
    message: str
    severity: str = "error"


def _looks_placeholder(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(pattern in lowered for pattern in _PLACEHOLDER_PATTERNS)


def _jwt_payload(value: str) -> dict | None:
    parts = str(value or "").split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")))
    except Exception:
        return None


def _valid_supabase_key(value: str, expected_role: str | None = None) -> bool:
    value = str(value or "").strip()
    if len(value) < 80:
        return False
    payload = _jwt_payload(value)
    if payload is not None:
        role = str(payload.get("role") or "")
        return not expected_role or role == expected_role
    if expected_role == "anon":
        return value.startswith("sb_publishable_")
    if expected_role == "service_role":
        return value.startswith("sb_secret_")
    return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str   # server-side key (never sent to browser)
    SUPABASE_ANON_KEY: str

    # ...existing code...

    # App
    ALLOWED_ORIGINS: str = "http://localhost:5173,https://your-vercel-app.vercel.app"
    ALLOWED_ORIGIN_REGEX: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://([a-zA-Z0-9-]+\.)*vercel\.app"
    ENV: str = "development"
    REDIS_URL: str = ""

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    def validate_required_env(self, production: bool | None = None) -> list[EnvValidationIssue]:
        """Validate required configuration without exposing secret values."""
        is_production = self.ENV == "production" if production is None else production
        issues: list[EnvValidationIssue] = []

        required = {
            "SUPABASE_URL": self.SUPABASE_URL,
            "SUPABASE_SERVICE_ROLE_KEY": self.SUPABASE_SERVICE_ROLE_KEY,
            "SUPABASE_ANON_KEY": self.SUPABASE_ANON_KEY,
        }
        operational = {
            # ...existing code...
            "REDIS_URL": self.REDIS_URL,
        }

        for name, value in required.items():
            if not str(value or "").strip():
                issues.append(EnvValidationIssue(name, "missing required value"))
            elif _looks_placeholder(value):
                issues.append(EnvValidationIssue(name, "contains a placeholder value"))

        for name, value in operational.items():
            if not str(value or "").strip():
                severity = "error" if is_production else "warning"
                issues.append(EnvValidationIssue(name, "missing operational value", severity))
            elif _looks_placeholder(value):
                issues.append(EnvValidationIssue(name, "contains a placeholder value"))

        if self.SUPABASE_URL and not re.match(r"^https://[a-zA-Z0-9-]+\.supabase\.co/?$", self.SUPABASE_URL.strip()):
            issues.append(EnvValidationIssue("SUPABASE_URL", "must be a Supabase project URL"))
        if self.SUPABASE_ANON_KEY and not _valid_supabase_key(self.SUPABASE_ANON_KEY, "anon"):
            issues.append(EnvValidationIssue("SUPABASE_ANON_KEY", "does not look like a valid Supabase anon key"))
        if self.SUPABASE_SERVICE_ROLE_KEY and not _valid_supabase_key(self.SUPABASE_SERVICE_ROLE_KEY, "service_role"):
            issues.append(EnvValidationIssue("SUPABASE_SERVICE_ROLE_KEY", "does not look like a valid Supabase service role key"))
        if self.REDIS_URL and not re.match(r"^rediss?://", self.REDIS_URL.strip()):
            issues.append(EnvValidationIssue("REDIS_URL", "must start with redis:// or rediss://"))

        return issues


settings = Settings()
