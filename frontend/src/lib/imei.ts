export function resolveImei(row: Record<string, any> | null | undefined): string {
  if (!row) return ''
  const value =
    row.imei
    || row.device_imei
    || row.imei_number
    || row.source_imei
    || row.imei1
    || row.imei_2
    || ''
  return String(value || '').trim()
}

export function formatImeiLabel(row: Record<string, any> | null | undefined): string {
  const imei = resolveImei(row)
  return imei ? `IMEI: ${imei}` : 'IMEI: —'
}
