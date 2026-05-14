import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import { useEffect, useDeferredValue } from 'react'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency, statusBadgeClass, statusLabel } from '@/lib/utils'
import { DollarSign } from 'lucide-react'
import toast from 'react-hot-toast'

interface Debtor {
  id: string
  row_type?: string
  client_name: string
  service_name: string
  total_amount: number
  amount_paid: number
  balance: number
  status: string
  due_date: string
  billing_row_id?: string
  row_count?: number
  source_row_ids?: string[]
}

interface PaymentForm {
  amount: number
  payment_method: string
  reference_no: string
  payment_date: string
  notes: string
}

export default function Debtors() {
  const qc = useQueryClient()
  const [selectedRow, setSelectedRow] = useState<Debtor | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const deferredSearch = useDeferredValue(searchInput)

  const { data: debtors, isLoading } = useQuery<Debtor[]>({
    queryKey: ['debtors', search],
    queryFn: () => api.get('/billing/debtors', { params: { search: search || undefined } }).then((r) => r.data),
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { register, handleSubmit, reset, formState: { errors } } = useForm<PaymentForm>()

  const applyMutation = useMutation({
    mutationFn: (values: PaymentForm) =>
      api.post('/payments', { billing_row_id: selectedRow!.billing_row_id || selectedRow!.id, ...values }),
    onSuccess: () => {
      toast.success('Payment applied')
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['billing'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setSelectedRow(null)
      reset()
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Payment failed'),
  })

  const totalOutstanding = debtors?.reduce((s, r) => s + Number(r.balance), 0) ?? 0

  const columns = [
    { key: 'client_name',  header: 'Client' },
    { key: 'service_name', header: 'Service' },
    { key: 'total_amount', header: 'Total',   render: (r: Debtor) => formatCurrency(r.total_amount, currency) },
    { key: 'amount_paid',  header: 'Paid',    render: (r: Debtor) => formatCurrency(r.amount_paid, currency) },
    { key: 'balance',      header: 'Balance', render: (r: Debtor) => <span className="font-semibold text-red-600">{formatCurrency(r.balance, currency)}</span> },
    { key: 'status',       header: 'Status',  render: (r: Debtor) => <span className={statusBadgeClass(r.status)}>{statusLabel(r.status)}</span> },
    { key: 'due_date',     header: 'Due',     render: (r: Debtor) => r.due_date ? new Date(r.due_date).toLocaleDateString() : '—' },
    {
      key: 'actions', header: '',
      render: (r: Debtor) => (
        <button
          onClick={() => { setSelectedRow(r); reset({ payment_date: new Date().toISOString().slice(0, 10) }) }}
          className="btn-primary py-1 px-2 text-xs"
        >
          <DollarSign size={13} /> Apply Payment
        </button>
      ),
    },
  ]

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Debtors</h1>
        <div className="card py-3 px-5 text-right">
          <p className="text-xs text-gray-500">Total Outstanding</p>
          <p className="text-2xl font-bold text-red-600">{formatCurrency(totalOutstanding, currency)}</p>
        </div>
      </div>

      <div className="card p-4">
        <input
          type="text"
          placeholder="Search by client name or service..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          className="form-input w-full"
        />
        {search && (
          <p className="text-xs text-gray-500 mt-2">
            Found {debtors?.length ?? 0} result{debtors?.length !== 1 ? 's' : ''}
          </p>
        )}
      </div>

      {isLoading ? <LoadingSpinner /> : <Table columns={columns as any} data={(debtors ?? []) as any} />}

      {selectedRow && (
        <Modal
          title={`Apply Payment — ${selectedRow.client_name}`}
          open={!!selectedRow}
          onClose={() => { setSelectedRow(null); reset() }}
        >
          <div className="mb-4 p-3 bg-gray-50 rounded-lg text-sm">
            <p><span className="font-medium">Service:</span> {selectedRow.service_name}</p>
            <p><span className="font-medium">Invoices in Group:</span> {selectedRow.row_count ?? 1}</p>
            <p><span className="font-medium">Outstanding:</span> <span className="text-red-600 font-semibold">{formatCurrency(selectedRow.balance, currency)}</span></p>
          </div>
          <form onSubmit={handleSubmit((v) => applyMutation.mutate(v))} className="space-y-4">
            <div>
              <label className="form-label">Amount</label>
              <input type="number" step="0.01" className="form-input"
                {...register('amount', { required: 'Required', valueAsNumber: true, min: { value: 0.01, message: 'Must be > 0' } })} />
              {errors.amount && <p className="text-xs text-red-500">{errors.amount.message}</p>}
            </div>
            <div>
              <label className="form-label">Payment Method</label>
              <select className="form-input" {...register('payment_method')}>
                <option value="cash">Cash</option>
                <option value="bank">Bank Transfer</option>
                <option value="mobile_money">Mobile Money</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label className="form-label">Reference No</label>
              <input className="form-input" {...register('reference_no')} />
            </div>
            <div>
              <label className="form-label">Payment Date</label>
              <input type="date" className="form-input" {...register('payment_date')} />
            </div>
            <div>
              <label className="form-label">Notes</label>
              <textarea className="form-input" rows={2} {...register('notes')} />
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setSelectedRow(null)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={applyMutation.isPending}>
                {applyMutation.isPending ? 'Processing…' : 'Apply Payment'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
