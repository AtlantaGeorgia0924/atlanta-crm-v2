# Database Migration: Expand Numeric Precision for Cashflow Summary

## Issue
The `cashflow_summary` table monetary columns are defined as `numeric(12,2)` which has a maximum value of **₦99,999,999.99**. When totals exceed this limit, Supabase returns error code 22003 (numeric field overflow).

## Solution
Expand all monetary columns from `numeric(12,2)` to `numeric(18,2)` to support values up to **₦999,999,999,999,999.99**.

## Columns to Alter
- weekly_paid_profits
- weekly_expenses
- weekly_net_profit
- next_week_allowance
- monthly_net_profit
- allowances_withdrawn
- monthly_net_profit_left

## SQL Command
See: `/database/migrations/006_expand_cashflow_numeric_precision.sql`

## How to Apply

### Option 1: Via Supabase Dashboard (Recommended)
1. Navigate to https://app.supabase.com/project/rwyplndwzrqdsyhsyjue/sql
2. Click "New Query"
3. Copy and paste the SQL from `006_expand_cashflow_numeric_precision.sql`
4. Click "Execute" or press Cmd+Enter
5. Verify all columns show `numeric(18,2)` in the results

### Option 2: Via psql command-line
```bash
cd /Users/mac/crm-app
PGPASSWORD="$(grep 'SUPABASE_SERVICE_ROLE_KEY=' backend/.env | cut -d= -f2)" \
psql -h rwyplndwzrqdsyhsyjue.supabase.co -U postgres -d postgres \
  -f database/migrations/006_expand_cashflow_numeric_precision.sql
```

## After Migration
1. Re-run "Refresh Workspace" in the CRM dashboard
2. Verify dashboard displays correct values (should no longer overflow)
3. Test with large totals exceeding ₦100,000,000

## Validation Query
```sql
-- Check column definitions
SELECT column_name, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_name = 'cashflow_summary' 
  AND table_schema = 'public'
  AND column_name IN (
    'weekly_paid_profits', 'weekly_expenses', 'weekly_net_profit',
    'next_week_allowance', 'monthly_net_profit', 'allowances_withdrawn',
    'monthly_net_profit_left'
  )
ORDER BY column_name;

-- Expected result: all showing numeric(18,2)
```

## Migration Status
- [ ] Migration file created: `006_expand_cashflow_numeric_precision.sql`
- [ ] Applied to Supabase database
- [ ] Dashboard refresh tested
- [ ] Large totals working (> ₦100,000,000)
