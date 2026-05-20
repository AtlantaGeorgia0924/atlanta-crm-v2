import base64
import json
import os

from app.core.config import settings as app_settings


def _load_service_account_info(raw_value: str) -> dict:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError(
            "Google Sheets not configured: GOOGLE_SERVICE_ACCOUNT_JSON is empty. "
            "Set it to a JSON file path, raw JSON, or base64-encoded JSON."
        )

    # 1) Treat as filesystem path when it exists.
    expanded_path = os.path.expanduser(value)
    if os.path.exists(expanded_path):
        with open(expanded_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # 2) Treat as raw JSON payload.
    try:
        return json.loads(value)
    except Exception:
        pass

    # 3) Treat as base64-encoded JSON payload.
    try:
        decoded = base64.b64decode(value).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        pass

    raise ValueError(
        "Google Sheets not configured: invalid GOOGLE_SERVICE_ACCOUNT_JSON. "
        "Provide a valid file path, raw JSON object, or base64-encoded JSON."
    )


def validate_google_service_account_config() -> tuple[bool, str]:
    try:
        _load_service_account_info(app_settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        return True, ""
    except ValueError as exc:
        return False, str(exc)


def build_google_service_account_credentials(scopes: list[str]):
    from google.oauth2.service_account import Credentials

    info = _load_service_account_info(app_settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    return Credentials.from_service_account_info(info, scopes=scopes)
