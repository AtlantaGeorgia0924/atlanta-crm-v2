import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'

interface Summary {
  clients: number
  total_invoices: number
  total_unpaid: number
  amount_owed: number
  monthly_sales: number
  available_products: number
  pending_products: number
  low_quality_stock: number
  net_profit: number
}

interface DebtorRow {
  client_name: string
  total_outstanding: number
  unpaid_jobs: number
}

interface DashboardActivityRow {
  id: string
  time?: string
  time_epoch?: number
  user: string
  action: string
  reference: string
}

interface CashflowPageData {
  statement?: {
    total_sales: number
    total_collected: number
    amount_owed: number
    net_profit: number
  }
}

interface BillingRow {
  service_name?: string
  amount_charged?: number
}

interface BillingGroupedResponse {
  groups: Array<{ items: BillingRow[] }>
}

function KpiCard({ title, value }: { title: string; value: string | number }) {
  return (
    <div className="rounded-xl border bg-white p-4" style={{ borderColor: '#D4AF37' }}>
      <p className="text-xs uppercase tracking-wide text-gray-500">{title}</p>
      <p className="mt-2 text-2xl font-bold text-black">{value}</p>
    </div>
  )
}

function MiniBarChart({ title, rows }: { title: string; rows: Array<{ label: string; value: number }> }) {
  const max = Math.max(1, ...rows.map((r) => r.value || 0))
  return (
    <div className="rounded-xl border bg-white p-4" style={{ borderColor: '#D4AF37' }}>
      <h3 className="text-sm font-semibold text-black">{title}</h3>
      <div className="mt-3 space-y-2">
        {rows.length === 0 ? (
          <p className="text-xs text-gray-500">No data</p>
        ) : (
          rows.map((row) => (
            <div key={row.label} className="space-y-1">
              <div className="flex items-center justify-between text-xs text-gray-600">
                <span>{row.label}</span>
                <span className="font-semibold text-black">{row.value}</span>
              </div>
              <div className="h-2 rounded bg-gray-100">
                <div
                  className="h-2 rounded"
                  style={{ width: `${Math.max(6, (row.value / max) * 100)}%`, backgroundColor: '#D4AF37' }}
                />
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function formatRelative(ts?: string): string {
  if (!ts) return '-'
  const now = Date.now()
  const then = new Date(ts).getTime()
  if (!Number.isFinite(then)) return '-'
  const diffMins = Math.max(0, Math.floor((now - then) / 60000))
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins} mins ago`
  const hours = Math.floor(diffMins / 60)
  if (hours < 24) return `${hours} hrs ago`
  const days = Math.floor(hours / 24)
  return `${days} days ago`
}

function dayKey(ts?: string): string {
  if (!ts) return 'N/A'
  return String(ts).slice(5, 10)
}

export default function Dashboard() {
  const user = useAuthStore((s) => s.user)
  const isStaff = user?.role === 'staff'

  const { data: summary, isLoading } = useQuery<Summary>({
    queryKey: ['dashboard'],
    queryFn: () => api.get('/dashboard').then((r) => r.data),
  })

  const { data: cashflowData } = useQuery<CashflowPageData>({
    queryKey: ['cashflow-page-data', 1, 1, 5],
    queryFn: () => api.get('/cashflow/page-data', { params: { expense_page: 1, withdrawals_page: 1, page_size: 5 } }).then((r) => r.data),
  })

  const { data: debtorsData } = useQuery<DebtorRow[]>({
    queryKey: ['debtors', 'dashboard'],
    queryFn: () => api.get('/billing/debtors').then((r) => r.data),
  })

  const { data: lowStockData } = useQuery<{ items: any[]; data?: any[] }>({
    queryKey: ['inventory', 'dashboard-low-stock'],
    queryFn: () => api.get('/inventory', { params: { view: 'products', low_stock: true, page: 1, page_size: 10 } }).then((r) => r.data),
  })

  const today = new Date().toISOString().slice(0, 10)
  const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10)

  const { data: billingTrendData } = useQuery<BillingGroupedResponse>({
    queryKey: ['billing-grouped', 'dashboard-trends', monthStart, today],
    queryFn: () => api.get('/billing/grouped', { params: { page: 1, page_size: 300, from_date: monthStart, to_date: today } }).then((r) => r.data),
  })

  const { data: activityData } = useQuery<{ items: DashboardActivityRow[] }>({
    queryKey: ['dashboard-activity'],
    queryFn: () => api.get('/dashboard/activity', { params: { limit: 30 } }).then((r) => r.data),
    refetchInterval: 15000,
  })

  const safeSummary: Summary =
    summary ??
    {
      clients: 0,
      total_invoices: 0,
      total_unpaid: 0,
      amount_owed: 0,
      monthly_sales: 0,
      available_products: 0,
      pending_products: 0,
      low_quality_stock: 0,
      net_profit: 0,
    }

  const statement = cashflowData?.statement
  const totalSales = Number(statement?.total_sales ?? safeSummary.monthly_sales ?? 0)
  const totalCollected = Number(statement?.total_collected ?? 0)
  const outstanding = Number(statement?.amount_owed ?? safeSummary.amount_owed ?? 0)
  const netProfit = Number(statement?.net_profit ?? safeSummary.net_profit ?? 0)

  const debtorRows = debtorsData ?? []
  const topDebtors = [...debtorRows]
    .sort((a, b) => Number(b.total_outstanding || 0) - Number(a.total_outstanding || 0))
    .slice(0, 5)

  const lowStockItems = (lowStockData?.items ?? lowStockData?.data ?? []).slice(0, 8)

  const activity = useMemo<DashboardActivityRow[]>(() => activityData?.items ?? [], [activityData])

  const salesTrend = useMemo(() => {
    const buckets: Record<string, number> = {}
    for (const row of activity) {
      if (!String(row.action || '').toLowerCase().includes('sale')) continue
      const key = dayKey(row.time)
      buckets[key] = (buckets[key] || 0) + 1
    }
    return Object.entries(buckets).map(([label, value]) => ({ label, value })).slice(-7)
  }, [activity])

  const collectionTrend = useMemo(() => {
    const buckets: Record<string, number> = {}
    for (const row of activity) {
      const action = String(row.action || '').toLowerCase()
      if (!action.includes('payment')) continue
      const key = dayKey(row.time)
      buckets[key] = (buckets[key] || 0) + 1
    }
    return Object.entries(buckets).map(([label, value]) => ({ label, value })).slice(-7)
  }, [activity])

  const inventoryMovement = useMemo(() => {
    const buckets: Record<string, number> = {}
    for (const row of activity) {
      const action = String(row.action || '').toLowerCase()
      if (!action.includes('inventory')) continue
      const key = dayKey(row.time)
      buckets[key] = (buckets[key] || 0) + 1
    }
    return Object.entries(buckets).map(([label, value]) => ({ label, value })).slice(-7)
  }, [activity])

  const topSellingDevices = useMemo(() => {
    const tally: Record<string, number> = {}
    const groups = billingTrendData?.groups ?? []
    for (const group of groups) {
      for (const row of group.items || []) {
        const name = String(row.service_name || '').trim() || 'Unknown'
        tally[name] = (tally[name] || 0) + Number(row.amount_charged || 0)
      }
    }
    return Object.entries(tally)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([label, value]) => ({ label: label.length > 18 ? `${label.slice(0, 18)}...` : label, value: Math.round(value) }))
  }, [billingTrendData])

  if (isLoading || !summary) return <LoadingSpinner />

  const maskedOrValue = (value: string | number, financial: boolean) => (isStaff && financial ? '*****' : value)

  return (
    <div className="p-6 space-y-6" style={{ background: '#f7f7f5' }}>
      <div className="rounded-2xl border p-5" style={{ background: '#0f0f0f', borderColor: '#D4AF37' }}>
        <h1 className="text-2xl font-bold text-white">Executive Dashboard</h1>
        <p className="text-sm text-[#D4AF37]">AtlantaGeorgia_TECH Operational Intelligence</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        <KpiCard title="Total Sales" value={maskedOrValue(formatCurrency(totalSales, 'NGN'), true)} />
        <KpiCard title="Total Collected" value={maskedOrValue(formatCurrency(totalCollected, 'NGN'), true)} />
        <KpiCard title="Outstanding Balance" value={maskedOrValue(formatCurrency(outstanding, 'NGN'), true)} />
        <KpiCard title="Inventory Value" value={maskedOrValue(formatCurrency(Number(safeSummary.available_products || 0) * 1, 'NGN'), true)} />
        <KpiCard title="Net Profit" value={maskedOrValue(formatCurrency(netProfit, 'NGN'), true)} />
        <KpiCard title="Debtors Count" value={debtorRows.length} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <MiniBarChart title="Sales Trend" rows={salesTrend} />
        <MiniBarChart title="Collections Trend" rows={collectionTrend} />
        <MiniBarChart title="Inventory Movement" rows={inventoryMovement} />
        <MiniBarChart title="Top Selling Devices" rows={topSellingDevices} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="rounded-xl border bg-white p-4 xl:col-span-2" style={{ borderColor: '#D4AF37' }}>
          <h3 className="text-sm font-semibold text-black">Recent Activity</h3>
          <div className="mt-3 space-y-2 max-h-72 overflow-y-auto">
            {activity.length === 0 ? (
              <p className="text-xs text-gray-500">No recent activity</p>
            ) : (
              activity.map((row) => (
                <div key={row.id} className="rounded border px-3 py-2" style={{ borderColor: '#f1e7bf' }}>
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-black">{row.user}</p>
                    <p className="text-xs text-gray-500">{formatRelative(row.time)}</p>
                  </div>
                  <p className="text-xs text-gray-700">{row.action}</p>
                  <p className="text-[11px] text-gray-500">Ref: {row.reference}</p>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border bg-white p-4" style={{ borderColor: '#D4AF37' }}>
            <h3 className="text-sm font-semibold text-black">Top Debtors</h3>
            <div className="mt-3 space-y-2">
              {topDebtors.length === 0 ? (
                <p className="text-xs text-gray-500">No debtors</p>
              ) : (
                topDebtors.map((d) => (
                  <div key={d.client_name} className="flex items-center justify-between text-xs">
                    <span className="text-gray-700 truncate max-w-[60%]">{d.client_name}</span>
                    <span className="font-semibold text-amber-700">{formatCurrency(Number(d.total_outstanding || 0), 'NGN')}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="rounded-xl border bg-white p-4" style={{ borderColor: '#D4AF37' }}>
            <h3 className="text-sm font-semibold text-black">Low Stock Alerts</h3>
            <div className="mt-3 space-y-2">
              {lowStockItems.length === 0 ? (
                <p className="text-xs text-gray-500">No low stock alerts</p>
              ) : (
                lowStockItems.map((item: any) => (
                  <div key={String(item.id)} className="text-xs">
                    <p className="font-medium text-gray-800 truncate">{item.item_name || '-'}</p>
                    <p className="text-gray-500">Qty: {item.quantity} | Reorder: {item.reorder_level}</p>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="rounded-xl border bg-white p-4" style={{ borderColor: '#D4AF37' }}>
            <h3 className="text-sm font-semibold text-black">Pending Payments</h3>
            <p className="mt-2 text-lg font-bold text-red-600">{safeSummary.total_unpaid}</p>
            <p className="text-xs text-gray-500">Services currently unpaid</p>
          </div>
        </div>
      </div>
    </div>
  )
}
