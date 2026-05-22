import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router-dom'
import {
  Calendar, ChevronLeft, ChevronRight,
  Copy, CreditCard, MessageCircle, Pencil, Plus,
  RotateCcw, Search, Trash2, X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import Modal from '@/components/Modal'
import { formatCurrency, statusBadgeClass, statusLabel } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'

// ─── Types ────────────────────────────────────────────────────────────────────

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

type FlatBillingEntry =
  | { kind: 'separator'; key: string; group: BillingGroup }
  | { kind: 'item'; key: string; group: BillingGroup; row: BillingRow }

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

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

function formatMonthLabel(monthStr: string): string {
  const [year, m] = monthStr.split('-').map(Number)
  return new Date(year, m - 1, 1).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  })
}

function labelForDate(dateStr: string): string {
  if (!dateStr || dateStr === 'Unknown') return 'Unknown Date'
  const d = new Date(`${dateStr}T00:00:00`)
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)

  const isSame = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()

  if (isSame(d, today)) return 'Today'
  if (isSame(d, yesterday)) return 'Yesterday'

  return d.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

function normalizePhone(raw?: string): string {
  if (!raw) return ''
  const digits = raw.replace(/\D/g, '')
  if (digits.startsWith('234')) return digits
  if (digits.startsWith('0') && digits.length === 11) return '234' + digits.slice(1)
  return digits
}

