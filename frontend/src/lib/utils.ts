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
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-GB')
}

export function statusBadgeClass(status: string): string {
  switch (status) {
    case 'paid':    return 'badge-paid'
    case 'partial': return 'badge-partial'
    default:        return 'badge-unpaid'
  }
}
