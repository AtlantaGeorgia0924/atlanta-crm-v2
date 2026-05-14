import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
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
  profit_seen_this_week: number
  expenses_of_the_week: number
  net_profit_of_the_week: number
  next_week_allowance: number
  profit_seen_this_month: number
  expenses_of_the_month: number
  net_profit_of_the_month: number
  net_profit_left_this_month: number
}

interface CashflowExpense {
  id: string
  amount: number
  description?: string
  expense_date: string
  is_reversed: boolean
  reversed_at?: string
}

interface AllowanceWithdrawal {
  id: string
  week_key: string
  amount: number
  withdrawn_at?: string
  status: 'YES' | 'NO'
}

export default function CashFlow() {
  const qc = useQueryClient()
  const [expenseAmount, setExpenseAmount] = useState('')
  const [expenseDescription, setExpenseDescription] = useState('')

  const { data, isLoading } = useQuery<Statement>({
    queryKey: ['cashflow-statement'],
    queryFn: () => api.get('/cashflow/statement').then((r) => r.data),
  })

  const { data: expenses } = useQuery<CashflowExpense[]>({
    queryKey: ['cashflow-expenses'],
    queryFn: () => api.get('/cashflow/expenses').then((r) => r.data),
  })

  const { data: withdrawals } = useQuery<AllowanceWithdrawal[]>({
    queryKey: ['allowance-withdrawals'],
    queryFn: () => api.get('/cashflow/allowance-withdrawals').then((r) => r.data),
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const refreshMutation = useMutation({
    mutationFn: () => api.post('/sync/refresh-workspace'),
    onSuccess: () => {
      toast.success('Metrics refreshed from Supabase')
      qc.invalidateQueries({ queryKey: ['cashflow-statement'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const createExpenseMutation = useMutation({
    mutationFn: () =>
      api.post('/cashflow/expenses', {
        amount: Number(expenseAmount),
        description: expenseDescription || null,
      }),
    onSuccess: () => {
      toast.success('Expense added')
      setExpenseAmount('')
      setExpenseDescription('')
      qc.invalidateQueries({ queryKey: ['cashflow-expenses'] })
      qc.invalidateQueries({ queryKey: ['cashflow-statement'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Failed to add expense'),
  })

  const reverseExpenseMutation = useMutation({
    mutationFn: (expenseId: string) => api.post(`/cashflow/expenses/${expenseId}/reverse`),
    onSuccess: () => {
      toast.success('Expense reversed')
      qc.invalidateQueries({ queryKey: ['cashflow-expenses'] })
      qc.invalidateQueries({ queryKey: ['cashflow-statement'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Failed to reverse expense'),
  })

  const withdrawAllowanceMutation = useMutation({
    mutationFn: () => api.post('/cashflow/allowance-withdrawals/withdraw', {}),
    onSuccess: () => {
      toast.success('Allowance withdrawn')
      qc.invalidateQueries({ queryKey: ['allowance-withdrawals'] })
      qc.invalidateQueries({ queryKey: ['cashflow-statement'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Allowance withdrawal failed'),
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
    profit_seen_this_week: 0,
    expenses_of_the_week: 0,
    net_profit_of_the_week: 0,
    next_week_allowance: 0,
    profit_seen_this_month: 0,
    expenses_of_the_month: 0,
    net_profit_of_the_month: 0,
    net_profit_left_this_month: 0,
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
          { label: 'Profit Seen This Week', value: statement.profit_seen_this_week, color: 'text-green-600' },
          { label: 'Expenses of the Week', value: statement.expenses_of_the_week, color: 'text-orange-600' },
          { label: 'Net Profit of the Week', value: statement.net_profit_of_the_week, color: statement.net_profit_of_the_week >= 0 ? 'text-emerald-700' : 'text-red-700' },
          { label: 'Next Week Allowance', value: statement.next_week_allowance, color: 'text-blue-700' },
          { label: 'Profit Seen This Month', value: statement.profit_seen_this_month, color: 'text-green-700' },
          { label: 'Expenses of the Month', value: statement.expenses_of_the_month, color: 'text-orange-700' },
          { label: 'Net Profit of the Month', value: statement.net_profit_of_the_month, color: statement.net_profit_of_the_month >= 0 ? 'text-emerald-700' : 'text-red-700' },
          { label: 'Net Profit Left This Month', value: statement.net_profit_left_this_month, color: statement.net_profit_left_this_month >= 0 ? 'text-sky-700' : 'text-red-700' },
        ].map(({ label, value, color }) => (
          <div key={label} className="card text-center">
            <p className="text-xs text-gray-500">{label}</p>
            <p className={`text-xl font-bold ${color}`}>{formatCurrency(value, currency)}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card space-y-3">
          <h2 className="text-lg font-semibold">Add Cash Flow Expense</h2>
          <div className="grid grid-cols-1 gap-3">
            <input
              className="form-input"
              type="number"
              placeholder="Amount"
              value={expenseAmount}
              onChange={(e) => setExpenseAmount(e.target.value)}
            />
            <input
              className="form-input"
              type="text"
              placeholder="Description"
              value={expenseDescription}
              onChange={(e) => setExpenseDescription(e.target.value)}
            />
            <button
              className="btn-primary"
              disabled={!Number(expenseAmount) || createExpenseMutation.isPending}
              onClick={() => createExpenseMutation.mutate()}
            >
              {createExpenseMutation.isPending ? 'Saving...' : 'Save Expense'}
            </button>
          </div>
        </div>

        <div className="card space-y-3">
          <h2 className="text-lg font-semibold">Allowance</h2>
          <p className="text-sm text-gray-600">
            Allowed amount this cycle: <strong>{formatCurrency(statement.next_week_allowance, currency)}</strong>
          </p>
          <button
            className="btn-secondary"
            disabled={withdrawAllowanceMutation.isPending}
            onClick={() => withdrawAllowanceMutation.mutate()}
          >
            {withdrawAllowanceMutation.isPending ? 'Processing...' : 'Withdraw Allowance'}
          </button>
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Expense History</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left border-b">
                <th className="py-2 pr-3">Date</th>
                <th className="py-2 pr-3">Description</th>
                <th className="py-2 pr-3">Amount</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {(expenses ?? []).map((row) => (
                <tr key={row.id} className="border-b">
                  <td className="py-2 pr-3">{new Date(row.expense_date).toLocaleString()}</td>
                  <td className="py-2 pr-3">{row.description || '-'}</td>
                  <td className="py-2 pr-3">{formatCurrency(row.amount, currency)}</td>
                  <td className="py-2 pr-3">{row.is_reversed ? 'Reversed' : 'Active'}</td>
                  <td className="py-2 pr-3">
                    {!row.is_reversed && (
                      <button
                        className="btn-secondary"
                        onClick={() => reverseExpenseMutation.mutate(row.id)}
                        disabled={reverseExpenseMutation.isPending}
                      >
                        Reverse
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Allowance Withdrawal History</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left border-b">
                <th className="py-2 pr-3">Week</th>
                <th className="py-2 pr-3">Amount</th>
                <th className="py-2 pr-3">Withdrawn At</th>
                <th className="py-2 pr-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {(withdrawals ?? []).map((row) => (
                <tr key={row.id} className="border-b">
                  <td className="py-2 pr-3">{row.week_key}</td>
                  <td className="py-2 pr-3">{formatCurrency(row.amount, currency)}</td>
                  <td className="py-2 pr-3">{row.withdrawn_at ? new Date(row.withdrawn_at).toLocaleString() : '-'}</td>
                  <td className="py-2 pr-3">{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