function parseApiError(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0]
    return String(first?.msg || first?.message || fallback)
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  if (error?.response?.status) return `Request failed (${error.response.status})`
  if (error?.message === 'Network Error') return 'Network/CORS error: cannot reach API'
  return String(error?.message || fallback)
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function Billing() {
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'

  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<BillingRow | null>(null)
  const [clientSearch, setClientSearch] = useState('')
  const [showClientDropdown, setShowClientDropdown] = useState(false)
  const [selectedClientId, setSelectedClientId] = useState('')
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())
  const [applyPayRow, setApplyPayRow] = useState<BillingRow | null>(null)
  const [applyPayAmount, setApplyPayAmount] = useState('')
  const [loadingEdit, setLoadingEdit] = useState(false)
  const [visibleCount, setVisibleCount] = useState(140)
  const [revealStartIndex, setRevealStartIndex] = useState<number | null>(null)
  const [revealEndIndex, setRevealEndIndex] = useState<number | null>(null)
  const [tableMotion, setTableMotion] = useState<'left' | 'right' | 'fade' | ''>('')
  const loadMoreRef = useRef<HTMLDivElement | null>(null)
  const motionTimerRef = useRef<number | null>(null)

  const page = Number(searchParams.get('page') || '1')
  const statusFilter = searchParams.get('payment_status') || ''
  const search = searchParams.get('search') || ''
  const dateFrom = searchParams.get('from_date') || ''
  const dateTo = searchParams.get('to_date') || ''
  const month = searchParams.get('month') || getDefaultMonth()
  const minAmount = searchParams.get('min_amount') || ''
  const maxAmount = searchParams.get('max_amount') || ''
  const returned = searchParams.get('is_return') || ''
  const paidState = searchParams.get('paid_state') || ''

  const [searchInput, setSearchInput] = useState(search)

  const { register, handleSubmit, reset, setValue, formState: { errors } } = useForm<FormValues>()

  useEffect(() => { setSearchInput(search) }, [search])

  useEffect(() => {
    const id = setTimeout(() => {
      const next = new URLSearchParams(searchParams)
      const trimmed = searchInput.trim()
      if (trimmed) {
        // Global search spans all services regardless of date window.
        next.set('search', trimmed)
        next.delete('from_date')
        next.delete('to_date')
        next.delete('month')
      } else {
        next.delete('search')
      }
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
          payment_status: statusFilter || undefined,
          search: search || undefined,
          from_date: dateFrom || undefined,
          to_date: dateTo || undefined,
          min_amount: minAmount || undefined,
          max_amount: maxAmount || undefined,
          is_return: returned === '' ? undefined : returned === 'true',
          paid_state: paidState || undefined,
        },
      }).then((r) => r.data),
    placeholderData: (prev) => prev,
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
    enabled: isAdmin,
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

      const quantity = Number(values.quantity)
      const unitPrice = Number(values.unit_price)
      const amountPaid = Number(values.amount_paid)
      const serviceExpense = Number(values.service_expense)

      if (!Number.isFinite(unitPrice) || unitPrice <= 0) {
        throw new Error('Unit Price must be greater than zero')
      }

      const normalizedClientName = String(values.client_name || '').trim()
      const normalizedServiceName = String(values.service_name || '').trim()
      if (!normalizedClientName || !normalizedServiceName) {
        throw new Error('Client Name and Service Name are required')
      }

      const payload = {
        ...values,
        client_name: normalizedClientName,
        service_name: normalizedServiceName,
        quantity: Number.isFinite(quantity) && quantity > 0 ? quantity : 1,
        unit_price: unitPrice,
        amount_paid: Number.isFinite(amountPaid) && amountPaid >= 0 ? amountPaid : 0,
        service_expense: Number.isFinite(serviceExpense) && serviceExpense >= 0 ? serviceExpense : 0,
        invoice_date: values.invoice_date?.trim() ? values.invoice_date : undefined,
        due_date: values.due_date?.trim() ? values.due_date : undefined,
        notes: values.notes?.trim() ? values.notes : undefined,
        client_id: clientId || undefined,
      }
      const finalPayload = { ...payload }

      // Staff can edit operational fields but not financial fields.
      if (editRow && !isAdmin) {
        delete (finalPayload as any).unit_price
        delete (finalPayload as any).amount_paid
        delete (finalPayload as any).service_expense
      }

      return editRow ? api.put(`/billing/${editRow.id}`, finalPayload) : api.post('/billing', payload)
    },
    retry: 1,
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      closeForm()
    },
    onError: (e: any) => toast.error(parseApiError(e, 'Save failed')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/billing/${id}`),
    onSuccess: () => {
      toast.success('Deleted')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
    },
  })

  const applyPaymentMutation = useMutation({
    mutationFn: ({ id, amount_paid }: { id: string; amount_paid: number }) =>
      api.put(`/billing/${id}`, { amount_paid }),
    retry: 1,
    onSuccess: () => {
      toast.success('Payment applied')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setApplyPayRow(null)
      setApplyPayAmount('')
    },
    onError: (e: any) => toast.error(parseApiError(e, 'Payment update failed')),
  })

  const markReturnedMutation = useMutation({
    mutationFn: (id: string) => api.put(`/billing/${id}`, { status: 'RETURNED' }),
    retry: 1,
    onSuccess: () => {
      toast.success('Marked as returned')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
    },
    onError: (e: any) => toast.error(parseApiError(e, 'Update failed')),
  })

  const whatsappTrackMutation = useMutation({
    mutationFn: ({ clientName, phoneNumber }: { clientName: string; phoneNumber: string }) =>
      api.post(`/billing/debtors/${encodeURIComponent(clientName)}/whatsapp`, { phone_number: phoneNumber }),
  })

  const openEdit = async (row: BillingRow) => {
    setLoadingEdit(true)
    setEditRow(row)
    setClientSearch(row.client_name)
    setSelectedClientId('')
    try {
      const details = await api.get(`/billing/${row.id}`).then((r) => r.data)
      const quantity = Number(details?.quantity ?? row.quantity ?? 1) || 1
      const totalAmount = Number(details?.total_amount ?? details?.amount_charged ?? row.total_amount ?? 0)
      const unitPrice = Number(details?.unit_price ?? (quantity ? totalAmount / quantity : 0))
      const amountPaid = Number(details?.amount_paid ?? details?.paid_amount ?? row.amount_paid ?? 0)

      reset({
        client_name: details?.client_name ?? row.client_name,
        client_phone: details?.phone_number ?? row.phone_number ?? '',
        service_name: details?.service_name ?? row.service_name,
        quantity,
        unit_price: Number.isFinite(unitPrice) ? unitPrice : 0,
        amount_paid: Number.isFinite(amountPaid) ? amountPaid : 0,
        service_expense: Number(details?.service_expense ?? 0) || 0,
        invoice_date: String(details?.invoice_date || details?.service_date || row.invoice_date || row.service_date || '').slice(0, 10),
        due_date: String(details?.due_date || '').slice(0, 10),
        notes: details?.notes ?? '',
      } as FormValues)
      setClientSearch(details?.client_name ?? row.client_name)
      setShowForm(true)
    } catch (e: any) {
      toast.error(parseApiError(e, 'Unable to open invoice for edit'))
    } finally {
      setLoadingEdit(false)
    }
  }

  const grouped: BillingGroup[] = useMemo(() => groupedData?.groups ?? [], [groupedData])

  const flatRows: FlatBillingEntry[] = useMemo(() => {
    const entries: FlatBillingEntry[] = []
    for (const group of grouped) {
      entries.push({ kind: 'separator', key: `sep-${group.service_date}`, group })
      for (const row of group.items) {
        entries.push({ kind: 'item', key: `row-${row.id}`, group, row })
      }
    }
    return entries
  }, [grouped])

  useEffect(() => {
    setVisibleCount(140)
    setRevealStartIndex(null)
    setRevealEndIndex(null)
  }, [groupedData?.page, groupedData?.total, search, dateFrom, dateTo, statusFilter, paidState, minAmount, maxAmount, returned])

  useEffect(() => {
    if (!loadMoreRef.current) return
    if (visibleCount >= flatRows.length) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisibleCount((prev) => {
              const next = Math.min(prev + 120, flatRows.length)
              if (next > prev) {
                setRevealStartIndex(prev)
                setRevealEndIndex(next)
              }
              return next
            })
          }
        }
      },
      { rootMargin: '320px' }
    )

    observer.observe(loadMoreRef.current)
    return () => observer.disconnect()
  }, [visibleCount, flatRows.length])

  useEffect(() => {
    return () => {
      if (motionTimerRef.current) {
        window.clearTimeout(motionTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (revealStartIndex == null || revealEndIndex == null) return
    const timer = window.setTimeout(() => {
      setRevealStartIndex(null)
      setRevealEndIndex(null)
    }, 520)
    return () => window.clearTimeout(timer)
  }, [revealStartIndex, revealEndIndex])

  const triggerTableMotion = (direction: 'left' | 'right' | 'fade') => {
    setTableMotion(direction)
    if (motionTimerRef.current) {
      window.clearTimeout(motionTimerRef.current)
    }
    motionTimerRef.current = window.setTimeout(() => setTableMotion(''), 260)
  }

  const totalSummary = useMemo(() => {
    let totalAmount = 0, totalPaid = 0, totalOutstanding = 0, jobs = 0
    for (const g of grouped) {
      totalAmount += Number(g.summary.total_amount || 0)
      totalPaid += Number(g.summary.total_paid || 0)
      totalOutstanding += Number(g.summary.total_outstanding || 0)
      jobs += Number(g.summary.job_count || 0)
    }
    return { totalAmount, totalPaid, totalOutstanding, jobs }
  }, [grouped])

  const activeRange = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    const d = new Date()
    d.setDate(d.getDate() - d.getDay())
    const weekStart = d.toISOString().slice(0, 10)
    const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10)
    if (dateFrom === today && dateTo === today) return 'today'
    if (dateFrom === weekStart && dateTo === today) return 'week'
    if (dateFrom === monthStart && dateTo === today) return 'month'
    return null
  }, [dateFrom, dateTo])

  const shiftMonth = (delta: number) => {
    triggerTableMotion(delta > 0 ? 'left' : 'right')
    const [y, m] = month.split('-').map(Number)
    const d = new Date(y, m - 1 + delta, 1)
    const nextMonth = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    const bounds = monthBounds(nextMonth)
    const next = new URLSearchParams(searchParams)
    next.set('month', nextMonth)
    next.set('from_date', bounds.from)
    next.set('to_date', bounds.to)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const shiftDay = (delta: number) => {
    triggerTableMotion(delta > 0 ? 'left' : 'right')
    const base = dateFrom || new Date().toISOString().slice(0, 10)
    const d = new Date(`${base}T00:00:00`)
    d.setDate(d.getDate() + delta)
    const day = d.toISOString().slice(0, 10)
    const next = new URLSearchParams(searchParams)
    next.set('from_date', day)
    next.set('to_date', day)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const applySingleDay = (day: string) => {
    if (!day) return
    triggerTableMotion('fade')
    const next = new URLSearchParams(searchParams)
    next.set('from_date', day)
    next.set('to_date', day)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const applyQuickRange = (type: 'today' | 'week' | 'month') => {
    triggerTableMotion('fade')
    const now = new Date()
    let from = ''
    const to = now.toISOString().slice(0, 10)

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
    next.set('from_date', from)
    next.set('to_date', to)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams)
    ;['search', 'from_date', 'to_date', 'payment_status', 'paid_state', 'min_amount', 'max_amount', 'is_return', 'month'].forEach((k) => next.delete(k))
    next.set('page', '1')
    setSearchInput('')
    setSearchParams(next, { replace: true })
  }

  const closeForm = () => {
    setShowForm(false)
    setEditRow(null)
    setSelectedClientId('')
    setClientSearch('')
    setShowClientDropdown(false)
    setExpandedRows(new Set())
    reset()
  }

  const toggleRow = (id: string) =>
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const generateBillText = (row: BillingRow): string =>
    [
      `*SERVICE INVOICE*`,
      `Client: ${row.client_name}`,
      row.phone_number ? `Phone: ${row.phone_number}` : '',
      `Service: ${row.service_name}`,
      `Amount: ${formatCurrency(row.total_amount, currency)}`,
      `Paid: ${formatCurrency(row.amount_paid, currency)}`,
      `Balance: ${formatCurrency(row.balance, currency)}`,
      `Status: ${statusLabel(row.status)}`,
      (row.invoice_date || row.service_date)
        ? `Date: ${(row.invoice_date || row.service_date)!.slice(0, 10)}`
        : '',
    ]
      .filter(Boolean)
      .join('\n')

  const openWhatsApp = async (row: BillingRow) => {
    const text = encodeURIComponent(generateBillText(row))
    const fallbackRaw = row.phone_number || prompt('Client phone missing. Enter WhatsApp number:') || ''
    const phone = normalizePhone(fallbackRaw)
    if (!phone) {
      toast.error('No client phone number found')
      return
    }
    window.open(`https://wa.me/${phone}?text=${text}`, '_blank', 'noopener,noreferrer')
    try {
      await whatsappTrackMutation.mutateAsync({ clientName: row.client_name, phoneNumber: fallbackRaw })
    } catch {
      // Sending already initiated; tracker failure should not block operator flow.
    }
  }

  const copyBill = async (row: BillingRow) => {
    try {
      await navigator.clipboard.writeText(generateBillText(row))
      toast.success('Bill copied to clipboard')
    } catch {
      toast.error('Copy failed')
    }
  }

  const hasActiveFilters = !!(search || dateFrom || dateTo || statusFilter || paidState || minAmount || maxAmount || returned)

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="p-6 space-y-4">

      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Service / Billing</h1>
        <button
          onClick={() => {
            setEditRow(null)
            setClientSearch('')
            setSelectedClientId('')
            setShowClientDropdown(false)
            reset({
              quantity: 1,
              unit_price: 0,
              amount_paid: 0,
              service_expense: 0,
              invoice_date: new Date().toISOString().slice(0, 10),
              due_date: '',
              notes: '',
            } as FormValues)
            setShowForm(true)
          }}
          className="btn-primary"
        >
          <Plus size={15} /> New Invoice
        </button>
      </div>

      {/* ── Date Nav + Quick Ranges ── */}
      <div className="rounded-xl border bg-white px-4 py-3 flex items-center justify-between gap-3 flex-wrap" style={{ borderColor: '#e7d89f' }}>
        <div className="flex items-center gap-1">
          <button
            className="rounded-lg border p-1.5 hover:bg-gray-50 transition-colors"
            style={{ borderColor: '#d4af37' }}
            onClick={() => shiftMonth(-1)}
            title="Previous month"
          >
            <ChevronLeft size={15} />
          </button>
          <button
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-semibold hover:bg-[#fffdf5] transition-colors"
            style={{ borderColor: '#d4af37' }}
            onClick={() => {
              const val = prompt('Go to month (YYYY-MM):', month)
              if (!val) return
              triggerTableMotion('fade')
              const bounds = monthBounds(val)
              const next = new URLSearchParams(searchParams)
              next.set('month', val)
              next.set('from_date', bounds.from)
              next.set('to_date', bounds.to)
              next.set('page', '1')
              setSearchParams(next, { replace: true })
            }}
            title="Click to jump to a specific month"
          >
            <Calendar size={13} className="text-[#D4AF37]" />
            {formatMonthLabel(month)}
          </button>
          <button
            className="rounded-lg border p-1.5 hover:bg-gray-50 transition-colors"
            style={{ borderColor: '#d4af37' }}
            onClick={() => shiftMonth(1)}
            title="Next month"
          >
            <ChevronRight size={15} />
          </button>
        </div>

        <div className="flex rounded-lg border overflow-hidden text-xs font-medium" style={{ borderColor: '#d4af37' }}>
          {(['today', 'week', 'month'] as const).map((type, i) => (
            <button
              key={type}
              onClick={() => applyQuickRange(type)}
              className={`px-3 py-1.5 transition-colors border-r last:border-r-0 ${
                activeRange === type
                  ? 'bg-black text-white'
                  : 'bg-white text-gray-600 hover:bg-[#fffdf5]'
              }`}
              style={{ borderColor: '#d4af37' }}
            >
              {['Today', 'This Week', 'This Month'][i]}
            </button>
          ))}
        </div>
      </div>

      {/* ── Compact Filters (2 rows) ── */}
      <div className="rounded-xl border bg-white px-4 py-3 space-y-2" style={{ borderColor: '#e7d89f' }}>
        {/* Row 1: Search + status filters */}
        <div className="flex gap-2 flex-wrap items-center">
          <div className="relative flex-1 min-w-48" style={{ maxWidth: '65%' }}>
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <input
              className="form-input pl-9 py-2 text-sm w-full"
              placeholder="Search clients, phone, service, notes, ID…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
          <select className="form-input py-2 text-sm" style={{ minWidth: '9rem' }} value={statusFilter} onChange={(e) => setParam('payment_status', e.target.value)}>
            <option value="">All statuses</option>
            <option value="PAID">Paid</option>
            <option value="PART PAYMENT">Part Payment</option>
            <option value="UNPAID">Unpaid</option>
            <option value="RETURNED">Returned</option>
          </select>
          {isAdmin && (
            <select className="form-input py-2 text-sm" style={{ minWidth: '8.5rem' }} value={paidState} onChange={(e) => setParam('paid_state', e.target.value)}>
              <option value="">All paid states</option>
              <option value="paid">Paid only</option>
              <option value="unpaid">Unpaid / partial</option>
            </select>
          )}
          <select className="form-input py-2 text-sm" style={{ minWidth: '8rem' }} value={returned} onChange={(e) => setParam('is_return', e.target.value)}>
            <option value="">All returns</option>
            <option value="false">Not returned</option>
            <option value="true">Returned</option>
          </select>
        </div>

        {/* Row 2: Date + amount range */}
        <div className="flex gap-2 flex-wrap items-center">
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-400 whitespace-nowrap">From</span>
            <input type="date" className="form-input py-1.5 text-xs" value={dateFrom} onChange={(e) => setParam('from_date', e.target.value)} />
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-400 whitespace-nowrap">To</span>
            <input type="date" className="form-input py-1.5 text-xs" value={dateTo} onChange={(e) => setParam('to_date', e.target.value)} />
          </div>
          {isAdmin && <input type="number" min="0" className="form-input py-1.5 text-xs" style={{ width: '7rem' }} placeholder="Min amount" value={minAmount} onChange={(e) => setParam('min_amount', e.target.value)} />}
          {isAdmin && <input type="number" min="0" className="form-input py-1.5 text-xs" style={{ width: '7rem' }} placeholder="Max amount" value={maxAmount} onChange={(e) => setParam('max_amount', e.target.value)} />}
          <button type="button" className="btn-secondary text-xs" onClick={() => shiftDay(-1)}>Prev Day</button>
          <input type="date" className="form-input py-1.5 text-xs" value={dateFrom || ''} onChange={(e) => applySingleDay(e.target.value)} />
          <button type="button" className="btn-secondary text-xs" onClick={() => shiftDay(1)}>Next Day</button>
          {hasActiveFilters && (
            <button type="button" className="flex items-center gap-1 text-xs text-gray-500 hover:text-red-600 border rounded-lg px-2 py-1.5 hover:border-red-300 transition-colors ml-auto" style={{ borderColor: '#e5e7eb' }} onClick={clearFilters}>
              <X size={12} /> Clear filters
            </button>
          )}
        </div>

        {/* Active filter badges */}
        {hasActiveFilters && (
          <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
            {search && <FilterBadge label={`"${search}"`} onRemove={() => { setSearchInput(''); setParam('search') }} />}
            {dateFrom && <FilterBadge label={`From ${dateFrom}`} onRemove={() => setParam('from_date')} />}
            {dateTo && <FilterBadge label={`To ${dateTo}`} onRemove={() => setParam('to_date')} />}
            {statusFilter && <FilterBadge label={statusFilter} onRemove={() => setParam('payment_status')} />}
            {isAdmin && paidState && <FilterBadge label={`Paid: ${paidState}`} onRemove={() => setParam('paid_state')} />}
            {isAdmin && minAmount && <FilterBadge label={`Min ${minAmount}`} onRemove={() => setParam('min_amount')} />}
            {isAdmin && maxAmount && <FilterBadge label={`Max ${maxAmount}`} onRemove={() => setParam('max_amount')} />}
            {returned && <FilterBadge label={returned === 'true' ? 'Returned' : 'Not returned'} onRemove={() => setParam('is_return')} />}
          </div>
        )}
      </div>

      {/* ── Summary Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryCard label="Jobs" value={String(totalSummary.jobs)} />
        {isAdmin && <SummaryCard label="Total Amount" value={formatCurrency(totalSummary.totalAmount, currency)} />}
        {isAdmin && <SummaryCard label="Paid" value={formatCurrency(totalSummary.totalPaid, currency)} valueClass="text-emerald-700" />}
        {isAdmin && (
          <SummaryCard
            label="Outstanding"
            value={formatCurrency(totalSummary.totalOutstanding, currency)}
            prominent
            valueClass={totalSummary.totalOutstanding > 0 ? 'text-amber-700' : 'text-emerald-600'}
          />
        )}
      </div>

      {/* ── Continuous table with sticky date separators ── */}
      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <div className="space-y-3">
          {flatRows.length === 0 && (
            <div className="rounded-xl border p-8 text-sm text-gray-400 text-center" style={{ borderColor: '#e7d89f' }}>
              No jobs found for the current filters.
            </div>
          )}

          {flatRows.length > 0 && (
            <section
              className={`rounded-xl border bg-white ${
                tableMotion === 'left'
                  ? 'billing-table-enter-left'
                  : tableMotion === 'right'
                    ? 'billing-table-enter-right'
                    : tableMotion === 'fade'
                      ? 'billing-table-enter-fade'
                      : ''
              }`}
              style={{ borderColor: '#e7d89f' }}
            >
              <div className="max-h-[68vh] overflow-y-auto">
                <div
                  className="sticky top-0 z-30 grid items-center gap-2 px-4 py-2 text-xs font-medium text-gray-400 uppercase tracking-wide border-b bg-white"
                  style={{ gridTemplateColumns: '1.8fr 1.8fr 1fr 1fr 1fr 1fr 6rem', borderColor: '#f7f1d8' }}
                >
                  <span>Client</span>
                  <span>Service</span>
                  <span>Total</span>
                  <span>Paid</span>
                  <span>Balance</span>
                  <span>Status</span>
                  <span />
                </div>

                {flatRows.slice(0, visibleCount).map((entry, idx) => {
                  if (entry.kind === 'separator') {
                    const g = entry.group
                    const hasOutstanding = Number(g.summary.total_outstanding) > 0
                    return (
                      <div
                        key={entry.key}
                        className="sticky top-9 z-20 border-b border-t px-4 py-2 bg-[#fffdf5]"
                        style={{ borderColor: '#f1e7bf' }}
                      >
                        <div className="flex items-center justify-between gap-3 text-xs">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="font-semibold text-sm text-gray-900">{labelForDate(g.service_date)}</span>
                            <span className="text-gray-400 hidden sm:inline">{g.service_date}</span>
                          </div>
                          <div className="flex items-center gap-3 shrink-0 text-gray-500">
                            <span>{g.summary.job_count} jobs</span>
                            {isAdmin && <span className="hidden lg:inline"><span className="text-gray-400">Total </span>{formatCurrency(g.summary.total_amount, currency)}</span>}
                            {isAdmin && <span className="hidden lg:inline text-emerald-600">{formatCurrency(g.summary.total_paid, currency)} paid</span>}
                            {isAdmin && hasOutstanding ? (
                              <span className="font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
                                {formatCurrency(g.summary.total_outstanding, currency)} due
                              </span>
                            ) : (
                              <span className="text-emerald-600 text-xs font-medium">✓ Settled</span>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  }

                  const row = entry.row
                  const expanded = expandedRows.has(row.id)
                  const balancePositive = Number(row.balance) > 0
                  const showBottomBorder = idx < Math.min(visibleCount, flatRows.length) - 1
                  const isRevealedRow = revealStartIndex != null && revealEndIndex != null && idx >= revealStartIndex && idx < revealEndIndex
                  const revealDelay = revealStartIndex == null ? 0 : Math.min((idx - revealStartIndex) * 14, 180)

                  return (
                    <div
                      key={entry.key}
                      className={`${showBottomBorder ? 'border-b' : ''} ${isRevealedRow ? 'billing-row-stagger-enter' : ''}`}
                      style={{
                        borderColor: '#f7f1d8',
                        animationDelay: isRevealedRow ? `${revealDelay}ms` : undefined,
                      }}
                    >
                      <div
                        className="group grid items-center gap-2 px-4 py-3 text-sm hover:bg-[#fffdf5] cursor-pointer transition-colors"
                        style={{ gridTemplateColumns: '1.8fr 1.8fr 1fr 1fr 1fr 1fr 6rem' }}
                        onClick={() => toggleRow(row.id)}
                      >
                        <span className="truncate font-medium text-gray-900" title={row.client_name}>{row.client_name}</span>
                        <span className="truncate text-gray-600" title={row.service_name}>{row.service_name}</span>
                        <span className="text-gray-800 tabular-nums">{isAdmin ? formatCurrency(row.total_amount, currency) : 'Hidden'}</span>
                        <span className="text-emerald-700 tabular-nums">{isAdmin ? formatCurrency(row.amount_paid, currency) : 'Hidden'}</span>
                        <span className={`tabular-nums font-medium ${balancePositive ? 'text-amber-700' : 'text-gray-300'}`}>
                          {isAdmin ? (balancePositive ? formatCurrency(row.balance, currency) : '—') : 'Hidden'}
                        </span>
                        <span>
                          <span className={statusBadgeClass(row.status)}>{statusLabel(row.status)}</span>
                        </span>
                        <div
                          className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <ActionBtn title="Edit" icon={<Pencil size={13} />} onClick={() => { void openEdit(row) }} />
                          {isAdmin && <ActionBtn title="Apply Payment" icon={<CreditCard size={13} />} onClick={() => { setApplyPayRow(row); setApplyPayAmount(String(row.amount_paid)) }} />}
                          <ActionBtn title="WhatsApp Bill" icon={<MessageCircle size={13} />} onClick={() => openWhatsApp(row)} colorClass="hover:text-green-600" />
                          <ActionBtn title="Copy Bill" icon={<Copy size={13} />} onClick={() => copyBill(row)} />
                          <ActionBtn title="Mark Returned" icon={<RotateCcw size={13} />} onClick={() => { if (confirm('Mark as returned?')) markReturnedMutation.mutate(row.id) }} />
                          <ActionBtn title="Delete" icon={<Trash2 size={13} />} onClick={() => { if (confirm('Delete invoice?')) deleteMutation.mutate(row.id) }} colorClass="hover:text-red-600" />
                        </div>
                      </div>

                      {expanded && (
                        <div
                          className="px-6 pb-3 pt-2 bg-[#fffdf5] border-t text-xs text-gray-600 space-y-2"
                          style={{ borderColor: '#f7f1d8' }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex flex-wrap gap-x-6 gap-y-1 text-gray-500">
                            {row.phone_number && <span>📱 <strong className="text-gray-700">{row.phone_number}</strong></span>}
                            {(row.invoice_date || row.service_date) && <span>📅 {(row.invoice_date || row.service_date)!.slice(0, 10)}</span>}
                            <span>Qty: <strong className="text-gray-700">{row.quantity}</strong></span>
                            <span>Unit price: <strong className="text-gray-700">{formatCurrency(Number(row.total_amount) / (Number(row.quantity) || 1), currency)}</strong></span>
                            <span>ID: <span className="font-mono text-gray-400">{row.id.slice(0, 8)}…</span></span>
                          </div>
                          {row.notes && <p className="italic text-gray-400">📝 {row.notes}</p>}
                          <div className="flex flex-wrap gap-2 pt-1">
                            <InlineBtn icon={<Pencil size={11} />} label="Edit" onClick={() => { void openEdit(row) }} />
                            {isAdmin && <InlineBtn icon={<CreditCard size={11} />} label="Apply Payment" onClick={() => { setApplyPayRow(row); setApplyPayAmount(String(row.amount_paid)) }} />}
                            <InlineBtn icon={<MessageCircle size={11} />} label="WhatsApp" onClick={() => openWhatsApp(row)} extraClass="text-green-700 hover:bg-green-50" />
                            <InlineBtn icon={<Copy size={11} />} label="Copy Bill" onClick={() => copyBill(row)} />
                            {row.status !== 'RETURNED' && (
                              <InlineBtn icon={<RotateCcw size={11} />} label="Mark Returned" onClick={() => { if (confirm('Mark as returned?')) markReturnedMutation.mutate(row.id) }} />
                            )}
                            <InlineBtn icon={<Trash2 size={11} />} label="Delete" onClick={() => { if (confirm('Delete invoice?')) deleteMutation.mutate(row.id) }} extraClass="text-red-600 hover:bg-red-50" />
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}

                {visibleCount < flatRows.length && (
                  <div ref={loadMoreRef} className="px-4 py-3 text-center text-xs text-gray-400">
                    Loading more rows...
                  </div>
                )}
              </div>
            </section>
          )}

          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setParam('page', String(page - 1))} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page} of {groupedData?.total_pages ?? 1}</span>
            <button disabled={page >= (groupedData?.total_pages ?? 1)} onClick={() => setParam('page', String(page + 1))} className="btn-secondary">Next</button>
          </div>
        </div>
      )}

      {/* ── New / Edit Invoice Modal ── */}
      <Modal
        title={editRow ? 'Edit Invoice' : 'New Invoice'}
        open={showForm}
        onClose={closeForm}
        size="lg"
        bodyClassName="pb-2"
        footer={(
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={closeForm}>Cancel</button>
            <button type="submit" form="invoice-form" className="btn-primary" disabled={saveMutation.isPending || loadingEdit}>
              {loadingEdit ? 'Loading...' : saveMutation.isPending ? 'Saving...' : 'Save'}
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
              <div className="absolute z-20 mt-1 w-full rounded-lg border bg-white shadow-lg" style={{ borderColor: '#d4af37' }}>
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
                    <div className="text-xs text-gray-500">{s.phone || 'No phone'} · {s.email || 'No email'}</div>
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
            <input type="number" step="0.01" min="0.01" className="form-input"
              {...register('quantity', { valueAsNumber: true, min: { value: 0.01, message: 'Must be > 0' } })} />
            {errors.quantity && <p className="text-xs text-red-500">{errors.quantity.message as string}</p>}
          </div>
          <div>
            <label className="form-label">Unit Price</label>
            <input type="number" step="0.01" min="0.01" className="form-input"
              {...register('unit_price', { valueAsNumber: true, required: 'Required', min: { value: 0.01, message: 'Must be > 0' } })} />
            {errors.unit_price && <p className="text-xs text-red-500">{errors.unit_price.message as string}</p>}
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

      {/* ── Apply Payment Modal ── */}
      <Modal
        title="Apply Payment"
        open={!!applyPayRow}
        onClose={() => { setApplyPayRow(null); setApplyPayAmount('') }}
        size="sm"
        footer={(
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => { setApplyPayRow(null); setApplyPayAmount('') }}>Cancel</button>
            <button
              type="button"
              className="btn-primary"
              disabled={applyPaymentMutation.isPending}
              onClick={() => {
                if (!applyPayRow) return
                const val = parseFloat(applyPayAmount)
                if (!Number.isFinite(val) || val < 0) { toast.error('Enter a valid amount'); return }
                applyPaymentMutation.mutate({ id: applyPayRow.id, amount_paid: val })
              }}
            >
              {applyPaymentMutation.isPending ? 'Saving...' : 'Apply'}
            </button>
          </div>
        )}
      >
        {applyPayRow && (
          <div className="space-y-4">
            <div className="rounded-lg border bg-gray-50 px-4 py-3 text-sm space-y-1" style={{ borderColor: '#e7d89f' }}>
              <p><span className="text-gray-500">Client:</span> <strong>{applyPayRow.client_name}</strong></p>
              <p><span className="text-gray-500">Service:</span> {applyPayRow.service_name}</p>
              <p><span className="text-gray-500">Total:</span> {formatCurrency(applyPayRow.total_amount, currency)}</p>
              <p><span className="text-gray-500">Currently paid:</span> <span className="text-emerald-600 font-medium">{formatCurrency(applyPayRow.amount_paid, currency)}</span></p>
              <p><span className="text-gray-500">Balance:</span> <span className="text-amber-700 font-semibold">{formatCurrency(applyPayRow.balance, currency)}</span></p>
            </div>
            <div>
              <label className="form-label">New Total Amount Paid</label>
              <input
                type="number"
                min="0"
                step="0.01"
                className="form-input"
                value={applyPayAmount}
                onChange={(e) => setApplyPayAmount(e.target.value)}
                autoFocus
              />
              <p className="text-xs text-gray-400 mt-1">Set the total paid so far (not just the new payment).</p>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function FilterBadge({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs rounded-full border bg-white px-2 py-0.5" style={{ borderColor: '#d4af37' }}>
      {label}
      <button type="button" onClick={onRemove} className="text-gray-400 hover:text-gray-700 ml-0.5 leading-none">
        <X size={10} />
      </button>
    </span>
  )
}

function SummaryCard({
  label,
  value,
  prominent = false,
  valueClass = '',
}: {
  label: string
  value: string
  prominent?: boolean
  valueClass?: string
}) {
  return (
    <div
      className={`rounded-xl border px-4 py-3 bg-white ${prominent ? 'ring-1 ring-amber-200' : ''}`}
      style={{ borderColor: prominent ? '#d4af37' : '#e7d89f' }}
    >
      <p className={`text-xs text-gray-500 mb-0.5 ${prominent ? 'font-medium uppercase tracking-wide' : ''}`}>{label}</p>
      <p className={`font-bold ${prominent ? 'text-2xl' : 'text-lg'} ${valueClass}`}>{value}</p>
    </div>
  )
}

function ActionBtn({
  title,
  icon,
  onClick,
  colorClass = 'hover:text-[#D4AF37]',
}: {
  title: string
  icon: React.ReactNode
  onClick: () => void
  colorClass?: string
}) {
  return (
    <button
      title={title}
      type="button"
      className={`p-1 rounded text-gray-400 transition-colors ${colorClass}`}
      onClick={onClick}
    >
      {icon}
    </button>
  )
}

function InlineBtn({
  icon,
  label,
  onClick,
  extraClass = '',
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  extraClass?: string
}) {
  return (
    <button
      type="button"
      className={`inline-flex items-center gap-1 text-xs border rounded px-2 py-1 hover:bg-white transition-colors text-gray-600 ${extraClass}`}
      style={{ borderColor: '#d4af37' }}
      onClick={onClick}
    >
      {icon} {label}
    </button>
  )
}
