import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Users, FileText, DollarSign, AlertCircle, Package, TrendingDown } from 'lucide-react'

interface Summary {
  total_clients: number
  total_invoices: number
  total_billed: number
  total_collected: number
  total_outstanding: number
  total_expenses: number
  total_allowances: number
  low_stock_count: number
}

function StatCard({ label, value, icon: Icon, color }: { label: string; value: string | number; icon: React.ElementType; color: string }) {
  return (
    <div className="card flex items-start gap-4">
      <div className={`p-2 rounded-lg ${color}`}>
        <Icon size={20} className="text-white" />
      </div>
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-xl font-bold text-gray-900">{value}</p>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { data, isLoading } = useQuery<Summary>({
    queryKey: ['dashboard'],
    queryFn: () => api.get('/dashboard').then((r) => r.data),
    refetchInterval: 60_000,
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })

  if (isLoading) return <LoadingSpinner />

  const s = data!
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  return (
    <div className="p-8 space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Clients"          value={s.total_clients}                       icon={Users}      color="bg-blue-500" />
        <StatCard label="Total Invoices"   value={s.total_invoices}                      icon={FileText}   color="bg-indigo-500" />
        <StatCard label="Total Billed"     value={formatCurrency(s.total_billed, currency)}   icon={DollarSign} color="bg-green-500" />
        <StatCard label="Collected"        value={formatCurrency(s.total_collected, currency)} icon={DollarSign} color="bg-teal-500" />
        <StatCard label="Outstanding"      value={formatCurrency(s.total_outstanding, currency)} icon={AlertCircle} color="bg-red-500" />
        <StatCard label="Total Expenses"   value={formatCurrency(s.total_expenses, currency)}   icon={TrendingDown} color="bg-orange-500" />
        <StatCard label="Allowances"       value={formatCurrency(s.total_allowances, currency)} icon={DollarSign} color="bg-purple-500" />
        <StatCard label="Low Stock Items"  value={s.low_stock_count}                     icon={Package}    color="bg-yellow-500" />
      </div>
    </div>
  )
}
