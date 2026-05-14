export function formatCurrency(value: number | string, currency = 'NGN'): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  const localeByCurrency: Record<string, string> = {
    NGN: 'en-NG',
    GHS: 'en-GH',
    USD: 'en-US',
    EUR: 'en-IE',
    GBP: 'en-GB',
  }
  const normalized = (currency || 'NGN').toUpperCase()
  return new Intl.NumberFormat(localeByCurrency[normalized] || 'en-NG', {
    style: 'currency',
    currency: normalized,
    minimumFractionDigits: 2,
  }).format(isNaN(num) ? 0 : num)
}

export function formatDate(dateStr?: string | null): string {
  if (!dateStr) return 'N/A'
  return new Date(dateStr).toLocaleDateString('en-GB')
}

export function normalizeStatus(status: string): 'paid' | 'partial' | 'unpaid' {
  const normalized = String(status || '').trim().toUpperCase()
  if (normalized === 'PAID') return 'paid'
  if (normalized === 'PARTIAL' || normalized === 'PART PAYMENT') return 'partial'
  return 'unpaid'
}

export function statusLabel(status: string): 'PAID' | 'PART PAYMENT' | 'UNPAID' {
  const normalized = normalizeStatus(status)
  if (normalized === 'paid') return 'PAID'
  if (normalized === 'partial') return 'PART PAYMENT'
  return 'UNPAID'
}

export function statusBadgeClass(status: string): string {
  switch (normalizeStatus(status)) {
    case 'paid':
      return 'badge-paid'
    case 'partial':
      return 'badge-partial'
    default:
      return 'badge-unpaid'
  }
}
