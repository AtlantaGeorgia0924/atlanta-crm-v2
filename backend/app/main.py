from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import (
    auth,
    clients,
    billing,
    inventory,
    payments,
    expenses,
    allowances,
    cashflow,
    dashboard,
    sync,
    settings as settings_router,
)

app = FastAPI(
    title="CRM API",
    version="1.0.0",
    docs_url="/docs" if settings.ENV != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────
app.include_router(auth.router,            prefix="/auth",       tags=["Auth"])
app.include_router(clients.router,         prefix="/clients",    tags=["Clients"])
app.include_router(billing.router,         prefix="/billing",    tags=["Billing"])
app.include_router(inventory.router,       prefix="/inventory",  tags=["Inventory"])
app.include_router(payments.router,        prefix="/payments",   tags=["Payments"])
app.include_router(expenses.router,        prefix="/expenses",   tags=["Expenses"])
app.include_router(allowances.router,      prefix="/allowances", tags=["Allowances"])
app.include_router(cashflow.router,        prefix="/cashflow",   tags=["CashFlow"])
app.include_router(dashboard.router,       prefix="/dashboard",  tags=["Dashboard"])
app.include_router(sync.router,            prefix="/sync",       tags=["Sync"])
app.include_router(settings_router.router, prefix="/settings",   tags=["Settings"])


@app.get("/health")
def health():
    return {"status": "ok"}
