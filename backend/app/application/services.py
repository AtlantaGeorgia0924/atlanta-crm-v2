from app.application.contracts import (
    CashFlowSummary,
    PaymentResult,
    SyncResult,
    WorkspaceRefreshResult,
)
from app.core.settings import Settings
from app.domain.blueprint import IMPORT_TARGETS, MODULES


def get_system_status(settings: Settings) -> dict:
    return {
        "project": settings.project_name,
        "source_of_truth": settings.source_of_truth,
        "database_provider": settings.database_provider,
        "google_sheets_mode": settings.google_sheets_mode,
        "hosting": {
            "frontend": settings.frontend_hosting,
            "backend": settings.backend_hosting,
        },
        "import_targets": [target.model_dump() for target in IMPORT_TARGETS],
        "modules": [module.model_dump() for module in MODULES],
    }


def refresh_workspace(settings: Settings) -> WorkspaceRefreshResult:
    return WorkspaceRefreshResult(
        source=settings.refresh_workspace_source,
        uses_google_sheets=False,
        cache_strategy="reload-directly-from-supabase",
    )


def prepare_initial_import() -> dict:
    return {
        "mode": "initial-import",
        "preserve_history": True,
        "targets": [target.model_dump() for target in IMPORT_TARGETS],
    }


def sync_to_google_sheets(settings: Settings) -> SyncResult:
    return SyncResult(
        mode=settings.google_sheets_mode,
        trigger="manual-user-action",
        destination="google-sheets-backup",
    )


def get_cash_flow_summary(settings: Settings) -> CashFlowSummary:
    return CashFlowSummary(
        source=settings.cash_flow_read_model,
        recalculation_mode="async-only-for-heavy-jobs",
    )


def apply_payment(settings: Settings) -> PaymentResult:
    return PaymentResult(
        status="accepted",
        source="supabase",
        target_latency_ms=settings.apply_payment_target_ms,
    )
