import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  BarChart,
  Bar,
} from 'recharts'
import {
  Wrench,
  Package,
  ShoppingBag,
  CreditCard,
  ShieldAlert,
  Smartphone,
  Landmark,
  Wallet,
  Boxes,
  ArrowUpRight,
  Clock3,
  Activity,
  ShoppingCart,
  Undo2,
  Receipt,
  RefreshCcw,
  Hammer,
  PlusCircle,
  UserCircle2,
  Store,
  Cable,
  type LucideIcon,
} from 'lucide-react'
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
  entity_type?: string
  reference: string
  detail?: Record<string, any>
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
  id?: string
  service_name?: string
  amount_charged?: number
  service_date?: string
  paid_amount?: number
  payment_status?: string
  client_name?: string
}

interface BillingGroupedResponse {
  groups: Array<{ service_date?: string; items: BillingRow[] }>
}

interface InventoryRow {
  id: string
  item_name?: string
  category?: string
  quantity?: number
  unit_price?: number
  supplier?: string
  created_at?: string
  reorder_level?: number
}

interface PaymentsRow {
  id: string
  client_name?: string
  service_job_id?: string
  amount?: number
  payment_amount?: number
  payment_method?: string
  payment_date?: string
  created_at?: string
}

interface KpiCardProps {
  title: string
  value: string | number
  hint?: string
  icon: LucideIcon
  tone?: 'neutral' | 'gold' | 'green' | 'blue' | 'purple'
}

type InventoryBucket = 'iPhones' | 'Samsung' | 'Google Pixel' | 'Accessories'

const toneMap: Record<NonNullable<KpiCardProps['tone']>, string> = {
  neutral: 'bg-white border-[#E5E7EB] text-gray-900',
  gold: 'bg-[#fff8e7] border-[#D4AF37] text-[#7a5b00]',
  green: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  blue: 'bg-blue-50 border-blue-200 text-blue-800',
  purple: 'bg-violet-50 border-violet-200 text-violet-800',
}

