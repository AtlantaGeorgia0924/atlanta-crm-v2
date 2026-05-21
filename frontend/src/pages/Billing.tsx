import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router-dom'
import { FixedSizeList as List, ListChildComponentProps } from 'react-window'
import { ChevronDown, ChevronLeft, ChevronRight, Plus, Search, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import Modal from '@/components/Modal'
import { formatCurrency, statusBadgeClass, statusLabel } from '@/lib/utils'

interface BillingRow {
  id: string
  client_name: string
  phone_number?: string
  service_name: string
  quantity: number
  total_amount: number
  amount_paid: number
  balance: number
  status: string
  invoice_date?: string
  service_date?: string
  notes?: string
}

interface BillingGroup {
  service_date: string
  items: BillingRow[]
  summary: {
    job_count: number
    total_amount: number
    total_paid: number
    total_outstanding: number
  }
}

interface GroupedResponse {
  groups: BillingGroup[]
  page: number
  total_pages: number
  total: number
}

interface FormValues {
  client_id?: string
  client_name: string
  client_phone?: string
  client_email?: string
  client_address?: string
  client_company?: string
  client_notes?: string
  service_name: string
  description: string
  quantity: number
  unit_price: number
  amount_paid: number
  service_expense: number
  invoice_date: string
  due_date: string
  notes: string
}

interface ClientSuggestion {
  id: string
  name: string
  email?: string
  phone?: string
  address?: string
  company?: string
  notes?: string
}

const ROW_HEIGHT = 54

function getDefaultMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function monthBounds(month: string): { from: string; to: string } {
  const [year, m] = month.split('-').map(Number)
  const start = new Date(year, m - 1, 1)
  const end = new Date(year, m, 0)
  return {
    from: start.toISOString().slice(0, 10),
    to: end.toISOString().slice(0, 10),
  }
}

function labelForDate(dateStr: string): string {
  if (!dateStr || dateStr === 'Unknown') return 'Unknown Date'
  const d = new Date(`${dateStr}T00:00:00`)
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)

  const isSame = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

  if (isSame(d, today)) return 'Today'
  if (isSame(d, yesterday)) return 'Yesterday'

  return d.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

export default function Billing() {
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<BillingRow | null>(null)
  const [clientSearch, setClientSearch] = useState('')
  const [showClientDropdown, setShowClientDropdown] = useState(false)
  const [selectedClientId, setSelectedClientId] = useState('')
  const [collapsedDates, setCollapsedDates] = useState<Record<string, boolean>>({})

  const page = Number(searchParams.get('page') || '1')
  const statusFilter = searchParams.get('status') || ''
  const search = searchParams.get('q') || ''
  const dateFrom = searchParams.get('from') || ''
  const dateTo = searchParams.get('to') || ''
  const month = searchParams.get('month') || getDefaultMonth()
  const minAmount = searchParams.get('min_amount') || ''
  const maxAmount = searchParams.get('max_amount') || ''
  const returned = searchParams.get('returned') || ''
  const paidState = searchParams.get('paid_state') || ''

  const [searchInput, setSearchInput] = useState(search)

  const { register, handleSubmit, reset, setValue, formState: { errors } } = useForm<FormValues>()

  useEffect(() => {
    setSearchInput(search)
  }, [search])

  useEffect(() => {
    const id = setTimeout(() => {
      const next = new URLSearchParams(searchParams)
      const trimmed = searchInput.trim()
      if (trimmed) next.set('q', trimmed)
      else next.delete('q')
      next.set('page', '1')
      setSearchParams(next, { replace: true })
    }, 300)
    return () => clearTimeout(id)
  }, [searchInput]) // eslint-disable-line react-hooks/exhaustive-deps

  const setParam = (key: string, value?: string) => {
    const next = new URLSearchParams(searchParams)
    if (value && value !== '') next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const { data: groupedData, isLoading } = useQuery<GroupedResponse>({
    queryKey: ['billing-grouped', Object.fromEntries(searchParams.entries())],
    queryFn: () =>
      api.get('/billing/grouped', {
        params: {
          page,
          page_size: 200,
          status: statusFilter || undefined,
          q: undefined,
          search: search || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          min_amount: minAmount || undefined,
          max_amount: maxAmount || undefined,
          returned: returned === '' ? undefined : returned === 'true',
          paid_state: paidState || undefined,
        },
      }).then((r) => r.data),
    placeholderData: (prev) => prev,
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { data: clientSearchResults } = useQuery({
    queryKey: ['billing-client-suggestions', clientSearch],
    queryFn: () => api.get('/clients', { params: { search: clientSearch, page: 1, page_size: 8 } }).then((r) => r.data),
    enabled: showForm && clientSearch.trim().length > 0,
  })

  const suggestions: ClientSuggestion[] = useMemo(
    () => (clientSearchResults?.items ?? []).map((c: any) => ({
      id: String(c.id),
      name: c.client_name ?? c.name ?? '',
      email: c.email ?? '',
      phone: c.phone_number ?? c.phone ?? '',
      address: c.address ?? '',
      company: c.company ?? '',
      notes: c.notes ?? '',
    })),
    [clientSearchResults]
  )

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      let clientId = selectedClientId || values.client_id || ''

      if (!editRow && !clientId) {
        const maybeExisting = suggestions.find(
          (s) => s.name.toLowerCase() === String(values.client_name || '').trim().toLowerCase()
        )
        if (maybeExisting) clientId = maybeExisting.id
      }

      if (!editRow && !clientId && values.client_name?.trim() && values.client_phone?.trim()) {
        const createClientRes = await api.post('/clients', {
          client_name: values.client_name,
          phone_number: values.client_phone,
          email: values.client_email || undefined,
          address: values.client_address || undefined,
          company: values.client_company || undefined,
          notes: values.client_notes || undefined,
        })
        clientId = createClientRes?.data?.id || ''
      }

      const payload = {
        ...values,
        amount_paid: Number.isFinite(values.amount_paid) ? values.amount_paid : 0,
        service_expense: Number.isFinite(values.service_expense) ? values.service_expense : 0,
        client_id: clientId || undefined,
      }

      return editRow ? api.put(`/billing/${editRow.id}`, payload) : api.post('/billing', payload)
    },
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false)
      setEditRow(null)
      setSelectedClientId('')
      setClientSearch('')
      setShowClientDropdown(false)
      reset()
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/billing/${id}`),
    onSuccess: () => {
      toast.success('Deleted')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
    },
  })

  const openEdit = (row: BillingRow) => {
    setEditRow(row)
    setClientSearch(row.client_name)
    setSelectedClientId('')
    reset({
      client_name: row.client_name,
      service_name: row.service_name,
      quantity: row.quantity,
      unit_price: Number(row.total_amount) / (Number(row.quantity) || 1),
      amount_paid: row.amount_paid,
      invoice_date: (row.invoice_date || row.service_date || '').slice(0, 10),
      due_date: '',
    } as FormValues)
    setShowForm(true)
  }

  const grouped: BillingGroup[] = useMemo(() => groupedData?.groups ?? [], [groupedData])

  const totalSummary = useMemo(() => {
    let totalAmount = 0
    let totalPaid = 0
    let totalOutstanding = 0
    let jobs = 0
    for (const g of grouped) {
      totalAmount += Number(g.summary.total_amount || 0)
      totalPaid += Number(g.summary.total_paid || 0)
      totalOutstanding += Number(g.summary.total_outstanding || 0)
      jobs += Number(g.summary.job_count || 0)
    }
    return { totalAmount, totalPaid, totalOutstanding, jobs }
  }, [grouped])

  const shiftMonth = (delta: number) => {
    const [y, m] = month.split('-').map(Number)
    const d = new Date(y, m - 1 + delta, 1)
    const nextMonth = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    const bounds = monthBounds(nextMonth)
    const next = new URLSearchParams(searchParams)
    next.set('month', nextMonth)
    next.set('from', bounds.from)
    next.set('to', bounds.to)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const applyQuickRange = (type: 'today' | 'week' | 'month') => {
    const now = new Date()
    let from = ''
    let to = now.toISOString().slice(0, 10)

    if (type === 'today') {
      from = to
    } else if (type === 'week') {
      const start = new Date(now)
      start.setDate(now.getDate() - now.getDay())
      from = start.toISOString().slice(0, 10)
    } else {
      const start = new Date(now.getFullYear(), now.getMonth(), 1)
      from = start.toISOString().slice(0, 10)
      const monthValue = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
      setParam('month', monthValue)
    }

    const next = new URLSearchParams(searchParams)
    next.set('from', from)
    next.set('to', to)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const closeForm = () => {
    setShowForm(false)
    setEditRow(null)
    setSelectedClientId('')
    setClientSearch('')
    setShowClientDropdown(false)
    reset()
  }

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-bold">Service / Billing</h1>
        <button onClick={() => {
          setEditRow(null)
          setClientSearch('')
          setSelectedClientId('')
          setShowClientDropdown(false)
          reset()
          setShowForm(true)
        }} className="btn-primary">
          <Plus size={15} /> New Invoice
        </button>
      </div>

      <div className="rounded-xl border p-3 bg-white" style={{ borderColor: '#e7d89f' }}>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <button className="btn-secondary py-1 px-2" onClick={() => shiftMonth(-1)}><ChevronLeft size={15} /></button>
            <input
              type="month"
              className="form-input"
              value={month}
              onChange={(e) => {
                const val = e.target.value
                const bounds = monthBounds(val)
                const next = new URLSearchParams(searchParams)
                next.set('month', val)
                next.set('from', bounds.from)
                next.set('to', bounds.to)
                next.set('page', '1')
                setSearchParams(next, { replace: true })
              }}
            />
            <button className="btn-secondary py-1 px-2" onClick={() => shiftMonth(1)}><ChevronRight size={15} /></button>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-secondary py-1 px-2 text-xs" onClick={() => applyQuickRange('today')}>Today</button>
            <button className="btn-secondary py-1 px-2 text-xs" onClick={() => applyQuickRange('week')}>This Week</button>
            <button className="btn-secondary py-1 px-2 text-xs" onClick={() => applyQuickRange('month')}>This Month</button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-3 text-gray-400" />
          <input className="form-input pl-8" placeholder="Search client, phone, service, notes, record id..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        </div>
        <select className="form-input" value={statusFilter} onChange={(e) => setParam('status', e.target.value)}>
          <option value="">All payment status</option>
          <option value="PAID">PAID</option>
          <option value="PART PAYMENT">PART PAYMENT</option>
          <option value="UNPAID">UNPAID</option>
          <option value="RETURNED">RETURNED</option>
        </select>
        <select className="form-input" value={paidState} onChange={(e) => setParam('paid_state', e.target.value)}>
          <option value="">All paid states</option>
          <option value="paid">Paid only</option>
          <option value="unpaid">Unpaid/partial</option>
        </select>
        <input type="date" className="form-input" value={dateFrom} onChange={(e) => setParam('from', e.target.value)} />
        <input type="date" className="form-input" value={dateTo} onChange={(e) => setParam('to', e.target.value)} />
        <input type="number" min="0" className="form-input" placeholder="Min amount" value={minAmount} onChange={(e) => setParam('min_amount', e.target.value)} />
        <input type="number" min="0" className="form-input" placeholder="Max amount" value={maxAmount} onChange={(e) => setParam('max_amount', e.target.value)} />
        <select className="form-input" value={returned} onChange={(e) => setParam('returned', e.target.value)}>
          <option value="">All return states</option>
          <option value="false">Not returned</option>
          <option value="true">Returned</option>
        </select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card p-3">
          <p className="text-xs text-gray-500">Jobs</p>
          <p className="text-xl font-semibold">{totalSummary.jobs}</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Total Amount</p>
          <p className="text-xl font-semibold">{formatCurrency(totalSummary.totalAmount, currency)}</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Paid</p>
          <p className="text-xl font-semibold">{formatCurrency(totalSummary.totalPaid, currency)}</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Outstanding</p>
          <p className="text-xl font-semibold text-red-600">{formatCurrency(totalSummary.totalOutstanding, currency)}</p>
        </div>
      </div>

      {isLoading ? <LoadingSpinner /> : (
        <div className="space-y-3">
          {grouped.length === 0 && (
            <div className="rounded-xl border p-6 text-sm text-gray-500" style={{ borderColor: '#e7d89f' }}>
              No jobs found for the current filters.
            </div>
          )}
          {grouped.map((group: BillingGroup) => {
            const collapsed = !!collapsedDates[group.service_date]
            const height = Math.min(360, Math.max(ROW_HEIGHT * group.items.length + 6, 60))
            return (
              <section key={group.service_date} className="rounded-xl border bg-white" style={{ borderColor: '#e7d89f' }}>
                <button
                  className="w-full text-left px-4 py-3 border-b flex items-center justify-between"
                  style={{ borderColor: '#f1e7bf' }}
                  onClick={() => setCollapsedDates((prev) => ({ ...prev, [group.service_date]: !collapsed }))}
                >
                  <div>
                    <p className="font-semibold text-gray-900">{labelForDate(group.service_date)}</p>
                    <p className="text-xs text-gray-500">{group.service_date}</p>
                  </div>
                  <div className="flex items-center gap-5 text-xs text-gray-600">
                    <span>{group.summary.job_count} jobs</span>
                    <span>Total {formatCurrency(group.summary.total_amount, currency)}</span>
                    <span>Paid {formatCurrency(group.summary.total_paid, currency)}</span>
                    <span className="text-red-600">Outstanding {formatCurrency(group.summary.total_outstanding, currency)}</span>
                    <ChevronDown size={15} className={`transition-transform ${collapsed ? '-rotate-90' : ''}`} />
                  </div>
                </button>

                {!collapsed && (
                  <div className="p-1">
                    <List
                      height={height}
                      width={1200}
                      itemCount={group.items.length}
                      itemSize={ROW_HEIGHT}
                    >
                      {({ index, style }: ListChildComponentProps) => {
                        const row = group.items[index]
                        return (
                          <div style={style} className="px-3">
                            <div className="grid grid-cols-12 items-center gap-2 border-b py-2 text-sm" style={{ borderColor: '#f7f1d8' }}>
                              <div className="col-span-2 truncate font-medium" title={row.client_name}>{row.client_name}</div>
                              <div className="col-span-2 truncate" title={row.service_name}>{row.service_name}</div>
                              <div className="col-span-2">{formatCurrency(row.total_amount, currency)}</div>
                              <div className="col-span-2">{formatCurrency(row.amount_paid, currency)}</div>
                              <div className="col-span-2 text-red-600">{formatCurrency(row.balance, currency)}</div>
                              <div className="col-span-1"><span className={statusBadgeClass(row.status)}>{statusLabel(row.status)}</span></div>
                              <div className="col-span-1 flex justify-end gap-1">
                                <button className="btn-secondary py-1 px-2 text-xs" onClick={() => openEdit(row)}>Edit</button>
                                <button
                                  className="text-red-500 hover:text-red-700"
                                  onClick={() => {
                                    if (confirm('Delete invoice?')) deleteMutation.mutate(row.id)
                                  }}
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            </div>
                          </div>
                        )
                      }}
                    </List>
                  </div>
                )}
              </section>
            )
          })}

          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setParam('page', String(page - 1))} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page} of {groupedData?.total_pages ?? 1}</span>
            <button disabled={page >= (groupedData?.total_pages ?? 1)} onClick={() => setParam('page', String(page + 1))} className="btn-secondary">Next</button>
          </div>
        </div>
      )}

      <Modal
        title={editRow ? 'Edit Invoice' : 'New Invoice'}
        open={showForm}
        onClose={closeForm}
        size="lg"
        bodyClassName="pb-2"
        footer={(
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={closeForm}>Cancel</button>
            <button type="submit" form="invoice-form" className="btn-primary" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        )}
      >
        <form id="invoice-form" onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="grid grid-cols-2 gap-4">
          <input type="hidden" {...register('client_id')} />
          <div className="col-span-2 relative">
            <label className="form-label">Client Name</label>
            <input
              className="form-input"
              {...register('client_name', { required: 'Required' })}
              value={clientSearch}
              onChange={(e) => {
                setClientSearch(e.target.value)
                setSelectedClientId('')
                setShowClientDropdown(true)
                setValue('client_name', e.target.value)
                setValue('client_id', '')
              }}
              onFocus={() => setShowClientDropdown(true)}
            />
            {showClientDropdown && clientSearch.trim() && suggestions.length > 0 && (
              <div className="absolute z-20 mt-1 w-full rounded-lg border bg-white shadow" style={{ borderColor: '#d4af37' }}>
                {suggestions.map((s) => (
                  <button
                    type="button"
                    key={s.id}
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-[#fff9e7]"
                    onClick={() => {
                      setSelectedClientId(s.id)
                      setClientSearch(s.name)
                      setValue('client_id', s.id)
                      setValue('client_name', s.name)
                      setValue('client_phone', s.phone || '')
                      setShowClientDropdown(false)
                    }}
                  >
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-gray-500">{s.phone || 'No phone'} - {s.email || 'No email'}</div>
                  </button>
                ))}
              </div>
            )}
            {errors.client_name && <p className="text-xs text-red-500">{errors.client_name.message}</p>}
          </div>
          <div>
            <label className="form-label">Client Phone</label>
            <input className="form-input" {...register('client_phone')} />
          </div>
          <div>
            <label className="form-label">Service Name</label>
            <input className="form-input" {...register('service_name', { required: 'Required' })} />
          </div>
          <div>
            <label className="form-label">Quantity</label>
            <input type="number" step="0.01" className="form-input" {...register('quantity', { valueAsNumber: true })} />
          </div>
          <div>
            <label className="form-label">Unit Price</label>
            <input type="number" step="0.01" className="form-input" {...register('unit_price', { valueAsNumber: true, required: 'Required' })} />
          </div>
          <div>
            <label className="form-label">Amount Paid</label>
            <input type="number" step="0.01" className="form-input" {...register('amount_paid', { valueAsNumber: true })} />
          </div>
          <div>
            <label className="form-label">Service Expense</label>
            <input type="number" step="0.01" className="form-input" {...register('service_expense', { valueAsNumber: true })} />
          </div>
          <div>
            <label className="form-label">Invoice Date</label>
            <input type="date" className="form-input" {...register('invoice_date')} />
          </div>
          <div>
            <label className="form-label">Due Date</label>
            <input type="date" className="form-input" {...register('due_date')} />
          </div>
          <div className="col-span-2">
            <label className="form-label">Notes</label>
            <textarea className="form-input" rows={2} {...register('notes')} />
          </div>
        </form>
      </Modal>
    </div>
  )
}
