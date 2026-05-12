export function formatCurrency(value: number | string, currency = 'GHS'): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  return new Intl.NumberFormat('en-GH', {
    style: 'currency',
    currency,
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
