import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency, formatDate, statusBadgeClass, statusLabel } from '@/lib/utils'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

interface BillingRow {
  id: string
  client_name: string
  service_name: string
  quantity: number
  unit_price: number
  total_amount: number
  amount_paid: number
  balance: number
  status: string
  service_expense: number
  gross_profit: number
  net_profit: number
  invoice_date: string
  due_date: string
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

export default function Billing() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<BillingRow | null>(null)
  const [clientSearch, setClientSearch] = useState('')
  const [showClientDropdown, setShowClientDropdown] = useState(false)
  const [selectedClientId, setSelectedClientId] = useState<string>('')

  const { data, isLoading } = useQuery({
    queryKey: ['billing', statusFilter, page],
    queryFn: () =>
      api.get('/billing', { params: { status: statusFilter || undefined, page, page_size: 50 } }).then((r) => r.data),
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { register, handleSubmit, reset, setValue, formState: { errors } } = useForm<FormValues>()

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

  useEffect(() => {
    if (!showForm) return
    const timer = setTimeout(() => setClientSearch((v) => v.trim()), 200)
    return () => clearTimeout(timer)
  }, [clientSearch, showForm])

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      let clientId = selectedClientId || values.client_id || ''

      if (!editRow && !clientId) {
        const maybeExisting = suggestions.find(
          (s) => s.name.toLowerCase() === String(values.client_name || '').trim().toLowerCase()
        )
        if (maybeExisting) {
          clientId = maybeExisting.id
        }
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

      return editRow
        ? api.put(`/billing/${editRow.id}`, payload)
        : api.post('/billing', payload)
    },
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['billing'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false); setEditRow(null); setSelectedClientId(''); setClientSearch(''); setShowClientDropdown(false); reset()
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/billing/${id}`),
    onSuccess: () => {
      toast.success('Deleted')
      qc.invalidateQueries({ queryKey: ['billing'] })
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
      unit_price: row.unit_price,
      amount_paid: row.amount_paid,
      service_expense: row.service_expense || 0,
      invoice_date: row.invoice_date?.slice(0, 10),
      due_date: row.due_date?.slice(0, 10),
    })
    setShowForm(true)
  }

  const selectClient = (client: ClientSuggestion) => {
    setSelectedClientId(client.id)
    setClientSearch(client.name)
    setValue('client_id', client.id)
    setValue('client_name', client.name)
    setValue('client_phone', client.phone || '')
    setValue('client_email', client.email || '')
    setValue('client_address', client.address || '')
    setValue('client_company', client.company || '')
    setValue('client_notes', client.notes || '')
    setShowClientDropdown(false)
  }

  const columns = [
    { key: 'client_name',  header: 'Client' },
    { key: 'service_name', header: 'Service' },
    { key: 'total_amount', header: 'Total', render: (r: BillingRow) => formatCurrency(r.total_amount, currency) },
    { key: 'amount_paid',  header: 'Paid',  render: (r: BillingRow) => formatCurrency(r.amount_paid, currency) },
    { key: 'service_expense', header: 'Expense', render: (r: BillingRow) => formatCurrency(r.service_expense || 0, currency) },
    { key: 'net_profit', header: 'Net Profit', render: (r: BillingRow) => formatCurrency(r.net_profit || 0, currency) },
    { key: 'balance',      header: 'Balance', render: (r: BillingRow) => formatCurrency(r.balance, currency) },
    { key: 'status',       header: 'Status', render: (r: BillingRow) => <span className={statusBadgeClass(r.status)}>{statusLabel(r.status)}</span> },
    { key: 'invoice_date', header: 'Date', render: (r: BillingRow) => formatDate(r.invoice_date) },
    {
      key: 'actions', header: '',
      render: (r: BillingRow) => (
        <div className="flex gap-2">
          <button onClick={() => openEdit(r)} className="text-gray-400 hover:text-primary-600"><Pencil size={14} /></button>
          <button onClick={() => { if (confirm('Delete?')) deleteMutation.mutate(r.id) }} className="text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Service / Billing</h1>
        <button onClick={() => { setEditRow(null); setClientSearch(''); setSelectedClientId(''); setShowClientDropdown(false); reset(); setShowForm(true) }} className="btn-primary"><Plus size={15} /> New Invoice</button>
      </div>

      <div className="flex gap-2">
        {['', 'unpaid', 'partial', 'paid'].map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1) }}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${statusFilter === s ? 'text-black border-[#D4AF37] bg-[#D4AF37]' : 'bg-white text-gray-600 border-gray-300 hover:bg-[#fff9e7] hover:border-[#D4AF37] hover:text-black'}`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      {isLoading ? <LoadingSpinner /> : (
        <>
          <Table columns={columns as any} data={data?.items ?? data?.data ?? []} />
          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page} of {data?.total_pages ?? 1}</span>
            <button disabled={page >= (data?.total_pages ?? 1)} onClick={() => setPage(p => p + 1)} className="btn-secondary">Next</button>
          </div>
        </>
      )}

      <Modal title={editRow ? 'Edit Invoice' : 'New Invoice'} open={showForm} onClose={() => { setShowForm(false); setEditRow(null); setSelectedClientId(''); setClientSearch(''); setShowClientDropdown(false); reset() }} size="lg">
        <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="grid grid-cols-2 gap-4">
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
                    onClick={() => selectClient(s)}
                  >
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-gray-500">{s.phone || 'No phone'} • {s.email || 'No email'}</div>
                  </button>
                ))}
              </div>
            )}
            {showClientDropdown && clientSearch.trim() && suggestions.length === 0 && (
              <p className="text-xs text-gray-500 mt-1">No existing client match. You can continue and create a new client from this form.</p>
            )}
            {errors.client_name && <p className="text-xs text-red-500">{errors.client_name.message}</p>}
          </div>
          <div>
            <label className="form-label">Client Phone</label>
            <input className="form-input" {...register('client_phone')} />
          </div>
          <div>
            <label className="form-label">Client Email</label>
            <input className="form-input" {...register('client_email')} />
          </div>
          <div>
            <label className="form-label">Client Company</label>
            <input className="form-input" {...register('client_company')} />
          </div>
          <div>
            <label className="form-label">Client Address</label>
            <input className="form-input" {...register('client_address')} />
          </div>
          <div className="col-span-2">
            <label className="form-label">Client Notes</label>
            <textarea className="form-input" rows={2} {...register('client_notes')} />
          </div>
          <div className="col-span-2">
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
          <div className="col-span-2 flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
