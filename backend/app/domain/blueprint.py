from pydantic import BaseModel, Field


class ImportTarget(BaseModel):
    sheet_name: str
    destination: str
    preserve_history: bool = True


class ModuleDefinition(BaseModel):
    key: str
    title: str
    status: str = "planned"
    summary: str


IMPORT_TARGETS = [
    ImportTarget(sheet_name="Services/Billing", destination="operational_billing_rows"),
    ImportTarget(sheet_name="Stock/Inventory", destination="operational_stock_rows"),
    ImportTarget(
        sheet_name="Cash Flow",
        destination="manual_expenses + related summary tables",
    ),
    ImportTarget(sheet_name="Contacts", destination="clients"),
]

MODULES = [
    ModuleDefinition(key="authentication", title="Authentication", summary="Protect workspace access and roles."),
    ModuleDefinition(key="inventory", title="Inventory Management", summary="Track stock rows and availability from Supabase."),
    ModuleDefinition(key="services", title="Service Management", summary="Manage service billing rows and operational history."),
    ModuleDefinition(key="debtors", title="Debtors and Apply Payment", summary="Apply payments against debtor balances with low-latency writes."),
    ModuleDefinition(key="clients", title="Clients / Contacts", summary="Manage clients imported from Sheets and edited in-app."),
    ModuleDefinition(key="import-contacts", title="Import Contacts from Sheet", summary="Bring Contacts sheet rows into the clients table."),
    ModuleDefinition(key="cash-flow", title="Cash Flow and Profit Calculation", summary="Read profit and cash flow from precomputed summary tables."),
    ModuleDefinition(key="manual-expenses", title="Manual Expenses", summary="Maintain direct expense entries in Supabase."),
    ModuleDefinition(key="allowance-tracking", title="Allowance Tracking", summary="Track allowances as first-class operational records."),
    ModuleDefinition(key="dashboard", title="Dashboard", summary="Present operational KPIs and system status."),
    ModuleDefinition(key="refresh-workspace", title="Refresh Workspace", summary="Reload workspace state directly from Supabase."),
    ModuleDefinition(key="sync-google-sheets", title="Sync to Google Sheets", summary="Export data to Sheets only after a manual user action."),
    ModuleDefinition(key="settings-status", title="Settings / System Status", summary="Show environment status and source-of-truth guarantees."),
]
