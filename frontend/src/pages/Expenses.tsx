import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency, formatDate } from '@/lib/utils'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

interface Expense {
  id: string
  category: string
  description: string
  amount: number
  expense_date: string
  paid_by: string
  receipt_ref: string
}

interface FormValues {
  category: string
  description: string
  amount: number
  expense_date: string
  paid_by: string
  receipt_ref: string
  notes: string
}

export default function Expenses() {
  const qc = useQueryClient()
  const [month, setMonth] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<Expense | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['expenses', month, page],
    queryFn: () =>
      api.get('/expenses', { params: { month: month || undefined, page, page_size: 50 } }).then((r) => r.data),
  })

  const { register, handleSubmit, reset } = useForm<FormValues>()

  const saveMutation = useMutation({
    mutationFn: (v: FormValues) =>
      editRow ? api.put(`/expenses/${editRow.id}`, v) : api.post('/expenses', v),
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['expenses'] })
      qc.invalidateQueries({ queryKey: ['cashflow'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false); setEditRow(null); reset()
    },
    onError: () => toast.error('Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/expenses/${id}`),
    onSuccess: () => {
      toast.success('Deleted')
      qc.invalidateQueries({ queryKey: ['expenses'] })
    },
  })

  const totalAmount = data?.data?.reduce((s: number, r: Expense) => s + Number(r.amount), 0) ?? 0

  const columns = [
    { key: 'expense_date', header: 'Date', render: (r: Expense) => formatDate(r.expense_date) },
    { key: 'category',     header: 'Category' },
    { key: 'description',  header: 'Description' },
    { key: 'amount',       header: 'Amount', render: (r: Expense) => formatCurrency(r.amount) },
    { key: 'paid_by',      header: 'Paid By' },
    { key: 'receipt_ref',  header: 'Receipt' },
    {
      key: 'actions', header: '',
      render: (r: Expense) => (
        <div className="flex gap-2">
          <button onClick={() => { setEditRow(r); reset({ ...r, expense_date: r.expense_date?.slice(0,10) }); setShowForm(true) }} className="text-gray-400 hover:text-primary-600"><Pencil size={14} /></button>
          <button onClick={() => { if (confirm('Delete?')) deleteMutation.mutate(r.id) }} className="text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Manual Expenses</h1>
        <button onClick={() => { setEditRow(null); reset({ expense_date: new Date().toISOString().slice(0,10) }); setShowForm(true) }} className="btn-primary"><Plus size={15} /> Add Expense</button>
      </div>

      <div className="flex gap-3 items-center justify-between">
        <input type="month" className="form-input w-44" value={month} onChange={(e) => { setMonth(e.target.value); setPage(1) }} />
        {month && (
          <div className="card py-2 px-4">
            <span className="text-xs text-gray-500">Period Total: </span>
            <span className="font-bold">{formatCurrency(totalAmount)}</span>
          </div>
        )}
      </div>

      {isLoading ? <LoadingSpinner /> : (
        <>
          <Table columns={columns as any} data={data?.data ?? []} />
          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page}</span>
            <button disabled={(data?.data?.length ?? 0) < 50} onClick={() => setPage(p => p + 1)} className="btn-secondary">Next</button>
          </div>
        </>
      )}

      <Modal title={editRow ? 'Edit Expense' : 'Add Expense'} open={showForm} onClose={() => { setShowForm(false); reset() }}>
        <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="space-y-4">
          <div>
            <label className="form-label">Category</label>
            <input className="form-input" {...register('category', { required: 'Required' })} />
          </div>
          <div>
            <label className="form-label">Description</label>
            <input className="form-input" {...register('description')} />
          </div>
          <div>
            <label className="form-label">Amount</label>
            <input type="number" step="0.01" className="form-input" {...register('amount', { required: 'Required', valueAsNumber: true })} />
          </div>
          <div>
            <label className="form-label">Date</label>
            <input type="date" className="form-input" {...register('expense_date', { required: 'Required' })} />
          </div>
          <div>
            <label className="form-label">Paid By</label>
            <input className="form-input" {...register('paid_by')} />
          </div>
          <div>
            <label className="form-label">Receipt Ref</label>
            <input className="form-input" {...register('receipt_ref')} />
          </div>
          <div className="flex justify-end gap-2">
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
