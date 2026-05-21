import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import LoadingSpinner from '@/components/LoadingSpinner'
import { ClipboardList, Download, Search, X } from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────────────────
interface AuditRow {
  id: string
  action: string
  amount: number | null
  performed_by: string | null
  related_record_id: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

interface AuditPage {
  items: AuditRow[]
  page: number
  page_size: number
  total_count: number
  total_pages: number
}

// ── Action options ─────────────────────────────────────────────────────────────
const ACTION_OPTIONS = [
  { value: '', label: 'All actions' },
  { value: 'expense_created', label: 'Expense created' },
  { value: 'expense_reversed', label: 'Expense reversed' },
  { value: 'allowance_withdrawn', label: 'Allowance withdrawn' },
]

// ── Helpers ────────────────────────────────────────────────────────────────────
function fmt(dt: string) {
  return new Intl.DateTimeFormat('en-GB', {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date(dt))
}

function ActionBadge({ action }: { action: string }) {
  const colours: Record<string, string> = {
    expense_created:    'bg-blue-100 text-blue-800',
    expense_reversed:   'bg-orange-100 text-orange-800',
    allowance_withdrawn:'bg-purple-100 text-purple-800',
  }
  const cls = colours[action] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {action.replace(/_/g, ' ')}
    </span>
  )
}

// ── CSV export ─────────────────────────────────────────────────────────────────
function buildExportUrl(params: Record<string, string>) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== ''))
  ).toString()
  return `${import.meta.env.VITE_API_URL ?? ''}/cashflow/audit/export-csv${qs ? '?' + qs : ''}`
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function CashFlowAudit() {
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [performedBy, setPerformedBy] = useState('')
  const [relatedId, setRelatedId] = useState('')
  const [relatedIdInput, setRelatedIdInput] = useState('')

  const params = {
    page: String(page),
    page_size: '50',
    ...(action ? { action } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(performedBy ? { performed_by: performedBy } : {}),
    ...(relatedId ? { related_record_id: relatedId } : {}),
  }

  const { data, isLoading, isError } = useQuery<AuditPage>({
    queryKey: ['cashflow-audit', params],
    queryFn: () => api.get('/cashflow/audit', { params }).then((r) => r.data),
    staleTime: 30_000,
  })

  function resetFilters() {
    setAction(''); setDateFrom(''); setDateTo('')
    setPerformedBy(''); setRelatedId(''); setRelatedIdInput(''); setPage(1)
  }

  return (
    <div className="space-y-5 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <ClipboardList size={22} className="text-indigo-600" />
          <h1 className="text-xl font-bold text-gray-900">Cash Flow Audit Log</h1>
          {data && (
            <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {data.total_count.toLocaleString()} rows
            </span>
          )}
        </div>
        <a
          href={buildExportUrl({ action, date_from: dateFrom, date_to: dateTo, performed_by: performedBy })}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          download
        >
          <Download size={14} /> Export CSV
        </a>
      </div>

      {/* Filters */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          {/* Action */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">Action</label>
            <select
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              value={action}
              onChange={(e) => { setAction(e.target.value); setPage(1) }}
            >
              {ACTION_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          {/* From date */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">From date</label>
            <input
              type="date"
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setPage(1) }}
            />
          </div>
          {/* To date */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">To date</label>
            <input
              type="date"
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setPage(1) }}
            />
          </div>
          {/* Performed by */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">Performed by (user ID)</label>
            <input
              type="text"
              placeholder="User ID…"
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              value={performedBy}
              onChange={(e) => { setPerformedBy(e.target.value); setPage(1) }}
            />
          </div>
          {/* Record ID search */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">Record ID</label>
            <div className="relative flex items-center">
              <input
                type="text"
                placeholder="Search record ID…"
                className="w-full rounded-md border border-gray-300 px-2 py-1.5 pr-14 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                value={relatedIdInput}
                onChange={(e) => setRelatedIdInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { setRelatedId(relatedIdInput); setPage(1) } }}
              />
              <button
                onClick={() => { setRelatedId(relatedIdInput); setPage(1) }}
                className="absolute right-7 text-gray-500 hover:text-gray-800"
                title="Search"
              >
                <Search size={14} />
              </button>
              {relatedId && (
                <button
                  onClick={() => { setRelatedId(''); setRelatedIdInput(''); setPage(1) }}
                  className="absolute right-1 text-gray-400 hover:text-gray-700"
                  title="Clear"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          </div>
        </div>
        {/* Active filter chips */}
        {(action || dateFrom || dateTo || performedBy || relatedId) && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-500">Active filters:</span>
            {action && <span className="rounded bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">{action}</span>}
            {dateFrom && <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">from {dateFrom}</span>}
            {dateTo && <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">to {dateTo}</span>}
            {performedBy && <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">by {performedBy.slice(0, 8)}…</span>}
            {relatedId && <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">id {relatedId.slice(0, 12)}…</span>}
            <button onClick={resetFilters} className="text-xs text-red-500 hover:text-red-700 underline">
              Clear all
            </button>
          </div>
        )}
      </div>

      {/* Table */}
      {isLoading && <LoadingSpinner />}
      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load audit log. Please try again.
        </div>
      )}
      {data && !isLoading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-100 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Action', 'Amount', 'Performed by', 'Record ID', 'Detail', 'Timestamp'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.items.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-sm text-gray-400">
                    No audit entries match your filters.
                  </td>
                </tr>
              )}
              {data.items.map((row) => (
                <tr key={row.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-2.5"><ActionBadge action={row.action} /></td>
                  <td className="px-4 py-2.5 font-mono text-gray-800">
                    {row.amount != null ? formatCurrency(row.amount, 'NGN') : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 max-w-[120px] truncate" title={row.performed_by ?? ''}>
                    {row.performed_by ? row.performed_by.slice(0, 12) + '…' : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-gray-500 font-mono text-xs max-w-[120px] truncate" title={row.related_record_id ?? ''}>
                    {row.related_record_id ? row.related_record_id.slice(0, 10) + '…' : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-gray-500 max-w-[180px]">
                    {row.detail ? (
                      <span className="block truncate text-xs font-mono" title={JSON.stringify(row.detail)}>
                        {JSON.stringify(row.detail)}
                      </span>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-gray-500 text-xs">
                    {fmt(row.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-600">
          <span>
            Page {data.page} of {data.total_pages} &nbsp;·&nbsp; {data.total_count.toLocaleString()} total rows
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-md border border-gray-300 px-3 py-1 hover:bg-gray-50 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(data.total_pages, p + 1))}
              disabled={page >= data.total_pages}
              className="rounded-md border border-gray-300 px-3 py-1 hover:bg-gray-50 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
