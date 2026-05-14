import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Users, FileText, DollarSign, AlertCircle, Package, TrendingDown, Wallet } from 'lucide-react'

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
        <StatCard label="Clients"            value={s.clients} icon={Users} color="bg-blue-500" />
        <StatCard label="Total Invoices"     value={s.total_invoices} icon={FileText} color="bg-indigo-500" />
        <StatCard label="Total Unpaid"       value={s.total_unpaid} icon={AlertCircle} color="bg-red-500" />
        <StatCard label="Amount Owed"        value={formatCurrency(s.amount_owed, currency)} icon={Wallet} color="bg-rose-500" />
        <StatCard label="Monthly Sales"      value={formatCurrency(s.monthly_sales, currency)} icon={DollarSign} color="bg-teal-500" />
        <StatCard label="Available Products" value={s.available_products} icon={Package} color="bg-green-600" />
        <StatCard label="Pending Products"   value={s.pending_products} icon={Package} color="bg-amber-500" />
        <StatCard label="Low Quality Stock"  value={s.low_quality_stock} icon={TrendingDown} color="bg-orange-600" />
        <StatCard label="Net Profit"         value={formatCurrency(s.net_profit, currency)} icon={DollarSign} color="bg-emerald-600" />
      </div>
    </div>
  )
}
