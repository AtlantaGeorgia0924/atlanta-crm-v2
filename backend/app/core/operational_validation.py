import logging
from dataclasses import dataclass

import httpx

from app.core.cache import cache_hit_rate
from app.core.config import EnvValidationIssue, settings
from app.db.supabase_client import get_supabase, get_supabase_auth

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperationalCheck:
    name: str
    ok: bool
    message: str


def _issue_to_check(issue: EnvValidationIssue) -> OperationalCheck:
    return OperationalCheck(
        name=f"env:{issue.name}",
        ok=issue.severity != "error",
        message=f"{issue.severity}: {issue.message}",
    )


def validate_required_env(production: bool | None = None) -> list[OperationalCheck]:
    return [_issue_to_check(issue) for issue in settings.validate_required_env(production=production)]


def validate_supabase_connectivity(timeout_seconds: float = 5.0) -> list[OperationalCheck]:
    checks: list[OperationalCheck] = []

    try:
        get_supabase().table("app_settings").select("key").limit(1).execute()
        checks.append(OperationalCheck("supabase:database", True, "database query succeeded"))
    except Exception as exc:
        checks.append(OperationalCheck("supabase:database", False, f"database query failed: {exc.__class__.__name__}"))

    try:
        get_supabase_auth()
        checks.append(OperationalCheck("supabase:auth", True, "auth client initialized"))
    except Exception as exc:
        checks.append(OperationalCheck("supabase:auth", False, f"auth client failed: {exc.__class__.__name__}"))

    try:
        rows = get_supabase().table("users").select("id,role,is_active").limit(5).execute().data or []
        invalid_roles = [row.get("role") for row in rows if str(row.get("role") or "").lower() not in {"admin", "staff"}]
        if invalid_roles:
            checks.append(OperationalCheck("supabase:rbac", False, "users table contains unsupported role values"))
        else:
            checks.append(OperationalCheck("supabase:rbac", True, "users table role check succeeded"))
    except Exception as exc:
        checks.append(OperationalCheck("supabase:rbac", False, f"RBAC check failed: {exc.__class__.__name__}"))

    try:
        realtime_url = settings.SUPABASE_URL.rstrip("/") + "/realtime/v1"
        headers = {"apikey": settings.SUPABASE_ANON_KEY}
        response = httpx.get(realtime_url, headers=headers, timeout=timeout_seconds)
        if response.status_code < 500:
            checks.append(OperationalCheck("supabase:realtime", True, "realtime endpoint reachable"))
        else:
            checks.append(OperationalCheck("supabase:realtime", False, f"realtime endpoint returned {response.status_code}"))
    except Exception as exc:
        checks.append(OperationalCheck("supabase:realtime", False, f"realtime endpoint failed: {exc.__class__.__name__}"))

    try:
        get_supabase().storage.list_buckets()
        checks.append(OperationalCheck("supabase:storage", True, "storage API reachable"))
    except Exception as exc:
        checks.append(OperationalCheck("supabase:storage", False, f"storage API failed: {exc.__class__.__name__}"))

    return checks


def validate_redis_connectivity() -> OperationalCheck:
    if not settings.REDIS_URL.strip():
        return OperationalCheck("redis", False, "REDIS_URL is not configured")
    status = cache_hit_rate()
    if status.get("backend") == "redis" and status.get("available"):
        return OperationalCheck("redis", True, "redis ping succeeded")
    return OperationalCheck("redis", False, "redis unavailable or falling back to local cache")


def run_startup_validation() -> list[OperationalCheck]:
    production = settings.ENV == "production"
    checks = validate_required_env(production=production)

    if not any(check.name.startswith("env:SUPABASE") and not check.ok for check in checks):
        checks.extend(validate_supabase_connectivity())
    checks.append(validate_redis_connectivity())

    for check in checks:
        log = logger.info if check.ok else logger.warning
        log("startup_check name=%s ok=%s message=%s", check.name, check.ok, check.message)

    if production:
        failures = [check for check in checks if not check.ok]
        if failures:
            names = ", ".join(check.name for check in failures)
            raise RuntimeError(f"Production startup validation failed: {names}")

    return checks
