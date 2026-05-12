from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_system_status_enforces_supabase_as_source_of_truth() -> None:
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()

    assert payload["source_of_truth"] == "Supabase"
    assert payload["google_sheets_mode"] == "manual-sync-only"
    assert len(payload["modules"]) == 13


def test_workspace_refresh_reads_from_supabase_only() -> None:
    response = client.post("/api/v1/workspace/refresh")

    assert response.status_code == 200
    assert response.json() == {
        "source": "supabase",
        "uses_google_sheets": False,
        "cache_strategy": "reload-directly-from-supabase",
    }


def test_import_mapping_preserves_history_for_all_targets() -> None:
    response = client.post("/api/v1/imports/google-sheets")

    assert response.status_code == 200
    payload = response.json()

    assert payload["mode"] == "initial-import"
    assert payload["preserve_history"] is True
    assert [
        (target["sheet_name"], target["destination"])
        for target in payload["targets"]
    ] == [
        ("Services/Billing", "operational_billing_rows"),
        ("Stock/Inventory", "operational_stock_rows"),
        ("Cash Flow", "manual_expenses + related summary tables"),
        ("Contacts", "clients"),
    ]


def test_apply_payment_contract_keeps_supabase_latency_target() -> None:
    response = client.post("/api/v1/debtors/apply-payment")

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "source": "supabase",
        "target_latency_ms": 1000,
    }
