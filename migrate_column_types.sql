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
