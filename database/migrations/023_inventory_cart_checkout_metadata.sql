-- Inventory cart checkout metadata for POS-style sell-out flow.

ALTER TABLE inventory_sales
    ADD COLUMN IF NOT EXISTS payment_method TEXT,
    ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(14,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS invoice_reference TEXT;

CREATE INDEX IF NOT EXISTS idx_inventory_sales_invoice_reference
ON inventory_sales(invoice_reference);

CREATE INDEX IF NOT EXISTS idx_inventory_sales_payment_method
ON inventory_sales(payment_method);
