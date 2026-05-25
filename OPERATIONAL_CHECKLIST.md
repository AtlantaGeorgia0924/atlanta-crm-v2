# CRM Operational Verification Checklist

Run before every production deployment:

```bash
npm run verify-system
```

Manual workflow checks that need seeded test data:

- Auth login: use `TEST_LOGIN_EMAIL` and `TEST_LOGIN_PASSWORD` against a non-production test account.
- RBAC enforcement: verify staff cannot open `/debtors`, `/cashflow`, `/settings`, or `/users`.
- Invoice editing: edit a disposable billing row and confirm the audit/activity entry.
- Payment application: apply a disposable debtor payment and confirm balances update.
- WhatsApp billing: send or generate a billing WhatsApp action for a test client phone number.
- Google Sheets sync: run Refresh from Google Sheets and Sync to Google Sheets with service-account access.
- Realtime updates: keep Cash Flow open in one browser, update a watched table, and confirm cache refresh.
- Redis connectivity: verify `REDIS_URL` points to production Redis and the verification script passes.
- Migration status: confirm all files in `database/migrations` have been applied in numeric order.
