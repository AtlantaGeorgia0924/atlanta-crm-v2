import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'

interface Statement {
  total_sales: number
  total_collected: number
  total_outstanding: number
  total_expenses: number
  total_service_expenses: number
  total_allowances: number
  gross_profit: number
  net_profit: number
}

export default function CashFlow() {
  const qc = useQueryClient()

  const { data, isLoading } = useQuery<Statement>({
    queryKey: ['cashflow-statement'],
    queryFn: () => api.get('/cashflow/statement').then((r) => r.data),
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const refreshMutation = useMutation({
    mutationFn: () => api.post('/sync/refresh-workspace'),
    onSuccess: () => {
      toast.success('Metrics refreshed from Google Sheets')
      qc.invalidateQueries({ queryKey: ['cashflow-statement'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  if (isLoading) return <LoadingSpinner />

  const statement = data ?? {
    total_sales: 0,
    total_collected: 0,
    total_outstanding: 0,
    total_expenses: 0,
    total_service_expenses: 0,
    total_allowances: 0,
    gross_profit: 0,
    net_profit: 0,
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Cash Flow</h1>
        <button className="btn-secondary" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
          <RefreshCw size={15} className={refreshMutation.isPending ? 'animate-spin' : ''} />
          Refresh Workspace
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Sales', value: statement.total_sales, color: 'text-green-600' },
          { label: 'Total Collected', value: statement.total_collected, color: 'text-teal-600' },
          { label: 'Total Outstanding', value: statement.total_outstanding, color: 'text-red-600' },
          { label: 'Total Expenses', value: statement.total_expenses, color: 'text-orange-600' },
          { label: 'Total Service Expenses', value: statement.total_service_expenses, color: 'text-amber-700' },
          { label: 'Total Allowances', value: statement.total_allowances, color: 'text-yellow-700' },
          { label: 'Gross Profit', value: statement.gross_profit, color: statement.gross_profit >= 0 ? 'text-blue-600' : 'text-red-700' },
          { label: 'Net Profit', value: statement.net_profit, color: statement.net_profit >= 0 ? 'text-emerald-700' : 'text-red-700' },
        ].map(({ label, value, color }) => (
          <div key={label} className="card text-center">
            <p className="text-xs text-gray-500">{label}</p>
            <p className={`text-xl font-bold ${color}`}>{formatCurrency(value, currency)}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
