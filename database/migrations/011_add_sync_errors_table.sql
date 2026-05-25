-- ============================================================
-- Sync Errors Logging Table
-- ============================================================

CREATE TABLE IF NOT EXISTS sync_errors (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name    TEXT NOT NULL,
    legacy_source_id TEXT,
    operation     TEXT NOT NULL,  -- 'insert', 'update', 'metadata_update', 'unknown'
    error_message TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Index for quick lookups by table and date
CREATE INDEX IF NOT EXISTS idx_sync_errors_table_created ON sync_errors(table_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_errors_legacy_id ON sync_errors(legacy_source_id);
