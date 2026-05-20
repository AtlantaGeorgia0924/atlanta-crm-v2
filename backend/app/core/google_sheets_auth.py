import base64
import json
import os

from app.core.config import settings as app_settings


class GoogleSheetsConfigError(ValueError):
    pass


def detect_google_service_account_mode(raw_value: str | None = None) -> str:
    value = str(raw_value if raw_value is not None else app_settings.GOOGLE_SERVICE_ACCOUNT_JSON or "").strip()
    if not value:
        return "empty"
    expanded_path = os.path.expanduser(value)
    if os.path.exists(expanded_path):
        return "path"
    try:
        json.loads(value)
        return "raw_json"
    except Exception:
        pass
    try:
        decoded = base64.b64decode(value).decode("utf-8")
        json.loads(decoded)
        return "base64_json"
    except Exception:
        return "invalid"


def _load_service_account_info(raw_value: str) -> dict:
    value = str(raw_value or "").strip()
    if not value:
        raise GoogleSheetsConfigError(
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

    raise GoogleSheetsConfigError(
        "Google Sheets not configured: invalid GOOGLE_SERVICE_ACCOUNT_JSON. "
        "Provide a valid file path, raw JSON object, or base64-encoded JSON."
    )


def validate_google_service_account_config() -> tuple[bool, str]:
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        build_google_service_account_credentials(scopes)
        return True, ""
    except GoogleSheetsConfigError as exc:
        return False, str(exc)


def build_google_service_account_credentials(scopes: list[str]):
    from google.oauth2.service_account import Credentials

    try:
        info = _load_service_account_info(app_settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        return Credentials.from_service_account_info(info, scopes=scopes)
    except GoogleSheetsConfigError:
        raise
    except Exception as exc:
        raise GoogleSheetsConfigError(
            "Google Sheets not configured: service account JSON is present but invalid "
            f"({str(exc)}). Re-paste the exact service account JSON in backend env."
        )