function KpiCard({ title, value, hint, icon: Icon, tone = 'neutral' }: KpiCardProps) {
  return (
    <div className={`rounded-2xl border p-4 shadow-sm min-h-[118px] ${toneMap[tone]}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide opacity-80">{title}</p>
        <div className="rounded-lg bg-black/5 p-2">
          <Icon size={16} />
        </div>
      </div>
      <p className="mt-3 text-2xl font-bold leading-none">{value}</p>
      {hint ? <p className="mt-2 text-xs opacity-80">{hint}</p> : null}
    </div>
  )
}

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-[#D4AF37] bg-white p-4 shadow-sm h-full">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        {action}
      </div>
      {children}
    </div>
  )
}

function toDayString(value?: string): string {
  if (!value) return ''
  return String(value).slice(0, 10)
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
  return `${Math.floor(hours / 24)} days ago`
}

function shortDate(ts?: string): string {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
}

function activityIcon(action: string) {
  const value = action.toLowerCase()
  if (value.includes('inventory') && value.includes('add')) return PlusCircle
  if (value.includes('inventory') && value.includes('sale')) return ShoppingCart
  if (value.includes('payment') && value.includes('reverse')) return RefreshCcw
  if (value.includes('payment')) return Wallet
  if (value.includes('return')) return Undo2
  if (value.includes('expense')) return Receipt
  if (value.includes('service') || value.includes('invoice')) return Wrench
  return Activity
}

function normalizeModel(item: InventoryRow): InventoryBucket {
  const name = String(item.item_name || '').toLowerCase()
  const category = String(item.category || '').toLowerCase()
  if (name.includes('iphone')) return 'iPhones'
  if (name.includes('samsung')) return 'Samsung'
  if (name.includes('pixel') || name.includes('google')) return 'Google Pixel'
  if (category.includes('accessor') || name.includes('airpod') || name.includes('charger') || name.includes('cable')) return 'Accessories'
  return 'Accessories'
}

export default function Dashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isStaff = user?.role === 'staff'
  const [now, setNow] = useState<Date>(new Date())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const { data: summary, isLoading } = useQuery<Summary>({
    queryKey: ['dashboard'],
    queryFn: () => api.get('/dashboard').then((r) => r.data),
  })

  const { data: cashflowData } = useQuery<CashflowPageData>({
    queryKey: ['cashflow-page-data', 1, 1, 7],
    queryFn: () => api.get('/cashflow/page-data', { params: { expense_page: 1, withdrawals_page: 1, page_size: 7 } }).then((r) => r.data),
  })

  const { data: debtorsData } = useQuery<DebtorRow[]>({
    queryKey: ['debtors', 'dashboard-v2'],
    queryFn: () => api.get('/billing/debtors').then((r) => r.data),
  })

  const { data: lowStockData } = useQuery<{ items: InventoryRow[]; data?: InventoryRow[] }>({
    queryKey: ['inventory', 'dashboard-low-stock-v2'],
    queryFn: () => api.get('/inventory', { params: { view: 'products', low_stock: true, page: 1, page_size: 12 } }).then((r) => r.data),
  })

  const { data: inventoryData } = useQuery<{ items: InventoryRow[]; data?: InventoryRow[] }>({
    queryKey: ['inventory', 'dashboard-inventory-v2'],
    queryFn: () => api.get('/inventory', { params: { view: 'products', page: 1, page_size: 200 } }).then((r) => r.data),
  })

  const today = useMemo(() => new Date().toISOString().slice(0, 10), [])
  const monthStart = useMemo(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10), [])

  const { data: billingTrendData } = useQuery<BillingGroupedResponse>({
    queryKey: ['billing-grouped', 'dashboard-v2-trends', monthStart, today],
    queryFn: () => api.get('/billing/grouped', { params: { page: 1, page_size: 400, from_date: monthStart, to_date: today } }).then((r) => r.data),
  })

  const { data: activityData } = useQuery<{ items: DashboardActivityRow[] }>({
    queryKey: ['dashboard-activity-v2'],
    queryFn: () => api.get('/dashboard/activity', { params: { limit: 60 } }).then((r) => r.data),
    refetchInterval: 15000,
  })

  const { data: paymentsData } = useQuery<{ items: PaymentsRow[] }>({
    queryKey: ['payments', 'dashboard-v2'],
    queryFn: () => api.get('/payments', { params: { page: 1, page_size: 20 } }).then((r) => r.data),
    retry: false,
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

  const inventoryRows = useMemo<InventoryRow[]>(() => inventoryData?.items ?? inventoryData?.data ?? [], [inventoryData])
  const lowStockItems = useMemo<InventoryRow[]>(() => (lowStockData?.items ?? lowStockData?.data ?? []).slice(0, 8), [lowStockData])
  const debtors = useMemo<DebtorRow[]>(() => debtorsData ?? [], [debtorsData])

  const inventoryCount = inventoryRows.length
  const inventoryUnits = inventoryRows.reduce((sum, row) => sum + Number(row.quantity || 0), 0)
  const inventoryValue = inventoryRows.reduce((sum, row) => sum + Number(row.quantity || 0) * Number(row.unit_price || 0), 0)

  const activity = useMemo<DashboardActivityRow[]>(() => activityData?.items ?? [], [activityData])

  const salesByDay = useMemo(() => {
    const bucket: Record<string, number> = {}
    for (const group of billingTrendData?.groups ?? []) {
      const day = toDayString(group.service_date)
      if (!day) continue
      let dayTotal = 0
      for (const row of group.items || []) {
        dayTotal += Number(row.amount_charged || 0)
      }
      bucket[day] = (bucket[day] || 0) + dayTotal
    }
    return bucket
  }, [billingTrendData])

  const dayKeys = useMemo(() => Object.keys(salesByDay).sort(), [salesByDay])
  const todaySales = Number(salesByDay[today] || 0)
  const weekSales = dayKeys
    .slice(-7)
    .reduce((sum, day) => sum + Number(salesByDay[day] || 0), 0)
  const monthSales = dayKeys.reduce((sum, day) => sum + Number(salesByDay[day] || 0), 0)

  const salesSummaryChart = useMemo(
    () => [
      { label: 'Today', value: todaySales },
      { label: 'Week', value: weekSales },
      { label: 'Month', value: monthSales },
    ],
    [todaySales, weekSales, monthSales],
  )

  const collectionsByDay = useMemo(() => {
    const bucket: Record<string, number> = {}
    for (const row of activity) {
      if (!String(row.action || '').toLowerCase().includes('payment')) continue
      const day = toDayString(row.time)
      if (!day) continue
      const amount = Number(row.detail?.amount || row.detail?.payment_amount || 0)
      bucket[day] = (bucket[day] || 0) + amount
    }
    const keys = Object.keys(bucket).sort().slice(-7)
    return keys.map((key) => ({ label: key.slice(5), value: Number(bucket[key] || 0) }))
  }, [activity])

  const devicesSoldToday = useMemo(() => {
    let count = 0
    for (const row of activity) {
      const action = String(row.action || '').toLowerCase()
      if (!action.includes('sale')) continue
      if (toDayString(row.time) !== today) continue
      count += Number(row.detail?.quantity || 1)
    }
    return count
  }, [activity, today])

  const repairsToday = useMemo(() => {
    let count = 0
    for (const group of billingTrendData?.groups ?? []) {
      if (toDayString(group.service_date) !== today) continue
      count += (group.items || []).length
    }
    return count
  }, [billingTrendData, today])

  const activeDebtors = debtors.length

  const inventoryOverview = useMemo(() => {
    const counts: Record<InventoryBucket, number> = { iPhones: 0, Samsung: 0, 'Google Pixel': 0, Accessories: 0 }
    for (const item of inventoryRows) {
      const bucket = normalizeModel(item)
      counts[bucket] += Number(item.quantity || 0)
    }
    return counts
  }, [inventoryRows])

  const topSellingDevices = useMemo(() => {
    const tally: Record<string, { qty: number; revenue: number }> = {}
    for (const group of billingTrendData?.groups ?? []) {
      for (const row of group.items || []) {
        const name = String(row.service_name || '').trim() || 'Unknown Device'
        const qty = 1
        const revenue = Number(row.amount_charged || 0)
        if (!tally[name]) tally[name] = { qty: 0, revenue: 0 }
        tally[name].qty += qty
        tally[name].revenue += revenue
      }
    }
    return Object.entries(tally)
      .sort((a, b) => b[1].qty - a[1].qty)
      .slice(0, 5)
      .map(([name, values]) => ({ name, ...values }))
  }, [billingTrendData])

  const recentPayments = useMemo(() => {
    const apiRows = paymentsData?.items ?? []
    if (apiRows.length > 0) {
      return apiRows.slice(0, 6).map((row) => ({
        id: row.id,
        client: row.client_name || row.service_job_id || '-',
        amount: Number(row.payment_amount ?? row.amount ?? 0),
        method: row.payment_method || '-',
        date: row.payment_date || row.created_at || '-',
      }))
    }
    return activity
      .filter((row) => String(row.action || '').toLowerCase().includes('payment'))
      .slice(0, 6)
      .map((row) => ({
        id: row.id,
        client: String(row.detail?.client_name || row.reference || '-'),
        amount: Number(row.detail?.amount || row.detail?.payment_amount || 0),
        method: String(row.detail?.payment_method || '-'),
        date: row.time || '-',
      }))
  }, [paymentsData, activity])

  const recentInventoryAdditions = useMemo(() => {
    const fromInventory = [...inventoryRows]
      .filter((row) => !!row.created_at)
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
      .slice(0, 6)
      .map((row) => ({
        id: row.id,
        item: row.item_name || '-',
        supplier: row.supplier || '-',
        quantity: Number(row.quantity || 0),
        date: row.created_at || '-',
      }))

    if (fromInventory.length > 0) return fromInventory

    return activity
      .filter((row) => {
        const action = String(row.action || '').toLowerCase()
        return action.includes('inventory') && (action.includes('add') || action.includes('created'))
      })
      .slice(0, 6)
      .map((row) => ({
        id: row.id,
        item: String(row.detail?.item_name || row.reference || '-'),
        supplier: String(row.detail?.supplier || '-'),
        quantity: Number(row.detail?.quantity || 0),
        date: row.time || '-',
      }))
  }, [inventoryRows, activity])

  const quickActions = [
    { label: 'New Service', icon: Wrench, onClick: () => navigate('/billing') },
    { label: 'Add Stock', icon: Package, onClick: () => navigate('/inventory') },
    { label: 'Sell Device', icon: ShoppingBag, onClick: () => navigate('/inventory') },
    { label: 'Apply Payment', icon: CreditCard, onClick: () => navigate('/debtors') },
  ]

  const row1Cards: KpiCardProps[] = isStaff
    ? [
        { title: 'Inventory Value', value: formatCurrency(inventoryValue, 'NGN'), icon: Boxes, tone: 'gold' },
        { title: 'Inventory Count', value: inventoryCount, icon: Package, tone: 'blue' },
        { title: 'Debtors Count', value: debtors.length, icon: ShieldAlert, tone: 'purple' },
        { title: 'Low Stock Count', value: lowStockItems.length, icon: ShieldAlert, tone: 'green' },
      ]
    : [
        { title: 'Total Sales', value: formatCurrency(totalSales, 'NGN'), icon: Landmark, tone: 'gold' },
        { title: 'Total Collected', value: formatCurrency(totalCollected, 'NGN'), icon: Wallet, tone: 'green' },
        { title: 'Outstanding Balance', value: formatCurrency(outstanding, 'NGN'), icon: ShieldAlert, tone: 'blue' },
        { title: 'Inventory Value', value: formatCurrency(inventoryValue, 'NGN'), icon: Boxes, tone: 'purple' },
      ]

  const row2Cards: KpiCardProps[] = [
    { title: 'Devices In Stock', value: inventoryUnits, icon: Smartphone, tone: 'gold' },
    { title: 'Devices Sold Today', value: devicesSoldToday, icon: ShoppingCart, tone: 'green' },
    { title: 'Repairs Today', value: repairsToday, icon: Hammer, tone: 'blue' },
    { title: 'Active Debtors', value: activeDebtors, icon: UserCircle2, tone: 'purple' },
  ]

  if (isLoading || !summary) return <LoadingSpinner />

  return (
    <div className="space-y-5 p-4 md:p-6" style={{ background: 'linear-gradient(180deg,#f5f5f5 0%,#f8f7f1 100%)' }}>
      <div className="rounded-2xl border border-[#D4AF37] bg-[#0c0c0c] p-4 text-white shadow-lg md:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-2xl font-bold">Welcome back, {user?.full_name || user?.email || 'Team'}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-[#f3d57a]">
              <span className="inline-flex items-center gap-1"><Clock3 size={14} /> {now.toLocaleDateString('en-GB', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })}</span>
              <span>{now.toLocaleTimeString('en-GB')}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {quickActions.map((action) => {
              const Icon = action.icon
              return (
                <button
                  key={action.label}
                  onClick={action.onClick}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-[#D4AF37] bg-[#181818] px-3 py-2 text-xs font-semibold text-white transition hover:bg-[#252525]"
                >
                  <Icon size={14} className="text-[#D4AF37]" /> {action.label}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {row1Cards.map((card) => (
          <KpiCard key={card.title} {...card} />
        ))}
      </div>

      {!isStaff ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            title="Net Profit"
            value={formatCurrency(netProfit, 'NGN')}
            icon={Wallet}
            tone="green"
          />
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {row2Cards.map((card) => (
          <KpiCard key={card.title} {...card} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <SectionCard title="Sales Chart" action={<span className="text-xs text-gray-500">Today • Week • Month</span>}>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={salesSummaryChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#ececec" />
                <XAxis dataKey="label" stroke="#6b7280" />
                <YAxis stroke="#6b7280" />
                <Tooltip formatter={(value: number) => formatCurrency(Number(value || 0), 'NGN')} />
                <Line type="monotone" dataKey="value" stroke="#D4AF37" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Collections Chart" action={<span className="text-xs text-gray-500">By Day</span>}>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={collectionsByDay}>
                <CartesianGrid strokeDasharray="3 3" stroke="#ececec" />
                <XAxis dataKey="label" stroke="#6b7280" />
                <YAxis stroke="#6b7280" />
                <Tooltip formatter={(value: number) => formatCurrency(Number(value || 0), 'NGN')} />
                <Bar dataKey="value" fill="#111827" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-4">
          <SectionCard title="Inventory Overview">
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-lg bg-gray-50 p-3"><span className="inline-flex items-center gap-2 text-sm"><Smartphone size={15} /> iPhones</span><strong>{inventoryOverview.iPhones}</strong></div>
              <div className="flex items-center justify-between rounded-lg bg-gray-50 p-3"><span className="inline-flex items-center gap-2 text-sm"><Store size={15} /> Samsung</span><strong>{inventoryOverview.Samsung}</strong></div>
              <div className="flex items-center justify-between rounded-lg bg-gray-50 p-3"><span className="inline-flex items-center gap-2 text-sm"><Smartphone size={15} /> Google Pixel</span><strong>{inventoryOverview['Google Pixel']}</strong></div>
              <div className="flex items-center justify-between rounded-lg bg-gray-50 p-3"><span className="inline-flex items-center gap-2 text-sm"><Cable size={15} /> Accessories</span><strong>{inventoryOverview.Accessories}</strong></div>
            </div>
          </SectionCard>
        </div>

        <div className="xl:col-span-4">
          <SectionCard
            title="Low Stock Alerts"
            action={
              <button onClick={() => navigate('/inventory')} className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 hover:underline">
                Open Inventory <ArrowUpRight size={12} />
              </button>
            }
          >
            <div className="space-y-2">
              {lowStockItems.length === 0 ? (
                <p className="text-xs text-gray-500">No low stock alerts</p>
              ) : (
                lowStockItems.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => navigate('/inventory')}
                    className="flex w-full items-center justify-between rounded-lg border border-amber-100 bg-amber-50 p-2 text-left"
                  >
                    <span className="text-sm text-gray-800">⚠ {item.item_name || 'Unknown Item'}</span>
                    <span className="text-xs font-semibold text-amber-700">{Number(item.quantity || 0)} left</span>
                  </button>
                ))
              )}
            </div>
          </SectionCard>
        </div>

        <div className="xl:col-span-4">
          <SectionCard title="Top Selling Devices">
            <div className="space-y-2">
              {topSellingDevices.length === 0 ? (
                <p className="text-xs text-gray-500">No sales yet</p>
              ) : (
                topSellingDevices.map((device) => (
                  <div key={device.name} className="rounded-lg bg-gray-50 p-3">
                    <p className="truncate text-sm font-semibold text-gray-900">{device.name}</p>
                    <div className="mt-1 flex items-center justify-between text-xs text-gray-600">
                      <span>{device.qty} sold</span>
                      {!isStaff ? <span className="font-semibold text-emerald-700">{formatCurrency(device.revenue, 'NGN')}</span> : null}
                    </div>
                  </div>
                ))
              )}
            </div>
          </SectionCard>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-5">
          <SectionCard title="Recent Activity Feed">
            <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
              {activity.length === 0 ? (
                <p className="text-xs text-gray-500">No recent activity</p>
              ) : (
                activity.slice(0, 25).map((row) => {
                  const Icon = activityIcon(row.action)
                  return (
                    <div key={row.id} className="flex items-start gap-3 rounded-lg border border-gray-100 p-2">
                      <div className="mt-0.5 rounded-full bg-gray-100 p-2">
                        <Icon size={14} className="text-gray-700" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-gray-900">{row.action}</p>
                        <p className="text-xs text-gray-500">{row.user || 'System'} • {formatRelative(row.time)}</p>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </SectionCard>
        </div>

        <div className="xl:col-span-4">
          <SectionCard title="Recent Payments">
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-gray-500">
                    <th className="py-2 text-left font-semibold">Client</th>
                    <th className="py-2 text-left font-semibold">Amount</th>
                    <th className="py-2 text-left font-semibold">Method</th>
                    <th className="py-2 text-left font-semibold">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {recentPayments.length === 0 ? (
                    <tr><td colSpan={4} className="py-4 text-center text-gray-400">No recent payments</td></tr>
                  ) : (
                    recentPayments.map((payment) => (
                      <tr key={payment.id} className="border-b last:border-b-0">
                        <td className="py-2 pr-2 truncate max-w-28">{payment.client}</td>
                        <td className="py-2 pr-2 font-semibold">{formatCurrency(payment.amount, 'NGN')}</td>
                        <td className="py-2 pr-2">{payment.method}</td>
                        <td className="py-2">{shortDate(payment.date)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </div>

        <div className="xl:col-span-3">
          <SectionCard title="Recent Inventory Additions">
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-gray-500">
                    <th className="py-2 text-left font-semibold">Item</th>
                    <th className="py-2 text-left font-semibold">Supplier</th>
                    <th className="py-2 text-left font-semibold">Qty</th>
                    <th className="py-2 text-left font-semibold">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {recentInventoryAdditions.length === 0 ? (
                    <tr><td colSpan={4} className="py-4 text-center text-gray-400">No additions</td></tr>
                  ) : (
                    recentInventoryAdditions.map((entry) => (
                      <tr key={entry.id} className="border-b last:border-b-0">
                        <td className="py-2 pr-2 truncate max-w-24">{entry.item}</td>
                        <td className="py-2 pr-2 truncate max-w-20">{entry.supplier}</td>
                        <td className="py-2 pr-2">{entry.quantity}</td>
                        <td className="py-2">{shortDate(entry.date)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  )
}
