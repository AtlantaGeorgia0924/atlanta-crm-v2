-- Migration: Expand cashflow_summary numeric precision to support large totals
-- Reason: numeric(12,2) max value is 99,999,999.99 - too small for large businesses
-- New: numeric(18,2) max value is 999,999,999,999,999.99
-- Applied: Via Supabase SQL Editor or direct psql command

ALTER TABLE cashflow_summary
ALTER COLUMN total_billed TYPE numeric(18,2),
ALTER COLUMN total_collected TYPE numeric(18,2),
ALTER COLUMN total_outstanding TYPE numeric(18,2),
ALTER COLUMN total_expenses TYPE numeric(18,2),
ALTER COLUMN total_allowances TYPE numeric(18,2),
ALTER COLUMN net_profit TYPE numeric(18,2),
ALTER COLUMN profit_seen TYPE numeric(18,2),
ALTER COLUMN expenses_total TYPE numeric(18,2),
ALTER COLUMN allowance_amount TYPE numeric(18,2),
ALTER COLUMN profit_left TYPE numeric(18,2);

-- Verify changes
SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_name = 'cashflow_summary' AND table_schema = 'public'
ORDER BY column_name;
