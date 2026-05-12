import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency, formatDate, statusBadgeClass } from '@/lib/utils'
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
  invoice_date: string
  due_date: string
}

interface FormValues {
  client_name: string
  service_name: string
  description: string
  quantity: number
  unit_price: number
  amount_paid: number
  invoice_date: string
  due_date: string
  notes: string
}

export default function Billing() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<BillingRow | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['billing', statusFilter, page],
    queryFn: () =>
      api.get('/billing', { params: { status: statusFilter || undefined, page, page_size: 50 } }).then((r) => r.data),
  })

  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>()

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) =>
      editRow
        ? api.put(`/billing/${editRow.id}`, values)
        : api.post('/billing', values),
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['billing'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false); setEditRow(null); reset()
    },
    onError: () => toast.error('Save failed'),
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
    reset({
      client_name: row.client_name,
      service_name: row.service_name,
      quantity: row.quantity,
      unit_price: row.unit_price,
      amount_paid: row.amount_paid,
      invoice_date: row.invoice_date?.slice(0, 10),
      due_date: row.due_date?.slice(0, 10),
    })
    setShowForm(true)
  }

  const columns = [
    { key: 'client_name',  header: 'Client' },
    { key: 'service_name', header: 'Service' },
    { key: 'total_amount', header: 'Total', render: (r: BillingRow) => formatCurrency(r.total_amount) },
    { key: 'amount_paid',  header: 'Paid',  render: (r: BillingRow) => formatCurrency(r.amount_paid) },
    { key: 'balance',      header: 'Balance', render: (r: BillingRow) => formatCurrency(r.balance) },
    { key: 'status',       header: 'Status', render: (r: BillingRow) => <span className={statusBadgeClass(r.status)}>{r.status}</span> },
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
        <button onClick={() => { setEditRow(null); reset(); setShowForm(true) }} className="btn-primary"><Plus size={15} /> New Invoice</button>
      </div>

      <div className="flex gap-2">
        {['', 'unpaid', 'partial', 'paid'].map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1) }}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${statusFilter === s ? 'bg-primary-600 text-white border-primary-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      {isLoading ? <LoadingSpinner /> : (
        <>
          <Table columns={columns as any} data={data?.data ?? []} />
          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page}</span>
            <button disabled={data?.data?.length < 50} onClick={() => setPage(p => p + 1)} className="btn-secondary">Next</button>
          </div>
        </>
      )}

      <Modal title={editRow ? 'Edit Invoice' : 'New Invoice'} open={showForm} onClose={() => { setShowForm(false); setEditRow(null); reset() }} size="lg">
        <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="form-label">Client Name</label>
            <input className="form-input" {...register('client_name', { required: 'Required' })} />
            {errors.client_name && <p className="text-xs text-red-500">{errors.client_name.message}</p>}
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
