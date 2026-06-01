import { useMemo, useState, useDeferredValue, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import { buildIdempotencyKey } from '@/lib/idempotency'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { generateBillingText, encodeWhatsAppText } from '@/lib/billingGenerator'
import { resolveImei } from '@/lib/imei'
import { DollarSign, FileText, Copy, Send, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'

interface Debtor {
  debtor_key?: string
  client_name: string
  phone_number?: string
  total_outstanding: number
  unpaid_jobs: number
  last_activity_date?: string
  last_payment_date?: string
  last_whatsapp_sent_at?: string
  whatsapp_sent_count?: number
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
  imei?: string
  device_imei?: string
  imei_number?: string
  source_imei?: string
  imei1?: string
  imei_2?: string
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
  balance_before?: number
  balance_after?: number
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

interface DebtorServicesResponse {
  items: LedgerItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
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
  const qc = useQueryClient()
  const [selectedRow, setSelectedRow] = useState<Debtor | null>(null)
  const [expandedRow, setExpandedRow] = useState<Debtor | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [showBillModal, setShowBillModal] = useState(false)
  const [showPhoneModal, setShowPhoneModal] = useState(false)
  const [manualPhoneNumber, setManualPhoneNumber] = useState('')
  const [billText, setBillText] = useState('')
  const [allocationMode, setAllocationMode] = useState<'auto' | 'manual'>('auto')
  const [manualAllocations, setManualAllocations] = useState<Record<string, number>>({})
  const [serviceSearch, setServiceSearch] = useState('')
  const [serviceStatus, setServiceStatus] = useState('')
  const deferredSearch = useDeferredValue(searchInput)

  const { data: debtors, isLoading, refetch } = useQuery<Debtor[]>({
    queryKey: ['debtors', deferredSearch],
    queryFn: () => api.get('/billing/debtors', { params: { search: deferredSearch || undefined } }).then((r) => r.data),
  })

  const { data: ledger, isLoading: detailsLoading } = useQuery<DebtorLedger>({
    queryKey: ['debtor-ledger', selectedRow?.client_name],
    queryFn: () =>
      api.get(`/billing/debtors/${encodeURIComponent(selectedRow!.client_name)}/ledger`, {
        params: { phone_number: selectedRow?.phone_number || undefined },
      }).then((r) => r.data),
    enabled: !!selectedRow,
  })

  const { data: expandedLedger, isLoading: expandedLoading } = useQuery<DebtorLedger>({
    queryKey: ['debtor-ledger-expanded', expandedRow?.client_name, expandedRow?.phone_number],
    queryFn: () =>
      api.get(`/billing/debtors/${encodeURIComponent(expandedRow!.client_name)}/ledger`, {
        params: { phone_number: expandedRow?.phone_number || undefined },
      }).then((r) => r.data),
    enabled: !!expandedRow,
  })

  const { data: debtorServices, isLoading: debtorServicesLoading } = useQuery<DebtorServicesResponse>({
    queryKey: ['debtor-services', expandedRow?.client_name, expandedRow?.phone_number, serviceSearch, serviceStatus],
    queryFn: () =>
      api.get(`/billing/debtors/${encodeURIComponent(expandedRow!.client_name)}/services`, {
        params: {
          phone_number: expandedRow?.phone_number || undefined,
          search: serviceSearch.trim() || undefined,
          payment_status: serviceStatus || undefined,
          page: 1,
          page_size: 120,
        },
      }).then((r) => r.data),
    enabled: !!expandedRow,
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
        idempotency_key: buildIdempotencyKey('debtor-payment-apply'),
          debtor_phone_number: selectedRow?.phone_number || undefined,
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
      qc.invalidateQueries({ queryKey: ['debtor-services'] })
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

  const totalOutstanding = debtors?.reduce((s, r) => s + Number(r.total_outstanding || 0), 0) ?? 0

  const handleGenerateBill = async () => {
    if (!selectedRow || !ledger) return
    const billItems = (ledger.items || []).map((item) => ({
      ...item,
      service_date: item.service_date || '',
      outstanding: Number(item.balance || item.outstanding || 0),
      imei: resolveImei(item) || undefined,
    }))
    const generated = generateBillingText(
      selectedRow.client_name,
      billItems,
        Number(ledger.total_outstanding || selectedRow.total_outstanding || 0),
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

    const openApplyPaymentModal = (r: Debtor) => {
      setSelectedRow(r)
      setAllocationMode('auto')
      setManualAllocations({})
      reset({
        payment_date: new Date().toISOString().slice(0, 10),
        amount: Number(r.total_outstanding || 0),
        reference_no: paymentReferencePreview?.reference_no || '',
      })
    }

    const toggleExpand = (r: Debtor) => {
      if (expandedRow?.debtor_key && expandedRow.debtor_key === r.debtor_key) {
        setExpandedRow(null)
        return
      }
      setExpandedRow(r)
      setServiceSearch('')
      setServiceStatus('')
    }

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

        {isLoading ? <LoadingSpinner /> : (
          <div className="overflow-x-auto rounded-xl border" style={{ borderColor: '#d4af37' }}>
            <table className="min-w-full text-sm">
              <thead style={{ background: '#000000' }}>
                <tr>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Client Name</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Phone Number</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Total Outstanding</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Unpaid Jobs</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Last Activity Date</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Last Payment Date</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Last WhatsApp Sent</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">WhatsApp Send Count</th>
                  <th className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white">
                {(debtors ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-gray-500">No records found</td>
                  </tr>
                ) : (debtors ?? []).map((r) => {
                  const isExpanded = !!expandedRow?.debtor_key && expandedRow.debtor_key === r.debtor_key
                  return (
                    <>
                      <tr
                        key={r.debtor_key || `${r.client_name}-${r.phone_number || ''}`}
                        className="group cursor-pointer transition-colors hover:bg-[#fff9e7]"
                        style={{ borderTop: '1px solid #f1e7bf' }}
                        onClick={() => toggleExpand(r)}
                      >
                        <td className="px-4 py-3 whitespace-nowrap font-medium">{r.client_name}</td>
                        <td className="px-4 py-3 whitespace-nowrap">{r.phone_number || '-'}</td>
                        <td className="px-4 py-3 whitespace-nowrap font-semibold text-red-600">{formatCurrency(Number(r.total_outstanding || 0), currency)}</td>
                        <td className="px-4 py-3 whitespace-nowrap">{Number(r.unpaid_jobs || 0)}</td>
                        <td className="px-4 py-3 whitespace-nowrap">{r.last_activity_date ? String(r.last_activity_date).slice(0, 10) : '-'}</td>
                        <td className="px-4 py-3 whitespace-nowrap">{r.last_payment_date ? String(r.last_payment_date).slice(0, 10) : '-'}</td>
                        <td className="px-4 py-3 whitespace-nowrap">{r.last_whatsapp_sent_at ? String(r.last_whatsapp_sent_at).slice(0, 19).replace('T', ' ') : '-'}</td>
                        <td className="px-4 py-3 whitespace-nowrap">{Number(r.whatsapp_sent_count || 0)}</td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex gap-1">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                toggleExpand(r)
                              }}
                              className="btn-secondary py-1 px-2 text-xs"
                            >
                              View Services
                            </button>
                            <button
                              type="button"
                              title="Apply Payment"
                              onClick={(e) => {
                                e.stopPropagation()
                                openApplyPaymentModal(r)
                              }}
                              className="btn-primary py-1 px-2 text-xs"
                            >
                              <DollarSign size={13} />
                            </button>
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr style={{ borderTop: '1px solid #f1e7bf' }}>
                          <td colSpan={9} className="px-4 py-4 bg-[#fffdf8]">
                            {expandedLoading ? (
                              <LoadingSpinner />
                            ) : (
                              <div className="space-y-4">
                                <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm grid grid-cols-1 md:grid-cols-3 gap-3">
                                  <div>
                                    <p className="text-gray-500">Outstanding Total</p>
                                    <p className="font-semibold text-red-600">{formatCurrency(Number(expandedLedger?.total_outstanding || r.total_outstanding || 0), currency)}</p>
                                  </div>
                                  <div>
                                    <p className="text-gray-500">Recent WhatsApp Activity</p>
                                    <p>{r.last_whatsapp_sent_at ? String(r.last_whatsapp_sent_at).slice(0, 19).replace('T', ' ') : '-'}</p>
                                  </div>
                                  <div>
                                    <p className="text-gray-500">WhatsApp Send Count</p>
                                    <p>{Number(r.whatsapp_sent_count || 0)}</p>
                                  </div>
                                </div>

                                <div className="flex flex-wrap gap-2">
                                  <button type="button" onClick={() => openApplyPaymentModal(r)} className="btn-primary py-1.5 px-3 text-xs">Apply Payment</button>
                                  <button
                                    type="button"
                                    onClick={async () => {
                                      setSelectedRow(r)
                                      const ledgerData = expandedLedger
                                      const billItems = (ledgerData?.items || []).map((item) => ({
                                        ...item,
                                        service_date: item.service_date || '',
                                        outstanding: Number(item.balance || item.outstanding || 0),
                                        imei: resolveImei(item) || undefined,
                                      }))
                                      const generated = generateBillingText(
                                        r.client_name,
                                        billItems,
                                        Number(ledgerData?.total_outstanding || r.total_outstanding || 0),
                                        PAYMENT_DETAILS,
                                        currency
                                      )
                                      setBillText(generated)
                                      setShowBillModal(true)
                                    }}
                                    className="btn-secondary py-1.5 px-3 text-xs flex items-center gap-1"
                                  >
                                    <FileText size={13} /> Send Bill
                                  </button>
                                  <button
                                    type="button"
                                    onClick={async () => {
                                      const ledgerData = expandedLedger
                                      const billItems = (ledgerData?.items || []).map((item) => ({
                                        ...item,
                                        service_date: item.service_date || '',
                                        outstanding: Number(item.balance || item.outstanding || 0),
                                        imei: resolveImei(item) || undefined,
                                      }))
                                      const generated = generateBillingText(
                                        r.client_name,
                                        billItems,
                                        Number(ledgerData?.total_outstanding || r.total_outstanding || 0),
                                        PAYMENT_DETAILS,
                                        currency
                                      )
                                      await navigator.clipboard.writeText(generated)
                                      toast.success('Bill copied to clipboard')
                                    }}
                                    className="btn-secondary py-1.5 px-3 text-xs flex items-center gap-1"
                                  >
                                    <Copy size={13} /> Copy Bill
                                  </button>
                                </div>

                                <div className="rounded-lg border border-gray-200 bg-white p-3 space-y-2">
                                  <p className="font-medium text-sm">View Services</p>
                                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                                    <input
                                      value={serviceSearch}
                                      onChange={(e) => setServiceSearch(e.target.value)}
                                      placeholder="Search service, invoice id, IMEI, serial"
                                      className="form-input"
                                    />
                                    <select className="form-input" value={serviceStatus} onChange={(e) => setServiceStatus(e.target.value)}>
                                      <option value="">All statuses</option>
                                      <option value="PAID">PAID</option>
                                      <option value="UNPAID">UNPAID</option>
                                      <option value="PART PAYMENT">PART PAYMENT</option>
                                      <option value="RETURNED">RETURNED</option>
                                    </select>
                                    <div className="text-xs text-gray-500 flex items-center">{debtorServices?.total ?? 0} service(s)</div>
                                  </div>
                                  <div className="max-h-56 overflow-y-auto border border-gray-100 rounded">
                                    {debtorServicesLoading ? (
                                      <div className="p-3 text-sm text-gray-500">Loading services...</div>
                                    ) : !(debtorServices?.items?.length) ? (
                                      <div className="p-3 text-sm text-gray-500">No services found.</div>
                                    ) : (
                                      <table className="min-w-full text-xs">
                                        <thead className="bg-gray-50 border-b">
                                          <tr>
                                            <th className="px-2 py-2 text-left">Date</th>
                                            <th className="px-2 py-2 text-left">Service / Device</th>
                                            <th className="px-2 py-2 text-left">Status</th>
                                            <th className="px-2 py-2 text-right">Amount</th>
                                            <th className="px-2 py-2 text-right">Paid</th>
                                            <th className="px-2 py-2 text-right">Balance</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {debtorServices.items.map((item) => (
                                            <tr key={item.id} className="border-b">
                                              <td className="px-2 py-2">{String(item.service_date || '').slice(0, 10)}</td>
                                              <td className="px-2 py-2">
                                                <div className="font-medium">{item.service_name}</div>
                                                <div className="text-[11px] text-gray-500">IMEI: {resolveImei(item) || '—'}</div>
                                              </td>
                                              <td className="px-2 py-2">{item.payment_status}</td>
                                              <td className="px-2 py-2 text-right">{formatCurrency(Number(item.amount_charged || 0), currency)}</td>
                                              <td className="px-2 py-2 text-right">{formatCurrency(Number(item.paid_amount || 0), currency)}</td>
                                              <td className="px-2 py-2 text-right">{formatCurrency(Number(item.balance || item.outstanding || 0), currency)}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    )}
                                  </div>
                                </div>

                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                  <div className="rounded-lg border border-gray-200 bg-white p-3">
                                    <p className="font-medium text-sm mb-2">Outstanding Services</p>
                                    <div className="max-h-44 overflow-y-auto space-y-1 text-xs">
                                      {(expandedLedger?.items || []).map((item) => (
                                        <div key={item.id} className="flex justify-between border-b border-gray-100 pb-1">
                                          <span>
                                            <span className="block">{item.service_name}</span>
                                            <span className="block text-[11px] text-gray-500">IMEI: {resolveImei(item) || '—'}</span>
                                          </span>
                                          <span className="font-medium text-red-600">{formatCurrency(Number(item.balance || item.outstanding || 0), currency)}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                  <div className="rounded-lg border border-gray-200 bg-white p-3">
                                    <p className="font-medium text-sm mb-2">Recent Payment History</p>
                                    <div className="max-h-44 overflow-y-auto space-y-1 text-xs">
                                      {(expandedLedger?.payment_history || []).slice(0, 20).map((p) => (
                                        <div key={p.id} className="border-b border-gray-100 pb-1">
                                          <p className="font-medium text-gray-700">{p.reference_no || p.id.slice(0, 8)} • {formatCurrency(Number(p.payment_amount ?? p.amount ?? 0), currency)}</p>
                                          <p className="text-gray-500">{String(p.payment_date || p.created_at || '').slice(0, 19).replace('T', ' ')} • {p.applied_by_name || '-'}</p>
                                          <p className="text-gray-500">Note: {p.payment_note || p.notes || '-'} • Before: {formatCurrency(Number(p.balance_before || 0), currency)} • After: {formatCurrency(Number(p.balance_after || 0), currency)}</p>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

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
              <p><span className="font-medium">Outstanding Jobs:</span> {ledger?.item_count ?? selectedRow.unpaid_jobs ?? 0}</p>
            <p>
              <span className="font-medium">Outstanding Balance:</span>{' '}
                <span className="text-red-600 font-semibold">{formatCurrency(Number(ledger?.total_outstanding ?? selectedRow.total_outstanding ?? 0), currency)}</span>
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
                          <p className="text-gray-500">{p.payment_note || p.notes || '-'} • Before: {formatCurrency(Number(p.balance_before || 0), currency)} • After: {formatCurrency(Number(p.balance_after || 0), currency)}</p>
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
