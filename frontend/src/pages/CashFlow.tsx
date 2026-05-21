import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { DollarSign, RefreshCw, Wallet } from 'lucide-react'
import { useState } from 'react'
import toast from 'react-hot-toast'

const PAGE_SIZE = 50

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

interface Statement {
  amount_owed: number
  monthly_sales: number
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

interface PaginatedResult<T> {
  items: T[]
  page: number
  page_size: number
  total_count: number
  total_pages: number
}

interface CashflowPageData {
  statement: Statement
  expenses: PaginatedResult<CashflowExpense>
  withdrawals: PaginatedResult<AllowanceWithdrawal>
  currency: string
}

function formatLagosDateTime(value?: string) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('en-NG', {
    timeZone: 'Africa/Lagos',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export default function CashFlow() {
  const qc = useQueryClient()
  const [expenseAmount, setExpenseAmount] = useState('')
  const [expenseDescription, setExpenseDescription] = useState('')
  const [expensePage, setExpensePage] = useState(1)
  const [withdrawalsPage, setWithdrawalsPage] = useState(1)
  const [reversingIds, setReversingIds] = useState<Set<string>>(new Set())

  const queryKey = ['cashflow-page-data', expensePage, withdrawalsPage, PAGE_SIZE] as const

  const { data: pageData, isLoading, isError, refetch } = useQuery<CashflowPageData>({
    queryKey,
    queryFn: () =>
      api
        .get('/cashflow/page-data', {
          params: {
            expense_page: expensePage,
            withdrawals_page: withdrawalsPage,
            page_size: PAGE_SIZE,
          },
        })
        .then((r) => r.data),
  })
  const currency = pageData?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const refreshMutation = useMutation({
    mutationFn: () => api.post('/sync/refresh-workspace'),
    onSuccess: () => {
      toast.success('Metrics refreshed from Supabase')
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
    },
  })

  const createExpenseMutation = useMutation({
    mutationFn: ({ amount, description }: { amount: number; description: string | null }) =>
      api.post('/cashflow/expenses', {
        amount,
        description,
      }),
    onMutate: async ({ amount, description }) => {
      await qc.cancelQueries({ queryKey })
      const previous = qc.getQueryData<CashflowPageData>(queryKey)

      if (previous) {
        const optimistic: CashflowExpense = {
          id: `temp-${Date.now()}`,
          amount,
          description: description ?? undefined,
          expense_date: new Date().toISOString(),
          is_reversed: false,
        }
        const nextItems = expensePage === 1 ? [optimistic, ...previous.expenses.items].slice(0, PAGE_SIZE) : previous.expenses.items
        const nextCount = previous.expenses.total_count + 1

        qc.setQueryData<CashflowPageData>(queryKey, {
          ...previous,
          expenses: {
            ...previous.expenses,
            items: nextItems,
            total_count: nextCount,
            total_pages: Math.max(1, Math.ceil(nextCount / PAGE_SIZE)),
          },
        })
      }

      setExpenseAmount('')
      setExpenseDescription('')
      return { previous }
    },
    onSuccess: () => {
      toast.success('Expense added')
    },
    onError: (e: any, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(queryKey, context.previous)
      }
      toast.error(e?.response?.data?.detail ?? 'Failed to add expense')
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
    },
  })

  const reverseExpenseMutation = useMutation({
    mutationFn: (expenseId: string) => api.post(`/cashflow/expenses/${expenseId}/reverse`),
    onMutate: async (expenseId: string) => {
      setReversingIds((prev) => new Set(prev).add(expenseId))
      await qc.cancelQueries({ queryKey })
      const previous = qc.getQueryData<CashflowPageData>(queryKey)

      if (previous) {
        qc.setQueryData<CashflowPageData>(queryKey, {
          ...previous,
          expenses: {
            ...previous.expenses,
            items: previous.expenses.items.map((item) =>
              item.id === expenseId ? { ...item, is_reversed: true, reversed_at: new Date().toISOString() } : item,
            ),
          },
        })
      }

      return { previous, expenseId }
    },
    onSuccess: () => {
      toast.success('Expense reversed')
    },
    onError: (e: any, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(queryKey, context.previous)
      }
      toast.error(e?.response?.data?.detail ?? 'Failed to reverse expense')
    },
    onSettled: (_data, _error, expenseId) => {
      setReversingIds((prev) => {
        const next = new Set(prev)
        next.delete(expenseId)
        return next
      })
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
    },
  })

  const withdrawAllowanceMutation = useMutation({
    mutationFn: () => api.post('/cashflow/allowance-withdrawals/withdraw', {}),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey })
      const previous = qc.getQueryData<CashflowPageData>(queryKey)

      if (previous) {
        const optimistic: AllowanceWithdrawal = {
          id: `temp-${Date.now()}`,
          week_key: 'Current Week',
          amount: previous.statement.next_week_allowance,
          withdrawn_at: new Date().toISOString(),
          status: 'YES',
        }
        const nextItems = withdrawalsPage === 1 ? [optimistic, ...previous.withdrawals.items].slice(0, PAGE_SIZE) : previous.withdrawals.items
        const nextCount = previous.withdrawals.total_count + 1

        qc.setQueryData<CashflowPageData>(queryKey, {
          ...previous,
          statement: {
            ...previous.statement,
            next_week_allowance: 0,
          },
          withdrawals: {
            ...previous.withdrawals,
            items: nextItems,
            total_count: nextCount,
            total_pages: Math.max(1, Math.ceil(nextCount / PAGE_SIZE)),
          },
        })
      }

      return { previous }
    },
    onSuccess: () => {
      toast.success('Allowance withdrawn')
    },
    onError: (e: any, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(queryKey, context.previous)
      }
      toast.error(e?.response?.data?.detail ?? 'Allowance withdrawal failed')
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
    },
  })

  if (isLoading) return <LoadingSpinner />

  if (isError) {
    return (
      <div className="p-8">
        <div className="card space-y-3">
          <h2 className="text-lg font-semibold text-red-700">Could not load Cash Flow data</h2>
          <p className="text-sm text-gray-600">Please check your connection and try again.</p>
          <button className="btn-secondary" onClick={() => refetch()}>
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!pageData?.statement) {
    return (
      <div className="p-8">
        <div className="card space-y-3">
          <h2 className="text-lg font-semibold">No Cash Flow statement available</h2>
          <p className="text-sm text-gray-600">Refresh workspace to generate financial metrics.</p>
          <button className="btn-secondary" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
            {refreshMutation.isPending ? 'Refreshing...' : 'Refresh Workspace'}
          </button>
        </div>
      </div>
    )
  }

  const statement = pageData?.statement ?? {
    amount_owed: 0,
    monthly_sales: 0,
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
  const expenses = pageData?.expenses.items ?? []
  const withdrawals = pageData?.withdrawals.items ?? []

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Cash Flow</h1>
        <button className="btn-secondary" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
          <RefreshCw size={15} className={refreshMutation.isPending ? 'animate-spin' : ''} />
          Refresh Workspace
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <StatCard
          label="Amount Owed"
          value={formatCurrency(statement.amount_owed, currency)}
          icon={Wallet}
          color="bg-rose-500"
        />
        <StatCard
          label="Monthly Sales"
          value={formatCurrency(statement.monthly_sales, currency)}
          icon={DollarSign}
          color="bg-teal-500"
        />
        <StatCard
          label="Net Profit"
          value={formatCurrency(statement.net_profit, currency)}
          icon={DollarSign}
          color="bg-emerald-600"
        />
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
              onClick={() =>
                createExpenseMutation.mutate({
                  amount: Number(expenseAmount),
                  description: expenseDescription || null,
                })
              }
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
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Expense History</h2>
          <div className="flex items-center gap-2 text-xs text-gray-600">
            <button
              className="btn-secondary"
              disabled={expensePage <= 1}
              onClick={() => setExpensePage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <span>
              Page {pageData?.expenses.page ?? 1} of {pageData?.expenses.total_pages ?? 1}
            </span>
            <button
              className="btn-secondary"
              disabled={expensePage >= (pageData?.expenses.total_pages ?? 1)}
              onClick={() => setExpensePage((p) => Math.min(pageData?.expenses.total_pages ?? p, p + 1))}
            >
              Next
            </button>
          </div>
        </div>
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
              {expenses.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-4 text-center text-sm text-gray-500">
                    No expenses yet.
                  </td>
                </tr>
              )}
              {expenses.map((row) => (
                <tr key={row.id} className="border-b">
                  <td className="py-2 pr-3">{formatLagosDateTime(row.expense_date)}</td>
                  <td className="py-2 pr-3">{row.description || '-'}</td>
                  <td className="py-2 pr-3">{formatCurrency(row.amount, currency)}</td>
                  <td className="py-2 pr-3">{row.is_reversed ? 'Reversed' : 'Active'}</td>
                  <td className="py-2 pr-3">
                    {!row.is_reversed && (
                      <button
                        className="btn-secondary"
                        onClick={() => reverseExpenseMutation.mutate(row.id)}
                        disabled={reversingIds.has(row.id)}
                      >
                        {reversingIds.has(row.id) ? 'Reversing...' : 'Reverse'}
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
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Allowance Withdrawal History</h2>
          <div className="flex items-center gap-2 text-xs text-gray-600">
            <button
              className="btn-secondary"
              disabled={withdrawalsPage <= 1}
              onClick={() => setWithdrawalsPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <span>
              Page {pageData?.withdrawals.page ?? 1} of {pageData?.withdrawals.total_pages ?? 1}
            </span>
            <button
              className="btn-secondary"
              disabled={withdrawalsPage >= (pageData?.withdrawals.total_pages ?? 1)}
              onClick={() => setWithdrawalsPage((p) => Math.min(pageData?.withdrawals.total_pages ?? p, p + 1))}
            >
              Next
            </button>
          </div>
        </div>
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
              {withdrawals.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-4 text-center text-sm text-gray-500">
                    No allowance withdrawals yet.
                  </td>
                </tr>
              )}
              {withdrawals.map((row) => (
                <tr key={row.id} className="border-b">
                  <td className="py-2 pr-3">{row.week_key}</td>
                  <td className="py-2 pr-3">{formatCurrency(row.amount, currency)}</td>
                  <td className="py-2 pr-3">{formatLagosDateTime(row.withdrawn_at)}</td>
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
