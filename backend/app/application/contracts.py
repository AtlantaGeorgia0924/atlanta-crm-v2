from pydantic import BaseModel


class WorkspaceRefreshResult(BaseModel):
    source: str
    uses_google_sheets: bool
    cache_strategy: str


class SyncResult(BaseModel):
    mode: str
    trigger: str
    destination: str


class CashFlowSummary(BaseModel):
    source: str
    recalculation_mode: str


class PaymentResult(BaseModel):
    status: str
    source: str
    target_latency_ms: int
