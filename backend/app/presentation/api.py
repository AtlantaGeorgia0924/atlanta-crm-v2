from fastapi import APIRouter, Depends, status

from app.application.services import (
    apply_payment,
    get_cash_flow_summary,
    get_system_status,
    prepare_initial_import,
    refresh_workspace,
    sync_to_google_sheets,
)
from app.core.settings import Settings, get_settings

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system/status")
def system_status(settings: Settings = Depends(get_settings)) -> dict:
    return get_system_status(settings)


@router.post("/workspace/refresh")
def workspace_refresh(settings: Settings = Depends(get_settings)) -> dict:
    return refresh_workspace(settings).model_dump()


@router.post("/imports/google-sheets")
def google_sheets_import() -> dict:
    return prepare_initial_import()


@router.post("/sync/google-sheets")
def google_sheets_sync(settings: Settings = Depends(get_settings)) -> dict:
    return sync_to_google_sheets(settings).model_dump()


@router.get("/cash-flow/summary")
def cash_flow_summary(settings: Settings = Depends(get_settings)) -> dict:
    return get_cash_flow_summary(settings).model_dump()


@router.post("/cash-flow/recalculate", status_code=status.HTTP_202_ACCEPTED)
def cash_flow_recalculate() -> dict[str, str | bool]:
    return {"status": "queued", "async": True}


@router.post("/debtors/apply-payment")
def debtors_apply_payment(settings: Settings = Depends(get_settings)) -> dict:
    return apply_payment(settings).model_dump()
