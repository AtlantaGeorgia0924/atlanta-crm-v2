from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.operational_validation import run_startup_validation

configure_logging(level="DEBUG" if settings.ENV != "production" else "INFO")

from app.api.routes import (
    auth,
    users,
    clients,
    billing,
    inventory,
    payments,
    expenses,
    allowances,
    cashflow,
    dashboard,
    debug,
    sync,
    settings as settings_router,
)
from app.api.routes import debug
from app.api.routes import admin
from app.api.routes import cashflow_audit

fastapi_app = FastAPI(
    title="CRM API",
    version="1.0.0",
    docs_url="/docs" if settings.ENV != "production" else None,
    redoc_url=None,
)

# ── Routers ────────────────────────────────────────────────
fastapi_app.include_router(auth.router,            prefix="/auth",       tags=["Auth"])
fastapi_app.include_router(users.router,           prefix="/users",      tags=["Users"])
fastapi_app.include_router(clients.router,         prefix="/clients",    tags=["Clients"])
fastapi_app.include_router(billing.router,         prefix="/billing",    tags=["Billing"])
fastapi_app.include_router(inventory.router,       prefix="/inventory",  tags=["Inventory"])
fastapi_app.include_router(payments.router,        prefix="/payments",   tags=["Payments"])
fastapi_app.include_router(expenses.router,        prefix="/expenses",   tags=["Expenses"])
fastapi_app.include_router(allowances.router,      prefix="/allowances", tags=["Allowances"])
fastapi_app.include_router(cashflow.router,        prefix="/cashflow",   tags=["CashFlow"])
fastapi_app.include_router(cashflow_audit.router,  prefix="/cashflow",   tags=["CashFlow"])
fastapi_app.include_router(dashboard.router,       prefix="/dashboard",  tags=["Dashboard"])
fastapi_app.include_router(debug.router, prefix="/debug", tags=["Debug"])
fastapi_app.include_router(sync.router,            prefix="/sync",       tags=["Sync"])
fastapi_app.include_router(settings_router.router, prefix="/settings",   tags=["Settings"])
fastapi_app.include_router(admin.router,           prefix="/admin",      tags=["Admin"])


@fastapi_app.get("/health")
def health():
    return {"status": "ok"}


@fastapi_app.on_event("startup")
def validate_operational_readiness():
    run_startup_validation()


# Wrap the FastAPI app with CORS as the outermost ASGI layer so even unexpected
# 500 responses still carry CORS headers instead of surfacing as opaque
# browser-side "CORS errors".
app = CORSMiddleware(
    app=fastapi_app,
    allow_origins=settings.origins,
    allow_origin_regex=settings.ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
