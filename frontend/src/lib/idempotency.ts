export function buildIdempotencyKey(scope: string): string {
  const prefix = String(scope || 'txn').trim().replace(/[^a-zA-Z0-9_-]/g, '').toLowerCase() || 'txn'
  const randomPart = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${randomPart}`
}
