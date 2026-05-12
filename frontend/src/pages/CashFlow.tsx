import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

interface CashFlowRow {
  period_month: string
  total_revenue: number
  total_expenses: number
  total_allowances: number
  gross_profit: number
}

export default function CashFlow() {
  const qc = useQueryClient()
  const [year, setYear] = useState(new Date().getFullYear().toString())

  const { data, isLoading } = useQuery<CashFlowRow[]>({
    queryKey: ['cashflow', year],
    queryFn: () => api.get('/cashflow', { params: { year } }).then((r) => r.data),
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const refreshMutation = useMutation({
    mutationFn: () => api.post('/cashflow/refresh'),
    onSuccess: () => {
      toast.success('Refresh started in background')
      setTimeout(() => qc.invalidateQueries({ queryKey: ['cashflow'] }), 3000)
    },
  })

  const chartData = (data ?? []).map((r) => ({
    month: r.period_month,
    Revenue:    Number(r.total_revenue),
    Expenses:   Number(r.total_expenses),
    Allowances: Number(r.total_allowances),
    Profit:     Number(r.gross_profit),
  }))

  const totals = (data ?? []).reduce(
    (acc, r) => ({
      revenue:    acc.revenue    + Number(r.total_revenue),
      expenses:   acc.expenses   + Number(r.total_expenses),
      allowances: acc.allowances + Number(r.total_allowances),
      profit:     acc.profit     + Number(r.gross_profit),
    }),
    { revenue: 0, expenses: 0, allowances: 0, profit: 0 }
  )

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Cash Flow</h1>
        <div className="flex gap-2 items-center">
          <input
            type="number"
            className="form-input w-28"
            value={year}
            min="2000"
            max="2099"
            onChange={(e) => setYear(e.target.value)}
          />
          <button className="btn-secondary" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
            <RefreshCw size={15} className={refreshMutation.isPending ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Revenue',    value: totals.revenue,    color: 'text-green-600' },
          { label: 'Expenses',   value: totals.expenses,   color: 'text-red-600' },
          { label: 'Allowances', value: totals.allowances, color: 'text-orange-600' },
          { label: 'Net Profit', value: totals.profit,     color: totals.profit >= 0 ? 'text-blue-600' : 'text-red-700' },
        ].map(({ label, value, color }) => (
          <div key={label} className="card text-center">
            <p className="text-xs text-gray-500">{label}</p>
            <p className={`text-xl font-bold ${color}`}>{formatCurrency(value, currency)}</p>
          </div>
        ))}
      </div>

      {isLoading ? <LoadingSpinner /> : (
        <>
          <div className="card">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData} margin={{ top: 5, right: 20, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis />
                <Tooltip formatter={(v: number) => formatCurrency(v, currency)} />
                <Legend />
                <Bar dataKey="Revenue"    fill="#22c55e" />
                <Bar dataKey="Expenses"   fill="#ef4444" />
                <Bar dataKey="Allowances" fill="#f97316" />
                <Bar dataKey="Profit"     fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded-xl border border-gray-200">
            <table className="min-w-full text-sm divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {['Month', 'Revenue', 'Expenses', 'Allowances', 'Net Profit'].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-medium text-gray-600">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {(data ?? []).map((r) => (
                  <tr key={r.period_month} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{r.period_month}</td>
                    <td className="px-4 py-3 text-green-700">{formatCurrency(r.total_revenue, currency)}</td>
                    <td className="px-4 py-3 text-red-700">{formatCurrency(r.total_expenses, currency)}</td>
                    <td className="px-4 py-3 text-orange-700">{formatCurrency(r.total_allowances, currency)}</td>
                    <td className={`px-4 py-3 font-semibold ${Number(r.gross_profit) >= 0 ? 'text-blue-700' : 'text-red-700'}`}>
                      {formatCurrency(r.gross_profit, currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
