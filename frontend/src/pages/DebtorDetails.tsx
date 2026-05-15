import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import Modal from '@/components/Modal'
import { formatCurrency } from '@/lib/utils'
import { generateBillingText, encodeWhatsAppText } from '@/lib/billingGenerator'
import { Copy, Send, Download, ArrowLeft } from 'lucide-react'
import toast from 'react-hot-toast'

interface DebtorItem {
  id: string
  service_name: string
  service_date: string
  amount_charged: number
  paid_amount: number
  outstanding: number
  payment_status: string
  description: string
}

interface DebtorDetails {
  client_name: string
  items: DebtorItem[]
  item_count: number
  total_outstanding: number
}

const PAYMENT_DETAILS = {
  accountNumber: '8168364881',
  bankName: 'OPAY (PAYCOM)',
  accountName: 'AKINPELUMI GEORGE AYOMIDE',
}

export default function DebtorDetails() {
  const { clientName } = useParams<{ clientName: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [showBillPreview, setShowBillPreview] = useState(false)
  const [billText, setBillText] = useState('')

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { data: debtor, isLoading } = useQuery<DebtorDetails>({
    queryKey: ['debtor-details', clientName],
    queryFn: () =>
      api.get(`/billing/debtors/${encodeURIComponent(clientName!)}/items`).then((r) => r.data),
    enabled: !!clientName,
  })

  const whatsappMutation = useMutation({
    mutationFn: () =>
      api.post(`/billing/debtors/${encodeURIComponent(clientName!)}/whatsapp`, {
        phone_number: '',
      }),
    onSuccess: () => {
      toast.success('WhatsApp send tracked')
      qc.invalidateQueries({ queryKey: ['debtors'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Failed to track WhatsApp send'),
  })

  const handleGenerateBill = () => {
    if (!debtor) return
    const generated = generateBillingText(
      debtor.client_name,
      debtor.items,
      debtor.total_outstanding,
      PAYMENT_DETAILS,
      currency
    )
    setBillText(generated)
    setShowBillPreview(true)
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
    const phoneNumber = debtor?.items[0]?.['client_phone'] || ''
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

  if (isLoading) return <LoadingSpinner />
  if (!debtor) return <div className="p-8">Debtor not found</div>

  return (
    <div className="p-8 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/debtors')}
          className="btn-secondary py-2 px-3 text-sm flex items-center gap-2"
        >
          <ArrowLeft size={16} /> Back
        </button>
        <div>
          <h1 className="text-2xl font-bold">{debtor.client_name}</h1>
          <p className="text-sm text-gray-500">{debtor.item_count} outstanding item(s)</p>
        </div>
      </div>

      {/* Total Outstanding Card */}
      <div className="card py-4 px-6">
        <p className="text-xs text-gray-500">Total Outstanding</p>
        <p className="text-3xl font-bold text-red-600">{formatCurrency(debtor.total_outstanding, currency)}</p>
      </div>

      {/* Actions */}
      <div className="flex gap-3 flex-wrap">
        <button
          onClick={handleGenerateBill}
          className="btn-primary py-2 px-4 text-sm flex items-center gap-2"
        >
          <Download size={16} /> Generate Bill
        </button>
        {billText && (
          <>
            <button
              onClick={handleCopyBill}
              className="btn-secondary py-2 px-4 text-sm flex items-center gap-2"
            >
              <Copy size={16} /> Copy Bill
            </button>
            <button
              onClick={handleSendWhatsApp}
              disabled={whatsappMutation.isPending}
              className="btn-primary py-2 px-4 text-sm flex items-center gap-2 bg-green-600 hover:bg-green-700"
            >
              <Send size={16} /> {whatsappMutation.isPending ? 'Sending…' : 'Send WhatsApp'}
            </button>
          </>
        )}
      </div>

      {/* Items Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Date</th>
                <th className="px-4 py-3 text-left font-medium">Description</th>
                <th className="px-4 py-3 text-right font-medium">Amount Charged</th>
                <th className="px-4 py-3 text-right font-medium">Paid</th>
                <th className="px-4 py-3 text-right font-medium">Outstanding</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {debtor.items.map((item) => (
                <tr key={item.id} className="border-b hover:bg-gray-50">
                  <td className="px-4 py-3">{new Date(item.service_date).toLocaleDateString()}</td>
                  <td className="px-4 py-3">{item.service_name}</td>
                  <td className="px-4 py-3 text-right">{formatCurrency(item.amount_charged, currency)}</td>
                  <td className="px-4 py-3 text-right">{formatCurrency(item.paid_amount, currency)}</td>
                  <td className="px-4 py-3 text-right font-semibold text-red-600">{formatCurrency(item.outstanding, currency)}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${
                      item.payment_status === 'UNPAID' ? 'bg-red-100 text-red-800' : 'bg-yellow-100 text-yellow-800'
                    }`}>
                      {item.payment_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bill Preview Modal */}
      {showBillPreview && (
        <Modal
          title="Bill Preview"
          open={showBillPreview}
          onClose={() => setShowBillPreview(false)}
        >
          <div className="bg-gray-50 p-4 rounded-lg whitespace-pre-wrap text-sm max-h-96 overflow-y-auto font-mono">
            {billText}
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button
              onClick={() => setShowBillPreview(false)}
              className="btn-secondary py-2 px-4"
            >
              Close
            </button>
            <button
              onClick={handleCopyBill}
              className="btn-primary py-2 px-4 flex items-center gap-2"
            >
              <Copy size={16} /> Copy
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
