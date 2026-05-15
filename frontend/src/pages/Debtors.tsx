import { useState, useDeferredValue } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency, statusBadgeClass, statusLabel } from '@/lib/utils'
import { generateBillingText, encodeWhatsAppText } from '@/lib/billingGenerator'
import { DollarSign, Eye, FileText, Copy, Send, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'

interface Debtor {
  id: string
  billing_row_id?: string
  client_name: string
  phone_number?: string
  total_outstanding: number
  amount_charged?: number
  amount_paid?: number
  balance: number
  status: string
  due_date: string
  row_count?: number
  service_name: string
  source_row_ids?: string[]
}

interface PaymentForm {
  amount: number
  payment_method: string
  reference_no: string
  payment_date: string
  notes: string
}

const PAYMENT_DETAILS = {
  accountNumber: '8168364881',
  bankName: 'OPAY (PAYCOM)',
  accountName: 'AKINPELUMI GEORGE AYOMIDE',
}

export default function Debtors() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [selectedRow, setSelectedRow] = useState<Debtor | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [showBillModal, setShowBillModal] = useState(false)
  const [billText, setBillText] = useState('')
  const deferredSearch = useDeferredValue(searchInput)

  const { data: debtors, isLoading, refetch } = useQuery<Debtor[]>({
    queryKey: ['debtors', deferredSearch],
    queryFn: () => api.get('/billing/debtors', { params: { search: deferredSearch || undefined } }).then((r) => r.data),
  })

  const { data: debtor, isLoading: detailsLoading } = useQuery({
    queryKey: ['debtor-details', selectedRow?.client_name],
    queryFn: () =>
      api.get(`/billing/debtors/${encodeURIComponent(selectedRow!.client_name)}/items`).then((r) => r.data),
    enabled: !!selectedRow,
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

  const whatsappMutation = useMutation({
    mutationFn: () =>
      api.post(`/billing/debtors/${encodeURIComponent(selectedRow!.client_name)}/whatsapp`, {
        phone_number: selectedRow?.phone_number || '',
      }),
    onSuccess: () => {
      toast.success('WhatsApp send tracked')
      qc.invalidateQueries({ queryKey: ['debtors'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Failed to track WhatsApp send'),
  })

  const totalOutstanding = debtors?.reduce((s, r) => s + Number(r.balance), 0) ?? 0

  const handleViewDetails = (debtor: Debtor) => {
    navigate(`/debtors/${encodeURIComponent(debtor.client_name)}`, { state: { debtor } })
  }

  const handleGenerateBill = async () => {
    if (!selectedRow || !debtor) return
    const generated = generateBillingText(
      selectedRow.client_name,
      debtor.items || [],
      selectedRow.balance,
      PAYMENT_DETAILS,
      currency
    )
    setBillText(generated)
    setShowBillModal(true)
  }

  const handleCopyBill = async () => {
    try {
      await navigator.clipboard.writeText(billText)
      toast.success('Bill copied to clipboard')
    } catch (err) {
      toast.error('Failed to copy to clipboard')
    }
  }

  const handleSendWhatsApp = async () => {
    const phoneNumber = selectedRow?.phone_number || ''
    if (!phoneNumber) {
      toast.error('Phone number not available')
      return
    }

    const encodedText = encodeWhatsAppText(billText)
    const whatsappUrl = `https://wa.me/${phoneNumber}?text=${encodedText}`

    // Track the send
    await whatsappMutation.mutateAsync()

    // Open WhatsApp
    window.open(whatsappUrl, '_blank')
  }

  const columns = [
    { key: 'client_name', header: 'Client', render: (r: Debtor) => <span className="font-medium">{r.client_name}</span> },
    { key: 'row_count', header: 'Items', render: (r: Debtor) => r.row_count ?? 1 },
    { key: 'amount_charged', header: 'Total Billed', render: (r: Debtor) => formatCurrency(r.amount_charged ?? 0, currency) },
    { key: 'amount_paid', header: 'Paid', render: (r: Debtor) => formatCurrency(r.amount_paid ?? 0, currency) },
    { key: 'balance', header: 'Outstanding', render: (r: Debtor) => <span className="font-semibold text-red-600">{formatCurrency(r.balance, currency)}</span> },
    { key: 'status', header: 'Status', render: (r: Debtor) => <span className={statusBadgeClass(r.status)}>{statusLabel(r.status)}</span> },
    {
      key: 'actions', header: 'Actions',
      render: (r: Debtor) => (
        <div className="flex gap-1">
          <button
            title="View Details"
            onClick={() => handleViewDetails(r)}
            className="btn-secondary py-1 px-2 text-xs"
          >
            <Eye size={13} />
          </button>
          <button
            title="Apply Payment"
            onClick={() => { setSelectedRow(r); reset({ payment_date: new Date().toISOString().slice(0, 10) }) }}
            className="btn-primary py-1 px-2 text-xs"
          >
            <DollarSign size={13} />
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Debtors</h1>
        <div className="flex items-center gap-3">
          <button
            onClick={() => refetch()}
            disabled={isLoading}
            className="btn-secondary py-2 px-3 text-sm flex items-center gap-2"
          >
            <RefreshCw size={16} /> Refresh
          </button>
          <div className="card py-3 px-5 text-right">
            <p className="text-xs text-gray-500">Total Outstanding</p>
            <p className="text-2xl font-bold text-red-600">{formatCurrency(totalOutstanding, currency)}</p>
          </div>
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
        {searchInput && (
          <p className="text-xs text-gray-500 mt-2">
            Found {debtors?.length ?? 0} result{debtors?.length !== 1 ? 's' : ''}
          </p>
        )}
      </div>

      {isLoading ? <LoadingSpinner /> : <Table columns={columns as any} data={(debtors ?? []) as any} />}

      {/* Apply Payment Modal */}
      {selectedRow && !showBillModal && (
        <Modal
          title={`Apply Payment — ${selectedRow.client_name}`}
          open={!!selectedRow}
          onClose={() => { setSelectedRow(null); reset() }}
        >
          <div className="mb-4 p-3 bg-gray-50 rounded-lg text-sm space-y-2">
            <p><span className="font-medium">Client:</span> {selectedRow.client_name}</p>
            <p><span className="font-medium">Outstanding Items:</span> {selectedRow.row_count ?? 1}</p>
            <p><span className="font-medium">Outstanding Balance:</span> <span className="text-red-600 font-semibold">{formatCurrency(selectedRow.balance, currency)}</span></p>
          </div>

          <div className="flex gap-2 mb-4">
            <button
              onClick={handleGenerateBill}
              disabled={detailsLoading}
              className="btn-secondary py-2 px-3 text-sm flex items-center gap-2 flex-1"
            >
              <FileText size={16} /> {detailsLoading ? 'Loading…' : 'Generate Bill'}
            </button>
            {billText && (
              <>
                <button
                  onClick={handleCopyBill}
                  className="btn-secondary py-2 px-3 text-sm flex items-center gap-2"
                  title="Copy bill to clipboard"
                >
                  <Copy size={16} />
                </button>
                <button
                  onClick={handleSendWhatsApp}
                  disabled={whatsappMutation.isPending}
                  className="btn-primary py-2 px-3 text-sm flex items-center gap-2 bg-green-600 hover:bg-green-700"
                >
                  <Send size={16} />
                </button>
              </>
            )}
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

      {/* Bill Preview Modal */}
      {showBillModal && billText && (
        <Modal
          title="Bill Preview"
          open={showBillModal}
          onClose={() => setShowBillModal(false)}
        >
          <div className="bg-gray-50 p-4 rounded-lg whitespace-pre-wrap text-xs max-h-96 overflow-y-auto font-mono">
            {billText}
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button
              onClick={() => setShowBillModal(false)}
              className="btn-secondary py-2 px-4"
            >
              Close
            </button>
            <button
              onClick={handleCopyBill}
              className="btn-secondary py-2 px-4 flex items-center gap-2"
            >
              <Copy size={16} /> Copy
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
