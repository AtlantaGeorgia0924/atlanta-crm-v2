from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase


def recompute_and_persist_metrics(sb, source: str = "supabase_auto_update") -> dict:
    """Recompute dashboard/financial metrics and persist them into app_settings."""
    metrics = compute_metrics_from_supabase(sb)
    sb.table("app_settings").upsert(
        app_settings_payload(metrics, source=source),
        on_conflict="key",
    ).execute()
    return metrics
