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

interface Allowance {
  id: string
  staff_name: string
  allowance_type: string
  amount: number
  allowance_date: string
  approved_by: string
}

interface FormValues {
  staff_name: string
  allowance_type: string
  amount: number
  allowance_date: string
  approved_by: string
  notes: string
}

export default function Allowances() {
  const qc = useQueryClient()
  const [month, setMonth] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<Allowance | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['allowances', month, page],
    queryFn: () =>
      api.get('/allowances', { params: { month: month || undefined, page, page_size: 50 } }).then((r) => r.data),
  })

  const { register, handleSubmit, reset } = useForm<FormValues>()

  const saveMutation = useMutation({
    mutationFn: (v: FormValues) =>
      editRow ? api.put(`/allowances/${editRow.id}`, v) : api.post('/allowances', v),
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['allowances'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false); setEditRow(null); reset()
    },
    onError: () => toast.error('Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/allowances/${id}`),
    onSuccess: () => {
      toast.success('Deleted')
      qc.invalidateQueries({ queryKey: ['allowances'] })
    },
  })

  const totalAmount = data?.data?.reduce((s: number, r: Allowance) => s + Number(r.amount), 0) ?? 0

  const columns = [
    { key: 'allowance_date', header: 'Date', render: (r: Allowance) => formatDate(r.allowance_date) },
    { key: 'staff_name',     header: 'Staff' },
    { key: 'allowance_type', header: 'Type' },
    { key: 'amount',         header: 'Amount', render: (r: Allowance) => formatCurrency(r.amount) },
    { key: 'approved_by',    header: 'Approved By' },
    {
      key: 'actions', header: '',
      render: (r: Allowance) => (
        <div className="flex gap-2">
          <button onClick={() => { setEditRow(r); reset({ ...r, allowance_date: r.allowance_date?.slice(0,10) }); setShowForm(true) }} className="text-gray-400 hover:text-primary-600"><Pencil size={14} /></button>
          <button onClick={() => { if (confirm('Delete?')) deleteMutation.mutate(r.id) }} className="text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Allowances</h1>
        <button onClick={() => { setEditRow(null); reset({ allowance_date: new Date().toISOString().slice(0,10) }); setShowForm(true) }} className="btn-primary"><Plus size={15} /> Add Allowance</button>
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

      {isLoading ? <LoadingSpinner /> : <Table columns={columns as any} data={data?.data ?? []} />}

      <Modal title={editRow ? 'Edit Allowance' : 'Add Allowance'} open={showForm} onClose={() => { setShowForm(false); reset() }}>
        <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="space-y-4">
          <div>
            <label className="form-label">Staff Name</label>
            <input className="form-input" {...register('staff_name', { required: 'Required' })} />
          </div>
          <div>
            <label className="form-label">Allowance Type</label>
            <select className="form-input" {...register('allowance_type', { required: 'Required' })}>
              <option value="">Select…</option>
              <option value="transport">Transport</option>
              <option value="meal">Meal</option>
              <option value="airtime">Airtime</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div>
            <label className="form-label">Amount</label>
            <input type="number" step="0.01" className="form-input" {...register('amount', { required: 'Required', valueAsNumber: true })} />
          </div>
          <div>
            <label className="form-label">Date</label>
            <input type="date" className="form-input" {...register('allowance_date', { required: 'Required' })} />
          </div>
          <div>
            <label className="form-label">Approved By</label>
            <input className="form-input" {...register('approved_by')} />
          </div>
          <div>
            <label className="form-label">Notes</label>
            <textarea className="form-input" rows={2} {...register('notes')} />
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
