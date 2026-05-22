import { useMemo, useState, useDeferredValue, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { generateBillingText, encodeWhatsAppText } from '@/lib/billingGenerator'
import { DollarSign, Eye, FileText, Copy, Send, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'

interface Debtor {
  client_name: string
  phone_number?: string
  total_outstanding?: number
  balance?: number
  row_count?: number
  unpaid_jobs?: number
  last_activity?: string
}

interface LedgerItem {
  id: string
  service_name: string
  service_date?: string
  due_date?: string
  amount_charged: number
  paid_amount: number
  balance: number
  outstanding?: number
  payment_status: string
  notes?: string
}

interface LedgerPayment {
  id: string
  service_job_id?: string
  billing_row_id?: string
  payment_amount?: number
  amount?: number
  payment_method?: string
  reference_no?: string
  payment_date?: string
  payment_note?: string
  notes?: string
  applied_by_name?: string
  new_status?: string
  is_reversed?: boolean
  created_at?: string
}

interface DebtorLedger {
  client_name: string
  items: LedgerItem[]
  item_count: number
  total_outstanding: number
  payment_history: LedgerPayment[]
}

interface WhatsAppContact {
  client_name: string
  client_id?: string
  phone_number: string
  normalized_phone_number: string
  source: string | null
  requires_manual_entry: boolean
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
  const [showPhoneModal, setShowPhoneModal] = useState(false)
  const [manualPhoneNumber, setManualPhoneNumber] = useState('')
  const [billText, setBillText] = useState('')
  const [allocationMode, setAllocationMode] = useState<'auto' | 'manual'>('auto')
  const [manualAllocations, setManualAllocations] = useState<Record<string, number>>({})
  const deferredSearch = useDeferredValue(searchInput)

  const { data: debtors, isLoading, refetch } = useQuery<Debtor[]>({
    queryKey: ['debtors', deferredSearch],
    queryFn: () => api.get('/billing/debtors', { params: { search: deferredSearch || undefined } }).then((r) => r.data),
  })

  const { data: ledger, isLoading: detailsLoading } = useQuery<DebtorLedger>({
    queryKey: ['debtor-ledger', selectedRow?.client_name],
    queryFn: () =>
      api.get(`/billing/debtors/${encodeURIComponent(selectedRow!.client_name)}/ledger`).then((r) => r.data),
    enabled: !!selectedRow,
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { data: paymentReferencePreview } = useQuery<{ reference_no: string }>({
    queryKey: ['debtor-payment-reference-preview', selectedRow?.client_name],
    queryFn: () => api.get('/payments/reference').then((r) => r.data),
    enabled: !!selectedRow,
  })

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    getValues,
    formState: { errors },
  } = useForm<PaymentForm>()
  const paymentAmount = Number(watch('amount') || 0)

  const autoAllocations = useMemo(() => {
    if (!ledger?.items?.length || paymentAmount <= 0) return [] as { billing_row_id: string; amount: number }[]
    let remaining = paymentAmount
    const allocations: { billing_row_id: string; amount: number }[] = []
    for (const item of ledger.items) {
      if (remaining <= 0) break
      const amount = Math.min(Number(item.balance || item.outstanding || 0), remaining)
      if (amount > 0) {
        allocations.push({ billing_row_id: item.id, amount })
        remaining -= amount
      }
    }
    return allocations
  }, [ledger?.items, paymentAmount])

  const manualAllocatedTotal = useMemo(() => {
    return Object.values(manualAllocations).reduce((sum, amount) => sum + Number(amount || 0), 0)
  }, [manualAllocations])

  const applyMutation = useMutation({
    mutationFn: (values: PaymentForm) => {
      const payload: any = {
        ...values,
        mode: allocationMode,
      }
      if (allocationMode === 'manual') {
        payload.allocations = Object.entries(manualAllocations)
          .filter(([, amount]) => Number(amount) > 0)
          .map(([billing_row_id, amount]) => ({ billing_row_id, amount: Number(amount) }))
      }
      return api.post(`/billing/debtors/${encodeURIComponent(selectedRow!.client_name)}/apply-payment`, payload)
    },
    onSuccess: () => {
      toast.success('Payment applied')
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['debtor-ledger'] })
      qc.invalidateQueries({ queryKey: ['billing'] })
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
      qc.invalidateQueries({ queryKey: ['system-status'] })
      setSelectedRow(null)
      setAllocationMode('auto')
      setManualAllocations({})
      reset()
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Payment failed'),
  })

  useEffect(() => {
    if (!selectedRow) return
    if (!paymentReferencePreview?.reference_no) return
    if (getValues('reference_no')) return
    setValue('reference_no', paymentReferencePreview.reference_no)
  }, [paymentReferencePreview, selectedRow, setValue, getValues])

  const whatsappMutation = useMutation({
    mutationFn: (phoneNumber: string) =>
      api.post(`/billing/debtors/${encodeURIComponent(selectedRow!.client_name)}/whatsapp`, {
        phone_number: phoneNumber,
      }),
    onSuccess: () => {
      toast.success('WhatsApp send tracked')
      qc.invalidateQueries({ queryKey: ['debtors'] })
    },
  })

  const totalOutstanding = debtors?.reduce((s, r) => s + Number(r.total_outstanding ?? r.balance ?? 0), 0) ?? 0

  const handleViewDetails = (debtor: Debtor) => {
    navigate(`/debtors/${encodeURIComponent(debtor.client_name)}`, { state: { debtor } })
  }

  const handleGenerateBill = async () => {
    if (!selectedRow || !ledger) return
    const billItems = (ledger.items || []).map((item) => ({
      ...item,
      service_date: item.service_date || '',
      outstanding: Number(item.balance || item.outstanding || 0),
    }))
    const generated = generateBillingText(
      selectedRow.client_name,
      billItems,
      Number(ledger.total_outstanding || selectedRow.total_outstanding || selectedRow.balance || 0),
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
    } catch {
      toast.error('Failed to copy to clipboard')
    }
  }

  const handleSendWhatsApp = async () => {
    if (!selectedRow || !billText) {
      toast.error('Generate the bill before sending')
      return
    }

    try {
      const response = await api.get<WhatsAppContact>(`/billing/debtors/${encodeURIComponent(selectedRow.client_name)}/whatsapp-contact`)
      const contact = response.data

      if (contact.requires_manual_entry || !contact.normalized_phone_number) {
        setManualPhoneNumber('')
        setShowPhoneModal(true)
        return
      }

      await openWhatsApp(contact.phone_number, contact.normalized_phone_number)
    } catch (error: any) {
      toast.error(error?.response?.data?.detail ?? 'Failed to resolve WhatsApp number')
    }
  }

  const openWhatsApp = async (phoneNumber: string, normalizedPhoneNumber?: string) => {
    const normalized = normalizedPhoneNumber || phoneNumber.replace(/\D+/g, '')
    if (!normalized) {
      toast.error('Failed to send')
      return
    }

    toast.success(`Using WhatsApp number: ${phoneNumber}`)

    const encodedText = encodeWhatsAppText(billText)
    const whatsappUrl = `https://wa.me/${normalized}?text=${encodedText}`
    const popup = window.open(whatsappUrl, '_blank')

    if (!popup) {
      toast.error('Failed to send')
      return
    }

    toast.success('Sent to WhatsApp')

    whatsappMutation.mutate(phoneNumber)
    setShowPhoneModal(false)
  }

  const handleConfirmPhoneAndSend = async () => {
    const trimmedPhone = manualPhoneNumber.trim()
    if (!trimmedPhone) {
      toast.error('Please enter a phone number')
      return
    }
    await openWhatsApp(trimmedPhone)
  }

  const onSubmitPayment = (values: PaymentForm) => {
    if (allocationMode === 'manual') {
      const positiveAllocations = Object.values(manualAllocations).filter((x) => Number(x) > 0)
      if (!positiveAllocations.length) {
        toast.error('Enter at least one manual allocation amount')
        return
      }
      if (manualAllocatedTotal - Number(values.amount || 0) > 1e-6) {
        toast.error('Total manual allocations cannot exceed payment amount')
        return
      }
    }
    applyMutation.mutate(values)
  }

  const columns = [
    { key: 'client_name', header: 'Client', render: (r: Debtor) => <span className="font-medium">{r.client_name}</span> },
    { key: 'phone_number', header: 'Phone', render: (r: Debtor) => r.phone_number || '-' },
    {
      key: 'total_outstanding',
      header: 'Outstanding',
      render: (r: Debtor) => <span className="font-semibold text-red-600">{formatCurrency(Number(r.total_outstanding ?? r.balance ?? 0), currency)}</span>,
    },
    { key: 'unpaid_jobs', header: 'Unpaid Jobs', render: (r: Debtor) => Number(r.row_count ?? r.unpaid_jobs ?? 0) },
    { key: 'last_activity', header: 'Last Activity', render: (r: Debtor) => (r.last_activity ? String(r.last_activity).slice(0, 10) : '-') },
    {
      key: 'actions',
      header: 'Actions',
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
            onClick={() => {
              setSelectedRow(r)
              setAllocationMode('auto')
              setManualAllocations({})
              reset({
                payment_date: new Date().toISOString().slice(0, 10),
                amount: Number(r.total_outstanding ?? r.balance ?? 0),
                reference_no: paymentReferencePreview?.reference_no || '',
              })
            }}
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
          placeholder="Search by client, phone, or service..."
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

      {selectedRow && !showBillModal && (
        <Modal
          title={`Apply Payment - ${selectedRow.client_name}`}
          open={!!selectedRow}
          onClose={() => {
            setSelectedRow(null)
            setAllocationMode('auto')
            setManualAllocations({})
            reset()
          }}
        >
          <div className="mb-4 p-3 bg-gray-50 rounded-lg text-sm space-y-2">
            <p><span className="font-medium">Client:</span> {selectedRow.client_name}</p>
            <p><span className="font-medium">Outstanding Jobs:</span> {ledger?.item_count ?? selectedRow.row_count ?? 0}</p>
            <p>
              <span className="font-medium">Outstanding Balance:</span>{' '}
              <span className="text-red-600 font-semibold">{formatCurrency(Number(ledger?.total_outstanding ?? selectedRow.total_outstanding ?? selectedRow.balance ?? 0), currency)}</span>
            </p>
          </div>

          <div className="flex gap-2 mb-4">
            <button
              onClick={handleGenerateBill}
              disabled={detailsLoading}
              className="btn-secondary py-2 px-3 text-sm flex items-center gap-2 flex-1"
            >
              <FileText size={16} /> {detailsLoading ? 'Loading...' : 'Generate Bill'}
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

          <form onSubmit={handleSubmit(onSubmitPayment)} className="space-y-4">
            <div>
              <label className="form-label">Amount</label>
              <input
                type="number"
                step="0.01"
                className="form-input"
                {...register('amount', { required: 'Required', valueAsNumber: true, min: { value: 0.01, message: 'Must be > 0' } })}
              />
              {errors.amount && <p className="text-xs text-red-500">{errors.amount.message}</p>}
            </div>

            <div>
              <label className="form-label">Allocation Mode</label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  className={`btn-secondary ${allocationMode === 'auto' ? 'ring-2 ring-primary-500' : ''}`}
                  onClick={() => setAllocationMode('auto')}
                >
                  Auto (oldest first)
                </button>
                <button
                  type="button"
                  className={`btn-secondary ${allocationMode === 'manual' ? 'ring-2 ring-primary-500' : ''}`}
                  onClick={() => setAllocationMode('manual')}
                >
                  Manual
                </button>
              </div>
            </div>

            {allocationMode === 'auto' && (
              <div className="rounded-lg border border-gray-200 p-3 text-sm space-y-2">
                <p className="font-medium">Auto Allocation Preview</p>
                {autoAllocations.length === 0 ? (
                  <p className="text-gray-500">Enter amount to preview allocation.</p>
                ) : (
                  autoAllocations.map((item) => {
                    const invoice = ledger?.items.find((row) => row.id === item.billing_row_id)
                    return (
                      <div key={item.billing_row_id} className="flex justify-between gap-4">
                        <span className="text-gray-700">{invoice?.service_name || item.billing_row_id}</span>
                        <span className="font-medium">{formatCurrency(item.amount, currency)}</span>
                      </div>
                    )
                  })
                )}
              </div>
            )}

            {allocationMode === 'manual' && (
              <div className="rounded-lg border border-gray-200 p-3 text-sm space-y-2 max-h-56 overflow-y-auto">
                <p className="font-medium">Manual Allocations</p>
                {(ledger?.items || []).map((item) => (
                  <div key={item.id} className="grid grid-cols-12 gap-2 items-center">
                    <div className="col-span-6 truncate" title={item.service_name}>{item.service_name}</div>
                    <div className="col-span-3 text-xs text-gray-500">Bal: {formatCurrency(Number(item.balance || item.outstanding || 0), currency)}</div>
                    <div className="col-span-3">
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        className="form-input"
                        value={manualAllocations[item.id] ?? ''}
                        onChange={(e) => {
                          const next = Number(e.target.value || 0)
                          setManualAllocations((prev) => ({ ...prev, [item.id]: next }))
                        }}
                      />
                    </div>
                  </div>
                ))}
                <div className="pt-2 border-t border-gray-200 flex justify-between">
                  <span>Allocated Total</span>
                  <span className={manualAllocatedTotal > paymentAmount ? 'text-red-600 font-semibold' : 'font-medium'}>
                    {formatCurrency(manualAllocatedTotal, currency)}
                  </span>
                </div>
              </div>
            )}

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

            {!!ledger?.payment_history?.length && (
              <div className="rounded-lg border border-gray-200 p-3 text-sm max-h-44 overflow-y-auto">
                <p className="font-medium mb-2">Recent Payment History</p>
                <div className="space-y-2">
                  {ledger.payment_history.slice(0, 20).map((p) => (
                    <div key={p.id} className="flex justify-between gap-3 text-xs border-b border-gray-100 pb-1.5 last:border-b-0">
                      <div>
                        <p className="font-medium text-gray-700">{p.reference_no || p.id.slice(0, 8)}</p>
                        <p className="text-gray-500">{String(p.payment_date || p.created_at || '').slice(0, 19).replace('T', ' ')} • {p.payment_method || 'payment'}{p.applied_by_name ? ` • ${p.applied_by_name}` : ''}</p>
                        {(p.payment_note || p.notes) && <p className="text-gray-500">{p.payment_note || p.notes}</p>}
                      </div>
                      <span className={`font-medium ${Number(p.payment_amount ?? p.amount ?? 0) < 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
                        {formatCurrency(Number(p.payment_amount ?? p.amount ?? 0), currency)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setSelectedRow(null)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={applyMutation.isPending || detailsLoading}>
                {applyMutation.isPending ? 'Processing...' : 'Apply Payment'}
              </button>
            </div>
          </form>
        </Modal>
      )}

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

      {showPhoneModal && (
        <Modal
          title="Enter Phone Number"
          open={showPhoneModal}
          onClose={() => setShowPhoneModal(false)}
        >
          <div className="space-y-4">
            <p className="text-sm text-gray-600">No saved phone number was found for this client. Enter one to send now and save it for next time.</p>
            <input
              type="text"
              placeholder="e.g. +2348012345678"
              value={manualPhoneNumber}
              onChange={(e) => setManualPhoneNumber(e.target.value)}
              className="form-input w-full"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setShowPhoneModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={handleConfirmPhoneAndSend}
                disabled={whatsappMutation.isPending}
              >
                {whatsappMutation.isPending ? 'Sending...' : 'Send'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
