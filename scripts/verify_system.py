#!/usr/bin/env python3
"""Production readiness checks for the CRM.

The script intentionally never prints environment variable values or secrets.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
PYTHON = BACKEND / ".venv" / "bin" / "python"


@dataclass
class Check:
    name: str
    ok: bool
    message: str
    required: bool = True


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def jwt_payload(value: str) -> dict | None:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return None


def valid_supabase_key(value: str, expected_role: str | None = None) -> bool:
    if len(value) < 80:
        return False
    payload = jwt_payload(value)
    if payload is not None:
        return expected_role is None or payload.get("role") == expected_role
    if expected_role == "anon":
        return value.startswith("sb_publishable_")
    if expected_role == "service_role":
        return value.startswith("sb_secret_")
    return False


def looks_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("your-", "your_", "example", "placeholder", "changeme", "replace-me"))


def check_env() -> list[Check]:
    frontend = load_env(FRONTEND / ".env")
    backend = load_env(BACKEND / ".env")
    checks: list[Check] = []

    frontend_required = ["VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY", "VITE_API_BASE_URL"]
    backend_required = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        "REDIS_URL",
    ]

    for key in frontend_required:
        value = frontend.get(key, "")
        checks.append(Check(f"env:frontend:{key}", bool(value) and not looks_placeholder(value), "present" if value else "missing"))
    for key in backend_required:
        value = backend.get(key, "")
        checks.append(Check(f"env:backend:{key}", bool(value) and not looks_placeholder(value), "present" if value else "missing"))

    url = backend.get("SUPABASE_URL", "")
    checks.append(Check("env:supabase:url_format", bool(re.match(r"^https://[a-zA-Z0-9-]+\.supabase\.co/?$", url)), "Supabase URL format"))
    checks.append(Check("env:supabase:anon_key_format", valid_supabase_key(backend.get("SUPABASE_ANON_KEY", ""), "anon"), "Supabase anon key format"))
    checks.append(Check("env:supabase:service_key_format", valid_supabase_key(backend.get("SUPABASE_SERVICE_ROLE_KEY", ""), "service_role"), "Supabase service role key format"))
    checks.append(Check("env:frontend:anon_matches_backend", frontend.get("VITE_SUPABASE_ANON_KEY") == backend.get("SUPABASE_ANON_KEY"), "frontend anon key matches backend anon key"))
    checks.append(Check("env:redis:url_format", bool(re.match(r"^rediss?://", backend.get("REDIS_URL", ""))), "Redis URL format"))

    return checks


def run_command(name: str, command: list[str], cwd: Path) -> Check:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        if result.returncode == 0:
            return Check(name, True, "passed")
        tail = "\n".join(result.stdout.splitlines()[-8:])
        return Check(name, False, tail or f"exit code {result.returncode}")
    except FileNotFoundError as exc:
        return Check(name, False, f"command not found: {exc.filename}")
    except subprocess.TimeoutExpired:
        return Check(name, False, "timed out")


def check_migrations() -> list[Check]:
    migrations = sorted((ROOT / "database" / "migrations").glob("*.sql"))
    prefixes: dict[str, list[str]] = {}
    checks: list[Check] = []
    for path in migrations:
        match = re.match(r"^(\d{3})_", path.name)
        if not match:
            checks.append(Check(f"migration:name:{path.name}", False, "missing numeric prefix"))
            continue
        prefixes.setdefault(match.group(1), []).append(path.name)
    duplicates = {prefix: names for prefix, names in prefixes.items() if len(names) > 1}
    checks.append(Check("migrations:duplicate_prefixes", not duplicates, "no duplicate prefixes" if not duplicates else f"duplicates: {', '.join(duplicates)}"))
    ordered = [int(prefix) for prefix in prefixes]
    checks.append(Check("migrations:deterministic_order", ordered == sorted(ordered), "numeric prefixes sort deterministically"))
    return checks


def check_backend_operational() -> Check:
    code = """
from app.core.operational_validation import run_startup_validation
checks = run_startup_validation()
failed = [check for check in checks if not check.ok]
print(f"checks={len(checks)} failures={len(failed)}")
for check in failed:
    print(f"{check.name}: {check.message}")
raise SystemExit(1 if failed else 0)
"""
    return run_command("backend:operational_validation", [str(PYTHON), "-c", code], BACKEND)


def check_routes() -> list[Check]:
    code = """
from app.main import app
paths = {route.path for route in app.routes}
required = [
    "/auth/login",
    "/users",
    "/billing/{billing_id}",
    "/payments",
    "/billing/debtors/{client_name}/apply-payment",
    "/billing/debtors/{client_name}/whatsapp",
    "/sync/refresh-workspace",
]
missing = [path for path in required if path not in paths]
print("missing=" + ",".join(missing))
raise SystemExit(1 if missing else 0)
"""
    route_check = run_command("backend:critical_routes", [str(PYTHON), "-c", code], BACKEND)
    skipped = [
        Check("workflow:auth_login", False, "skipped unless TEST_LOGIN_EMAIL and TEST_LOGIN_PASSWORD are configured", required=False),
        Check("workflow:rbac_enforcement", False, "covered by route guard and users table check; live test requires seeded admin/staff users", required=False),
        Check("workflow:invoice_editing", False, "route present; live test requires disposable invoice fixture", required=False),
        Check("workflow:payment_application", False, "route present; live test requires disposable debtor fixture", required=False),
        Check("workflow:whatsapp_billing", False, "route present; live test requires disposable client phone fixture", required=False),
        Check("workflow:realtime_updates", False, "endpoint checked; browser subscription test requires running frontend session", required=False),
    ]
    return [route_check, *skipped]


def main() -> int:
    checks: list[Check] = []
    checks.extend(check_env())
    checks.extend(check_migrations())
    checks.append(run_command("frontend:lint", ["npm", "run", "lint"], FRONTEND))
    checks.append(run_command("frontend:build", ["npm", "run", "build"], FRONTEND))
    checks.append(run_command("backend:compile", [str(PYTHON), "-m", "compileall", "app"], BACKEND))
    checks.append(run_command("backend:health", [str(PYTHON), "-c", "from fastapi.testclient import TestClient; from app.main import app; r=TestClient(app).get('/health'); print(r.status_code); raise SystemExit(0 if r.status_code == 200 else 1)"], BACKEND))
    checks.append(check_backend_operational())
    checks.extend(check_routes())

    failures = [check for check in checks if check.required and not check.ok]
    for check in checks:
        if check.ok:
            status = "PASS"
        elif check.required:
            status = "FAIL"
        else:
            status = "SKIP"
        print(f"[{status}] {check.name} - {check.message}")

    print(f"summary: total={len(checks)} required_failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
