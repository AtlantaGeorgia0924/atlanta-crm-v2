import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router-dom'
import {
  ChevronDown,
  Filter,
  Plus,
  RefreshCcw,
  Search,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import api from '@/lib/api'
import { buildIdempotencyKey } from '@/lib/idempotency'
import LoadingSpinner from '@/components/LoadingSpinner'
import Modal from '@/components/Modal'
import { formatCurrency, statusLabel } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'

// ─── Types ────────────────────────────────────────────────────────────────────

interface BillingRow {
  id: string
  client_name: string
  phone_number?: string
  service_name: string
  device_model?: string
  imei?: string
  serial_number?: string
  condition?: string
  lock_status?: string
  quantity: number
  total_amount: number
  amount_charged?: number
  amount_paid: number
  paid_amount?: number
  balance: number
  status: string
  payment_status?: string
  invoice_date?: string
  service_date?: string
  notes?: string
  created_by?: string
  created_by_name?: string
  created_by_role?: string
  last_edited_by?: string
  last_edited_by_name?: string
  last_edited_at?: string
  returned_by?: string
  returned_by_name?: string
  returned_at?: string
  last_payment_by?: string
  last_payment_by_name?: string
  last_payment_at?: string
  assigned_staff_id?: string
  assigned_staff_name?: string
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
  device_model?: string
  imei?: string
  serial_number?: string
  condition?: string
  lock_status?: string
  payment_status?: string
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

interface PaymentHistoryRow {
  id: string
  service_job_id?: string
  payment_amount?: number
  amount?: number
  payment_method?: string
  reference_no?: string
  payment_note?: string
  notes?: string
  applied_by_name?: string
  payment_date?: string
  created_at?: string
  is_reversed?: boolean
}

interface BillingActivityRow {
  id: string
  action?: string
  entity_type?: string
  entity_id?: string
  performed_by?: string
  detail?: Record<string, any>
  created_at?: string
}

interface ClientSummary {
  client_name: string
  phone_number?: string
  total_jobs: number
  unpaid_services_count?: number
  last_payment_date?: string | null
  last_whatsapp_sent_at?: string | null
  whatsapp_sent_count?: number
  outstanding_balance?: number | null
  recent_services: Array<{
    id: string
    service_name: string
    service_date?: string
    payment_status?: string
  }>
}

interface WhatsAppContactResponse {
  phone_number?: string
  normalized_phone_number?: string
  requires_manual_entry?: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

function operationStatusClass(status: string): string {
  const s = String(status || '').toUpperCase()
  if (s === 'PAID') return 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold bg-emerald-100 text-emerald-700'
  if (s === 'PART PAYMENT' || s === 'PARTIAL') return 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold bg-amber-100 text-amber-700'
  if (s === 'UNPAID') return 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold bg-red-100 text-red-700'
  if (s === 'RETURNED') return 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold bg-gray-200 text-gray-700'
  return 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold bg-gray-100 text-gray-700'
}

function parseApiError(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail
  const message = error?.response?.data?.message
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0]
    const loc = Array.isArray(first?.loc) ? first.loc.join('.') : ''
    const msg = String(first?.msg || first?.message || fallback)
    return loc ? `${loc}: ${msg}` : msg
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  if (typeof message === 'string' && message.trim()) return message
  if (error?.response?.status === 403) return 'Permission denied for this action'
  if (error?.response?.status === 404) return 'Invoice was not found or may have been removed'
  if (error?.response?.status === 408) return 'Request timed out, please try again'
  if (error?.response?.status === 422) return 'Validation failed. Please check the values and try again'
  if (error?.response?.status) return `Request failed (${error.response.status})`
  if (error?.message === 'Network Error') return 'Network/CORS error: cannot reach API'
  if (String(error?.code || '').toUpperCase() === 'ECONNABORTED') return 'Request timed out, please retry'
  return String(error?.message || fallback)
}

function resolveSerial(row: BillingRow): string {
  const anyRow = row as any
  const value = row.serial_number || anyRow.serial_no || anyRow.device_serial || ''
  return String(value || '').trim() || '—'
}

function resolveImeiValue(row: BillingRow): string {
  const anyRow = row as any
  const value = row.imei || anyRow.device_imei || anyRow.imei_number || anyRow.source_imei || anyRow.imei1 || anyRow.imei_2 || ''
  return String(value || '').trim()
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function Billing() {
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'
  const imeiText = (row: BillingRow) => resolveImeiValue(row) || '—'

  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<BillingRow | null>(null)
  const [clientSearch, setClientSearch] = useState('')
  const [showClientDropdown, setShowClientDropdown] = useState(false)
  const [selectedClientId, setSelectedClientId] = useState('')
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())
  const [applyPayRow, setApplyPayRow] = useState<BillingRow | null>(null)
  const [applyPayAmount, setApplyPayAmount] = useState('')
  const [applyPayMethod, setApplyPayMethod] = useState('cash')
  const [applyPayReference, setApplyPayReference] = useState('')
  const [applyPayDate, setApplyPayDate] = useState('')
  const [applyPayNotes, setApplyPayNotes] = useState('')
  const [applyPayIdempotencyKey, setApplyPayIdempotencyKey] = useState('')
  const [reversePayRow, setReversePayRow] = useState<BillingRow | null>(null)
  const [reversePayAmount, setReversePayAmount] = useState('')
  const [reversePayReason, setReversePayReason] = useState('')
  const [reversePayIdempotencyKey, setReversePayIdempotencyKey] = useState('')
  const [loadingEdit, setLoadingEdit] = useState(false)
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [actionMenuRowId, setActionMenuRowId] = useState<string | null>(null)
  const [clientQuickViewName, setClientQuickViewName] = useState<string | null>(null)
  const [paymentQuickViewRow, setPaymentQuickViewRow] = useState<BillingRow | null>(null)
  const [expandedNotesRows, setExpandedNotesRows] = useState<Set<string>>(new Set())
  const [visibleCount, setVisibleCount] = useState(140)
  const [revealStartIndex, setRevealStartIndex] = useState<number | null>(null)
  const [revealEndIndex, setRevealEndIndex] = useState<number | null>(null)
  const [tableMotion, setTableMotion] = useState<'left' | 'right' | 'fade' | ''>('')
  const loadMoreRef = useRef<HTMLDivElement | null>(null)
  const motionTimerRef = useRef<number | null>(null)

  const todayISO = new Date().toISOString().slice(0, 10)
  const page = Number(searchParams.get('page') || '1')
  const statusFilter = searchParams.get('payment_status') || ''
  const search = searchParams.get('search') || ''
  const selectedDate = searchParams.get('date') || todayISO
  const rangeFrom = searchParams.get('from_date') || ''
  const rangeTo = searchParams.get('to_date') || ''
  const minAmount = searchParams.get('min_amount') || ''
  const maxAmount = searchParams.get('max_amount') || ''
  const returned = searchParams.get('is_return') || ''
  const paidState = searchParams.get('paid_state') || ''
  const createdBy = searchParams.get('created_by') || ''
  const editedBy = searchParams.get('edited_by') || ''
  const assignedStaff = searchParams.get('assigned_staff') || ''

  const [searchInput, setSearchInput] = useState(search)
  const normalizedSearch = search.trim()
  const isRangeMode = !normalizedSearch && !!rangeFrom && !!rangeTo && rangeFrom !== rangeTo
  const effectiveFrom = normalizedSearch ? undefined : (isRangeMode ? rangeFrom : selectedDate)
  const effectiveTo = normalizedSearch ? undefined : (isRangeMode ? rangeTo : selectedDate)
  const effectiveStatusFilter = normalizedSearch ? '' : statusFilter
  const effectiveReturned = normalizedSearch ? '' : returned
  const effectivePaidState = normalizedSearch ? '' : paidState
  const effectiveCreatedBy = normalizedSearch ? '' : createdBy
  const effectiveEditedBy = normalizedSearch ? '' : editedBy
  const effectiveAssignedStaff = normalizedSearch ? '' : assignedStaff
  const effectiveMinAmount = normalizedSearch ? '' : minAmount
  const effectiveMaxAmount = normalizedSearch ? '' : maxAmount

  const { register, handleSubmit, reset, setValue, formState: { errors } } = useForm<FormValues>()

  useEffect(() => { setSearchInput(search) }, [search])

  useEffect(() => {
    if (searchParams.get('date')) return
    const next = new URLSearchParams(searchParams)
    next.set('date', todayISO)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const id = setTimeout(() => {
      const next = new URLSearchParams(searchParams)
      const trimmed = searchInput.trim()
      if (trimmed) {
        next.set('search', trimmed)
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
          page_size: normalizedSearch ? 500 : 200,
          payment_status: effectiveStatusFilter || undefined,
          search: search || undefined,
          from_date: effectiveFrom,
          to_date: effectiveTo,
          min_amount: effectiveMinAmount || undefined,
          max_amount: effectiveMaxAmount || undefined,
          is_return: effectiveReturned === '' ? undefined : effectiveReturned === 'true',
          paid_state: effectivePaidState || undefined,
          created_by: effectiveCreatedBy || undefined,
          edited_by: effectiveEditedBy || undefined,
          assigned_staff: effectiveAssignedStaff || undefined,
        },
      }).then((r) => r.data),
    placeholderData: (prev) => prev,
  })

  const { data: clientQuickView, isLoading: clientQuickViewLoading } = useQuery<ClientSummary>({
    queryKey: ['billing-client-quick-view', clientQuickViewName],
    queryFn: () =>
      api.get('/billing/client-summary/by-name', {
        params: { client_name: clientQuickViewName, limit: 6 },
      }).then((r) => r.data),
    enabled: !!clientQuickViewName,
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
    enabled: isAdmin,
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { data: usersData } = useQuery<{ items: Array<{ id: string; full_name?: string; email?: string; role?: string }> }>({
    queryKey: ['billing-users-filter-list'],
    queryFn: () => api.get('/users', { params: { page: 1, page_size: 200, include_deleted: false } }).then((r) => r.data),
    enabled: isAdmin,
  })
  const userOptions = useMemo(
    () => (usersData?.items ?? []).map((u) => ({ id: String(u.id), label: u.full_name || u.email || String(u.id) })),
    [usersData]
  )

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
      if (!Number.isFinite(quantity) || quantity <= 0) {
        throw new Error('Quantity must be greater than zero')
      }
      if (!Number.isFinite(amountPaid) || amountPaid < 0) {
        throw new Error('Amount paid cannot be negative')
      }

      const normalizedClientName = String(values.client_name || '').trim()
      const normalizedServiceName = String(values.service_name || '').trim()
      if (!normalizedClientName || !normalizedServiceName) {
        throw new Error('Client Name and Service Name are required')
      }

      const computedTotal = quantity * unitPrice
      if (amountPaid > computedTotal) {
        throw new Error('Paid amount cannot exceed total amount')
      }

      const payload = {
        ...values,
        client_name: normalizedClientName,
        service_name: normalizedServiceName,
        device_model: values.device_model?.trim() || undefined,
        imei: values.imei?.trim() || undefined,
        serial_number: values.serial_number?.trim() || undefined,
        condition: values.condition?.trim() || undefined,
        lock_status: values.lock_status?.trim() || undefined,
        payment_status: values.payment_status?.trim() || undefined,
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
        delete (finalPayload as any).payment_status
      }

      return editRow ? api.put(`/billing/${editRow.id}`, finalPayload) : api.post('/billing', payload)
    },
    retry: 1,
    onSuccess: (res) => {
      const updated = res?.data
      if (updated?.id) {
        qc.setQueriesData({ queryKey: ['billing-grouped'] }, (old: any) => {
          if (!old?.groups) return old
          const groups = (old.groups || []).map((g: any) => ({ ...g, items: [...(g.items || [])] }))
          let found = false
          for (const g of groups) {
            const idx = (g.items || []).findIndex((r: any) => r.id === updated.id)
            if (idx >= 0) {
              g.items[idx] = { ...g.items[idx], ...updated }
              found = true
              break
            }
          }
          if (!found) {
            const dateKey = String(updated.service_date || updated.invoice_date || '').slice(0, 10) || 'Unknown'
            const target = groups.find((g: any) => g.service_date === dateKey)
            if (target) target.items.unshift(updated)
            else groups.unshift({
              service_date: dateKey,
              items: [updated],
              summary: { job_count: 0, total_amount: 0, total_paid: 0, total_outstanding: 0 },
            })
          }
          return { ...old, groups }
        })
      }
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
      qc.invalidateQueries({ queryKey: ['system-status'] })
      qc.invalidateQueries({ queryKey: ['invoice-payments'] })
      qc.invalidateQueries({ queryKey: ['billing-client-quick-view'] })
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
    onError: (e: any) => toast.error(parseApiError(e, 'Delete failed')),
  })

  const applyPaymentMutation = useMutation({
    mutationFn: ({ id, amount }: { id: string; amount: number }) =>
      api.post('/payments', {
        service_job_id: id,
        amount,
        payment_method: applyPayMethod,
        reference_no: applyPayReference.trim() || undefined,
        payment_date: applyPayDate || undefined,
        notes: applyPayNotes.trim() || undefined,
        idempotency_key: applyPayIdempotencyKey,
      }),
    retry: 1,
    onSuccess: () => {
      toast.success('Payment applied')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
      qc.invalidateQueries({ queryKey: ['system-status'] })
      qc.invalidateQueries({ queryKey: ['invoice-payments'] })
      qc.invalidateQueries({ queryKey: ['billing-client-quick-view'] })
      setApplyPayRow(null)
      setApplyPayAmount('')
      setApplyPayMethod('cash')
      setApplyPayReference('')
      setApplyPayDate('')
      setApplyPayNotes('')
      setApplyPayIdempotencyKey('')
    },
    onError: (e: any) => toast.error(parseApiError(e, 'Payment apply failed')),
  })

  const openApplyPayment = (row: BillingRow) => {
    setApplyPayRow(row)
    setApplyPayAmount('')
    setApplyPayMethod('cash')
    setApplyPayReference('')
    setApplyPayDate(new Date().toISOString().slice(0, 10))
    setApplyPayNotes('')
    setApplyPayIdempotencyKey(buildIdempotencyKey('payment-apply'))
  }

  const reversePaymentMutation = useMutation({
    mutationFn: ({ id, amount, reason }: { id: string; amount: number; reason?: string }) =>
      api.post('/payments/reverse', {
        service_job_id: id,
        amount,
        reason: reason || undefined,
        idempotency_key: reversePayIdempotencyKey,
      }),
    retry: 1,
    onSuccess: () => {
      toast.success('Payment reversed')
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
      qc.invalidateQueries({ queryKey: ['system-status'] })
      qc.invalidateQueries({ queryKey: ['invoice-payments'] })
      qc.invalidateQueries({ queryKey: ['billing-client-quick-view'] })
      setReversePayRow(null)
      setReversePayAmount('')
      setReversePayReason('')
      setReversePayIdempotencyKey('')
    },
    onError: (e: any) => toast.error(parseApiError(e, 'Payment reversal failed')),
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
        device_model: details?.device_model ?? row.device_model ?? '',
        imei: details?.imei ?? '',
        serial_number: details?.serial_number ?? '',
        condition: details?.condition ?? '',
        lock_status: details?.lock_status ?? '',
        payment_status: String(details?.payment_status || details?.status || row.payment_status || row.status || '').toUpperCase(),
        description: details?.description ?? '',
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

  const handleInvoiceFormKeyDown = (e: React.KeyboardEvent<HTMLFormElement>) => {
    if (e.key !== 'Enter' || e.shiftKey) return
    const target = e.target as HTMLElement
    const tag = target.tagName.toLowerCase()
    if (tag === 'textarea' || (target as HTMLInputElement).type === 'submit') return
    e.preventDefault()
    const controls = Array.from(
      e.currentTarget.querySelectorAll<HTMLElement>('input, select, textarea, button')
    ).filter((el) => !el.hasAttribute('disabled') && el.getAttribute('type') !== 'hidden')
    const idx = controls.indexOf(target)
    if (idx >= 0 && idx < controls.length - 1) {
      controls[idx + 1].focus()
    }
  }

  const { data: paymentReferencePreview } = useQuery<{ reference_no: string }>({
    queryKey: ['payment-reference-preview', applyPayRow?.id],
    queryFn: () => api.get('/payments/reference').then((r) => r.data),
    enabled: !!applyPayRow && isAdmin,
  })

  useEffect(() => {
    if (!applyPayRow) return
    if (applyPayReference.trim()) return
    const generated = paymentReferencePreview?.reference_no
    if (generated) setApplyPayReference(generated)
  }, [applyPayRow, applyPayReference, paymentReferencePreview])

  const flatRows: FlatBillingEntry[] = useMemo(() => {
    const entries: FlatBillingEntry[] = []
    const groupsToRender = isRangeMode ? grouped : grouped.slice(0, 1)
    for (const group of groupsToRender) {
      if (isRangeMode) {
        entries.push({ kind: 'separator', key: `sep-${group.service_date}`, group })
      }
      for (const row of group.items) {
        entries.push({ kind: 'item', key: `row-${row.id}`, group, row })
      }
    }
    return entries
  }, [grouped, isRangeMode])

  const activeDebtorsCount = useMemo(() => {
    const names = new Set<string>()
    for (const entry of flatRows) {
      if (entry.kind === 'item') {
        names.add(String(entry.row.client_name || '').trim().toUpperCase())
      }
    }
    return names.size
  }, [flatRows])

  useEffect(() => {
    setVisibleCount(140)
    setRevealStartIndex(null)
    setRevealEndIndex(null)
  }, [groupedData?.page, groupedData?.total, search, selectedDate, rangeFrom, rangeTo, statusFilter, paidState, minAmount, maxAmount, returned])

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
    if (!isRangeMode) return null
    const today = new Date().toISOString().slice(0, 10)
    const d = new Date()
    d.setDate(d.getDate() - d.getDay())
    const weekStart = d.toISOString().slice(0, 10)
    const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10)
    if (rangeFrom === today && rangeTo === today) return 'today'
    if (rangeFrom === weekStart && rangeTo === today) return 'week'
    if (rangeFrom === monthStart && rangeTo === today) return 'month'
    return null
  }, [isRangeMode, rangeFrom, rangeTo])

  const shiftDay = (delta: number) => {
    triggerTableMotion(delta > 0 ? 'left' : 'right')
    const d = new Date(`${selectedDate}T00:00:00`)
    d.setDate(d.getDate() + delta)
    const nextDate = d.toISOString().slice(0, 10)
    const next = new URLSearchParams(searchParams)
    next.set('date', nextDate)
    next.delete('from_date')
    next.delete('to_date')
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const applySingleDay = (day: string) => {
    if (!day) return
    triggerTableMotion('fade')
    const next = new URLSearchParams(searchParams)
    next.set('date', day)
    next.delete('from_date')
    next.delete('to_date')
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const applyQuickRange = (type: 'today' | 'week' | 'month') => {
    triggerTableMotion('fade')
    const now = new Date()
    let from = ''
    const to = now.toISOString().slice(0, 10)

    if (type === 'today') {
      applySingleDay(to)
      return
    }

    if (type === 'week') {
      const start = new Date(now)
      start.setDate(now.getDate() - now.getDay())
      from = start.toISOString().slice(0, 10)
    } else {
      const start = new Date(now.getFullYear(), now.getMonth(), 1)
      from = start.toISOString().slice(0, 10)
    }

    const next = new URLSearchParams(searchParams)
    next.set('date', to)
    next.set('from_date', from)
    next.set('to_date', to)
    next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams)
    ;['search', 'from_date', 'to_date', 'payment_status', 'paid_state', 'min_amount', 'max_amount', 'is_return', 'created_by', 'edited_by', 'assigned_staff'].forEach((k) => next.delete(k))
    next.set('date', todayISO)
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
      row.device_model ? `Device: ${row.device_model}` : '',
      resolveImeiValue(row) ? `IMEI: ${resolveImeiValue(row)}` : '',
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
    let phoneRaw = row.phone_number || ''
    try {
      const contact = await api
        .get<WhatsAppContactResponse>(`/billing/debtors/${encodeURIComponent(row.client_name)}/whatsapp-contact`)
        .then((r) => r.data)
      if (!contact?.requires_manual_entry && contact?.phone_number) {
        phoneRaw = contact.phone_number
      }
    } catch {
      // Fallback to row phone if contact lookup fails.
    }

    const phone = normalizePhone(phoneRaw)
    if (!phone) {
      toast.error('No client phone number found')
      return
    }

    let billText = generateBillText(row)
    try {
      const payments = await api.get<PaymentHistoryRow[]>('/payments', { params: { service_job_id: row.id } }).then((r) => r.data)
      if (payments?.length) {
        const latest = payments[0]
        const latestRef = latest.reference_no || latest.id.slice(0, 8)
        billText += `\nLast Payment Ref: ${latestRef}`
        const recentLines = payments.slice(0, 3).map((p) => {
          const pRef = p.reference_no || p.id.slice(0, 8)
          const pAmt = Number(p.payment_amount ?? p.amount ?? 0)
          const pDate = String(p.payment_date || p.created_at || '').slice(0, 10)
          return `${pDate} ${pRef} ${formatCurrency(pAmt, currency)}`
        })
        if (recentLines.length) {
          billText += `\nRecent Payments:\n${recentLines.join('\n')}`
        }
      }
    } catch {
      // Bill generation should still proceed with available invoice totals.
    }

    const text = encodeURIComponent(billText)
    const popup = window.open(`https://wa.me/${phone}?text=${text}`, '_blank', 'noopener,noreferrer')
    if (!popup) {
      toast.error('Unable to open WhatsApp. Please allow popups and try again.')
      return
    }
    try {
      await whatsappTrackMutation.mutateAsync({ clientName: row.client_name, phoneNumber: phoneRaw })
      qc.invalidateQueries({ queryKey: ['billing-client-quick-view'] })
      toast.success('Bill opened in WhatsApp')
    } catch {
      toast.error('Bill opened, but send tracking failed')
    }
  }

  const copyBill = async (row: BillingRow) => {
    try {
      await navigator.clipboard.writeText(generateBillText(row))
      toast.success('Bill copied')
    } catch {
      toast.error('Unable to copy bill')
    }
  }

  const openReversePayment = (row: BillingRow) => {
    setReversePayRow(row)
    setReversePayAmount('')
    setReversePayReason('')
    setReversePayIdempotencyKey(buildIdempotencyKey('payment-reverse'))
  }

  const hasActiveFilters = !!(search || rangeFrom || rangeTo || statusFilter || paidState || minAmount || maxAmount || returned || createdBy || editedBy || assignedStaff)
  const allRows = useMemo(
    () => flatRows.filter((entry): entry is Extract<FlatBillingEntry, { kind: 'item' }> => entry.kind === 'item').map((entry) => entry.row),
    [flatRows]
  )

  const todayJobs = useMemo(
    () => allRows.filter((row) => String(row.service_date || row.invoice_date || '').slice(0, 10) === todayISO).length,
    [allRows, todayISO]
  )

  const devicesDelivered = useMemo(
    () => allRows.filter((row) => String(row.status || '').toUpperCase() === 'PAID').length,
    [allRows]
  )

  const pendingJobs = useMemo(
    () => allRows.filter((row) => {
      const st = String(row.status || '').toUpperCase()
      return st === 'UNPAID' || st === 'PART PAYMENT'
    }).length,
    [allRows]
  )

  const partPaymentCount = useMemo(
    () => allRows.filter((row) => String(row.status || '').toUpperCase() === 'PART PAYMENT').length,
    [allRows]
  )

  const devicesAwaitingPickup = useMemo(
    () => allRows.filter((row) => {
      const pickup = String((row as any).pickup_status || (row as any).delivery_status || '').toUpperCase()
      if (!pickup) return false
      return pickup !== 'PICKED_UP' && pickup !== 'DELIVERED'
    }).length,
    [allRows]
  )

  const refreshBillingView = () => {
    qc.invalidateQueries({ queryKey: ['billing-grouped'] })
    qc.invalidateQueries({ queryKey: ['billing-client-quick-view'] })
    qc.invalidateQueries({ queryKey: ['invoice-payments'] })
  }

  const openNewInvoice = () => {
    setEditRow(null)
    setClientSearch('')
    setSelectedClientId('')
    setShowClientDropdown(false)
    reset({
      client_name: '',
      client_phone: '',
      service_name: '',
      device_model: '',
      description: '',
      imei: '',
      serial_number: '',
      condition: '',
      lock_status: '',
      payment_status: 'UNPAID',
      quantity: 1,
      unit_price: 0,
      amount_paid: 0,
      service_expense: 0,
      invoice_date: new Date().toISOString().slice(0, 10),
      due_date: '',
      notes: '',
    } as FormValues)
    setShowForm(true)
  }

  const highlightMatch = (text?: string) => {
    const value = String(text || '')
    if (!normalizedSearch) return value || '—'
    const escaped = normalizedSearch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (!escaped) return value || '—'
    const regex = new RegExp(`(${escaped})`, 'ig')
    const parts = value.split(regex)
    if (parts.length <= 1) return value || '—'
    return (
      <>
        {parts.map((part, idx) => (
          part.toLowerCase() === normalizedSearch.toLowerCase()
            ? <mark key={`${part}-${idx}`} className="bg-amber-100 text-amber-900 px-0.5 rounded">{part}</mark>
            : <span key={`${part}-${idx}`}>{part}</span>
        ))}
      </>
    )
  }

  const statusChips = [
    { label: 'All', value: '' },
    { label: 'Paid', value: 'PAID' },
    { label: 'Part Payment', value: 'PART PAYMENT' },
    { label: 'Unpaid', value: 'UNPAID' },
    { label: 'Returned', value: 'RETURNED' },
  ]

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-full bg-[#f5f6f4] p-3 md:p-4 space-y-3">

      <section className="rounded-xl border border-[#e7d89f] bg-white px-4 py-3">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <h1 className="text-lg md:text-xl font-semibold text-[#151515]">Services & Billing</h1>
            <p className="text-[11px] text-gray-500">Manage sales, repairs and customer payments</p>
          </div>

          <div className="flex w-full flex-col gap-2 sm:flex-row xl:w-auto">
            <div className="relative min-w-[300px] flex-1 xl:min-w-[360px]">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                className="h-9 w-full rounded-lg border border-[#e7d89f] bg-white pl-9 pr-9 text-sm text-gray-800"
                placeholder="Search client, phone, IMEI, device, invoice, notes"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
              />
              {!!searchInput && (
                <button type="button" title="Clear" className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700" onClick={() => setSearchInput('')}>
                  <X size={14} />
                </button>
              )}
            </div>

            <button type="button" title="Refresh" className="inline-flex h-9 items-center gap-2 rounded-lg border border-[#e7d89f] bg-white px-3 text-xs font-semibold text-gray-700 hover:bg-[#fff8e1]" onClick={refreshBillingView}>
              <RefreshCcw size={14} /> Refresh
            </button>
            <button type="button" title="Filters" className="inline-flex h-9 items-center gap-2 rounded-lg border border-[#e7d89f] bg-white px-3 text-xs font-semibold text-gray-700 hover:bg-[#fff8e1]" onClick={() => setShowAdvancedFilters((prev) => !prev)}>
              <Filter size={14} /> Filter
            </button>
            <button type="button" className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#d4af37] px-3 text-xs font-bold text-[#101010] hover:bg-[#e4bf4b]" onClick={openNewInvoice}>
              <Plus size={14} /> New Invoice
            </button>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-2 lg:grid-cols-3 xl:grid-cols-6">
        <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
          <p className="text-[10px] uppercase tracking-wide text-gray-500">Services Today</p>
          <p className="text-base font-semibold text-gray-900">{todayJobs}</p>
        </div>
        {isAdmin && (
          <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
            <p className="text-[10px] uppercase tracking-wide text-gray-500">Revenue Today</p>
            <p className="text-base font-semibold text-gray-900">{formatCurrency(totalSummary.totalAmount, currency)}</p>
          </div>
        )}
        {isAdmin && (
          <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
            <p className="text-[10px] uppercase tracking-wide text-gray-500">Collected Today</p>
            <p className="text-base font-semibold text-emerald-700">{formatCurrency(totalSummary.totalPaid, currency)}</p>
          </div>
        )}
        {isAdmin && (
          <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
            <p className="text-[10px] uppercase tracking-wide text-gray-500">Outstanding Balance</p>
            <p className="text-base font-semibold text-amber-700">{formatCurrency(totalSummary.totalOutstanding, currency)}</p>
          </div>
        )}
        <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
          <p className="text-[10px] uppercase tracking-wide text-gray-500">Active Debtors</p>
          <p className="text-base font-semibold text-gray-900">{activeDebtorsCount}</p>
        </div>
        {isAdmin && (
          <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
            <p className="text-[10px] uppercase tracking-wide text-gray-500">Awaiting Pickup</p>
            <p className="text-base font-semibold text-gray-900">{devicesAwaitingPickup}</p>
          </div>
        )}
        {!isAdmin && (
          <>
            <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Awaiting Pickup</p>
              <p className="text-base font-semibold text-gray-900">{devicesAwaitingPickup}</p>
            </div>
            <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Devices Delivered</p>
              <p className="text-base font-semibold text-emerald-700">{devicesDelivered}</p>
            </div>
            <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Pending Jobs</p>
              <p className="text-base font-semibold text-amber-700">{pendingJobs}</p>
            </div>
            <div className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-2 shadow-sm">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Part Payments</p>
              <p className="text-base font-semibold text-amber-700">{partPaymentCount}</p>
            </div>
          </>
        )}
      </section>

      <section className="rounded-xl border border-[#d4af37]/35 bg-white px-3 py-3 shadow-sm space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          {statusChips.map((chip) => {
            const active = (statusFilter || '') === chip.value
            return (
              <button
                key={chip.label}
                type="button"
                onClick={() => setParam('payment_status', chip.value)}
                className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${active ? 'bg-[#111] text-white border-[#111]' : 'bg-white text-gray-700 border-[#e7d89f] hover:bg-[#fff7de]'}`}
              >
                {chip.label}
              </button>
            )
          })}
          <button type="button" className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${!isRangeMode ? 'bg-[#111] text-white border-[#111]' : 'bg-white text-gray-700 border-[#e7d89f] hover:bg-[#fff7de]'}`} onClick={() => applyQuickRange('today')}>Today</button>
          <button type="button" className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${activeRange === 'week' ? 'bg-[#111] text-white border-[#111]' : 'bg-white text-gray-700 border-[#e7d89f] hover:bg-[#fff7de]'}`} onClick={() => applyQuickRange('week')}>This Week</button>
          <button type="button" className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${activeRange === 'month' ? 'bg-[#111] text-white border-[#111]' : 'bg-white text-gray-700 border-[#e7d89f] hover:bg-[#fff7de]'}`} onClick={() => applyQuickRange('month')}>This Month</button>
          <button type="button" className="ml-auto rounded-full border border-[#e7d89f] px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-[#fff7de]" onClick={() => shiftDay(-1)}>Previous Day</button>
          <input type="date" className="h-8 rounded-full border border-[#e7d89f] px-3 text-xs" value={selectedDate} onChange={(e) => applySingleDay(e.target.value)} />
          <button type="button" className="rounded-full border border-[#e7d89f] px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-[#fff7de]" onClick={() => shiftDay(1)}>Next Day</button>
          {hasActiveFilters && (
            <button type="button" className="rounded-full border border-[#e7d89f] px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-[#fff7de]" onClick={clearFilters}>Clear</button>
          )}
        </div>

        <p className="text-xs text-gray-500">{isRangeMode ? `Range: ${rangeFrom} to ${rangeTo}` : `Selected date: ${labelForDate(selectedDate)} (${selectedDate})`}</p>

        {showAdvancedFilters && (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 border-t pt-2" style={{ borderColor: '#f1e7bf' }}>
            <input type="date" className="form-input py-1.5 text-xs" value={rangeFrom} onChange={(e) => setParam('from_date', e.target.value)} placeholder="From date" />
            <input type="date" className="form-input py-1.5 text-xs" value={rangeTo} onChange={(e) => setParam('to_date', e.target.value)} placeholder="To date" />
            <select className="form-input py-2 text-xs" value={statusFilter} onChange={(e) => setParam('payment_status', e.target.value)}>
              <option value="">Payment status</option>
              <option value="PAID">PAID</option>
              <option value="PART PAYMENT">PART PAYMENT</option>
              <option value="UNPAID">UNPAID</option>
              <option value="RETURNED">RETURNED</option>
            </select>
            <select className="form-input py-2 text-xs" value={returned} onChange={(e) => setParam('is_return', e.target.value)}>
              <option value="">Return status</option>
              <option value="false">Not returned</option>
              <option value="true">Returned</option>
            </select>
            {isAdmin && (
              <select className="form-input py-2 text-xs" value={createdBy} onChange={(e) => setParam('created_by', e.target.value)}>
                <option value="">Created by</option>
                {userOptions.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
              </select>
            )}
            {isAdmin && (
              <select className="form-input py-2 text-xs" value={editedBy} onChange={(e) => setParam('edited_by', e.target.value)}>
                <option value="">Edited by</option>
                {userOptions.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
              </select>
            )}
            {isAdmin && (
              <select className="form-input py-2 text-xs" value={assignedStaff} onChange={(e) => setParam('assigned_staff', e.target.value)}>
                <option value="">Assigned staff</option>
                {userOptions.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
              </select>
            )}
            {isAdmin && <input type="number" min="0" className="form-input py-1.5 text-xs" placeholder="Min amount" value={minAmount} onChange={(e) => setParam('min_amount', e.target.value)} />}
            {isAdmin && <input type="number" min="0" className="form-input py-1.5 text-xs" placeholder="Max amount" value={maxAmount} onChange={(e) => setParam('max_amount', e.target.value)} />}
          </div>
        )}
      </section>

      {isLoading ? (
        <section className="rounded-xl border border-[#e7d89f] bg-white p-4 space-y-2">
          {Array.from({ length: 6 }).map((_, idx) => (
            <div key={idx} className="h-11 animate-pulse rounded-lg bg-[#f7f2df]" />
          ))}
        </section>
      ) : (
        <div className="space-y-2">
          {flatRows.length === 0 && (
            <section className="rounded-xl border border-[#e7d89f] bg-white p-10 text-center">
              <p className="text-sm font-semibold text-gray-700">No transactions found</p>
              <p className="text-xs text-gray-500 mt-1">Try clearing filters or adjusting your search query.</p>
            </section>
          )}

          {flatRows.length > 0 && (
            <section className={`overflow-hidden rounded-xl border border-[#e7d89f] bg-white ${
              tableMotion === 'left'
                ? 'billing-table-enter-left'
                : tableMotion === 'right'
                  ? 'billing-table-enter-right'
                  : tableMotion === 'fade'
                    ? 'billing-table-enter-fade'
                    : ''
            }`}>
              <div className="hidden md:block max-h-[76vh] overflow-y-auto">
                <div className="sticky top-0 z-30 grid grid-cols-[56px_1.25fr_1.9fr_0.95fr_0.95fr_0.95fr_1fr_0.95fr_240px] items-center gap-2 border-b border-[#eadca9] bg-[#121212] px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-[#f4dea5]">
                  <span>S/N</span>
                  <span>Client</span>
                  <span>Description</span>
                  <span>Payment Status</span>
                  <span>Amount</span>
                  <span>Balance</span>
                  <span>Staff</span>
                  <span>Date</span>
                  <span className="text-center">Actions</span>
                </div>

                {flatRows.slice(0, visibleCount).map((entry, idx) => {
                  if (entry.kind === 'separator') {
                    return (
                      <div key={entry.key} className="sticky top-[40px] z-20 border-y border-[#f1e7bf] bg-[#fffaf0] px-4 py-1 text-xs font-medium text-gray-700">
                        {labelForDate(entry.group.service_date)}
                      </div>
                    )
                  }

                  const row = entry.row
                  const expanded = expandedRows.has(row.id)
                  const isRevealedRow = revealStartIndex != null && revealEndIndex != null && idx >= revealStartIndex && idx < revealEndIndex
                  const revealDelay = revealStartIndex == null ? 0 : Math.min((idx - revealStartIndex) * 14, 180)
                  const battery = (row as any).battery_health ? `${(row as any).battery_health}%` : 'N/A'
                  const zebraClass = idx % 2 === 0 ? 'bg-white' : 'bg-[#fffdfa]'
                  const notesExpanded = expandedNotesRows.has(row.id)

                  return (
                    <div key={entry.key} className={`border-b border-[#f7f1d8] ${isRevealedRow ? 'billing-row-stagger-enter' : ''}`} style={{ animationDelay: isRevealedRow ? `${revealDelay}ms` : undefined }}>
                      <div className={`grid cursor-pointer grid-cols-[56px_1.25fr_1.9fr_0.95fr_0.95fr_0.95fr_1fr_0.95fr_240px] items-center gap-2 px-3 py-2 text-xs transition ${zebraClass} hover:bg-[#fff5d9]`} onClick={() => toggleRow(row.id)}>
                        <span className="font-semibold text-gray-500">{idx + 1}</span>
                        <div className="min-w-0">
                          <button type="button" className="max-w-full truncate text-left font-semibold text-[#234d87] hover:underline" title={row.client_name} onClick={(e) => { e.stopPropagation(); setClientQuickViewName(row.client_name) }}>
                            {highlightMatch(row.client_name)}
                          </button>
                          <p className="truncate text-[11px] text-gray-500">{highlightMatch(row.phone_number) || 'No phone'}</p>
                        </div>
                        <div className="min-w-0 leading-tight">
                          <p className="truncate text-[12px] font-semibold text-gray-900">{highlightMatch(row.device_model || row.service_name || '—')}</p>
                          <p className="truncate text-[11px] text-gray-500">{String((row as any).storage || 'N/A')} • {String((row as any).color || 'N/A')}</p>
                          <p className="truncate text-[11px] text-gray-500">Battery {battery}</p>
                          <p className="truncate text-[11px] text-gray-400">IMEI: {highlightMatch(imeiText(row))}</p>
                        </div>
                        <span className={operationStatusClass(row.status)}>{statusLabel(row.status)}</span>
                        <p className="tabular-nums font-semibold text-gray-800">{formatCurrency(Number(row.total_amount || 0), currency)}</p>
                        <p className={`tabular-nums font-semibold ${Number(row.balance || 0) > 0 ? 'text-amber-700' : 'text-gray-500'}`}>{formatCurrency(Number(row.balance || 0), currency)}</p>
                        <p className="truncate text-gray-600">{row.assigned_staff_name || row.created_by_name || 'Unassigned'}</p>
                        <p className="text-gray-600">{String(row.service_date || row.invoice_date || '').slice(0, 10) || '—'}</p>
                        <div className="relative flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                          <button type="button" title="Apply Payment" className="rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700 hover:bg-[#fff7de]" onClick={() => openApplyPayment(row)}>Apply Payment</button>
                          <button type="button" title="Send Bill" className="rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700 hover:bg-[#fff7de]" onClick={() => { void openWhatsApp(row) }}>Send Bill</button>
                          <button type="button" title="History" className="rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700 hover:bg-[#fff7de]" onClick={() => toggleRow(row.id)}>History</button>
                          <button type="button" title="More" className="inline-flex items-center gap-1 rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700 hover:bg-[#fff7de]" onClick={() => setActionMenuRowId((prev) => prev === row.id ? null : row.id)}>
                            More <ChevronDown size={12} />
                          </button>
                          {actionMenuRowId === row.id && (
                            <div className="absolute right-0 top-[calc(100%+4px)] z-40 w-40 rounded-md border border-[#e7d89f] bg-white shadow-lg">
                              <button type="button" className="block w-full px-3 py-2 text-left text-[11px] hover:bg-[#fff7de]" onClick={() => { setActionMenuRowId(null); setPaymentQuickViewRow(row) }}>View Ledger</button>
                              <button type="button" className="block w-full px-3 py-2 text-left text-[11px] hover:bg-[#fff7de]" onClick={() => { setActionMenuRowId(null); void copyBill(row) }}>Copy Bill</button>
                              <button type="button" className="block w-full px-3 py-2 text-left text-[11px] hover:bg-[#fff7de]" onClick={() => { setActionMenuRowId(null); void openEdit(row) }}>Edit</button>
                              {isAdmin && <button type="button" className="block w-full px-3 py-2 text-left text-[11px] text-amber-800 hover:bg-amber-50" onClick={() => { setActionMenuRowId(null); openReversePayment(row) }}>Reverse Payment</button>}
                              {row.status !== 'RETURNED' && <button type="button" className="block w-full px-3 py-2 text-left text-[11px] text-amber-800 hover:bg-amber-50" onClick={() => { setActionMenuRowId(null); if (confirm('Mark as returned?')) markReturnedMutation.mutate(row.id) }}>Mark Returned</button>}
                              {isAdmin && <button type="button" className="block w-full px-3 py-2 text-left text-[11px] text-red-700 hover:bg-red-50" onClick={() => { setActionMenuRowId(null); if (confirm('Delete invoice?')) deleteMutation.mutate(row.id) }}>Delete</button>}
                            </div>
                          )}
                        </div>
                      </div>

                      {expanded && (
                        <div className="space-y-3 border-t border-[#f1e7bf] bg-[#fffdf7] px-4 py-3 text-xs" onClick={(e) => e.stopPropagation()}>
                          <div className="grid gap-3 lg:grid-cols-4">
                            <div className="rounded-lg border border-[#efdca5] bg-white p-2">
                              <p className="text-[10px] font-semibold tracking-wide text-[#866b2f]">DEVICE INFORMATION</p>
                              <p className="mt-1 text-gray-700">Device Name: <strong>{row.device_model || row.service_name || '—'}</strong></p>
                              <p className="text-gray-700">IMEI: <strong>{imeiText(row)}</strong></p>
                              <p className="text-gray-700">Serial Number: <strong>{resolveSerial(row)}</strong></p>
                              <p className="text-gray-700">Storage: <strong>{String((row as any).storage || '—')}</strong></p>
                              <p className="text-gray-700">Color: <strong>{String((row as any).color || '—')}</strong></p>
                              <p className="text-gray-700">Battery Health: <strong>{(row as any).battery_health ? `${(row as any).battery_health}%` : '—'}</strong></p>
                              <p className="text-gray-700">Lock Status: <strong>{row.lock_status || '—'}</strong></p>
                            </div>

                            <div className="rounded-lg border border-[#efdca5] bg-white p-2">
                              <p className="text-[10px] font-semibold tracking-wide text-[#866b2f]">CLIENT INFORMATION</p>
                              <p className="mt-1 text-gray-700">Client Name: <strong>{row.client_name}</strong></p>
                              <p className="text-gray-700">Phone: <strong>{row.phone_number || '—'}</strong></p>
                              <p className="text-gray-700">Address: <strong>{String((row as any).client_address || '—')}</strong></p>
                            </div>

                            <div className="rounded-lg border border-[#efdca5] bg-white p-2">
                              <p className="text-[10px] font-semibold tracking-wide text-[#866b2f]">FINANCIAL INFORMATION</p>
                              <p className="mt-1 text-gray-700">Amount Charged: <strong>{formatCurrency(Number(row.total_amount || 0), currency)}</strong></p>
                              <p className="text-gray-700">Amount Paid: <strong>{formatCurrency(Number(row.amount_paid || 0), currency)}</strong></p>
                              <p className="text-gray-700">Outstanding: <strong>{formatCurrency(Number(row.balance || 0), currency)}</strong></p>
                              <p className="text-gray-700">Payment Status: <strong>{statusLabel(row.status)}</strong></p>
                            </div>

                            <div className="rounded-lg border border-[#efdca5] bg-white p-2">
                              <p className="text-[10px] font-semibold tracking-wide text-[#866b2f]">PAYMENT TIMELINE</p>
                              <div className="mt-1 space-y-1 border-l border-amber-200 pl-2">
                                <p className="text-gray-700">Invoice Created • {String(row.service_date || row.invoice_date || '').slice(0, 19).replace('T', ' ') || '—'}</p>
                                <p className="text-gray-700">Payment Applied • {String(row.last_payment_at || '').slice(0, 19).replace('T', ' ') || '—'}</p>
                                <p className="text-gray-700">WhatsApp Bill Sent • See WhatsApp History</p>
                                <p className="text-gray-700">Returned • {String(row.returned_at || '').slice(0, 19).replace('T', ' ') || '—'}</p>
                                <p className="text-gray-700">Edited • {String(row.last_edited_at || '').slice(0, 19).replace('T', ' ') || '—'}</p>
                              </div>
                            </div>
                          </div>

                          <div className="rounded-lg border border-[#efdca5] bg-white p-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[10px] font-semibold tracking-wide text-[#866b2f]">NOTES</p>
                              <button
                                type="button"
                                className="text-[10px] font-semibold text-[#866b2f] hover:underline"
                                onClick={() => setExpandedNotesRows((prev) => {
                                  const next = new Set(prev)
                                  if (next.has(row.id)) next.delete(row.id)
                                  else next.add(row.id)
                                  return next
                                })}
                              >
                                {notesExpanded ? 'Collapse' : 'Expand'}
                              </button>
                            </div>
                            <p className={`text-gray-700 ${notesExpanded ? '' : 'line-clamp-2'}`}>{row.notes || '—'}</p>
                          </div>

                          <div className="rounded-lg border border-[#efdca5] bg-white p-2">
                            <p className="text-[10px] font-semibold tracking-wide text-[#866b2f]">AUDIT LOG</p>
                            <div className="mt-1 space-y-1 text-gray-700">
                              <p>Created: <strong>{String(row.service_date || row.invoice_date || '').slice(0, 19).replace('T', ' ') || '—'}</strong></p>
                              <p>Edited: <strong>{String(row.last_edited_at || '').slice(0, 19).replace('T', ' ') || '—'}</strong></p>
                              <p>Paid: <strong>{String(row.last_payment_at || '').slice(0, 19).replace('T', ' ') || '—'}</strong></p>
                              <p>Returned: <strong>{String(row.returned_at || '').slice(0, 19).replace('T', ' ') || '—'}</strong></p>
                            </div>
                          </div>

                          <InvoicePaymentHistory invoiceId={row.id} currency={currency} />
                          <BillingWhatsAppHistory invoiceId={row.id} />
                          <BillingReturnHistory invoiceId={row.id} />
                        </div>
                      )}
                    </div>
                  )
                })}

                {visibleCount < flatRows.length && (
                  <div ref={loadMoreRef} className="px-4 py-3 text-center text-xs text-gray-400">Loading more rows...</div>
                )}
              </div>

              <div className="md:hidden max-h-[76vh] overflow-y-auto space-y-2 p-2">
                {flatRows.slice(0, visibleCount).map((entry, idx) => {
                  if (entry.kind === 'separator') {
                    return (
                      <div key={entry.key} className="sticky top-0 z-20 rounded border bg-[#fffaf0] px-3 py-1 text-xs font-medium text-gray-600" style={{ borderColor: '#f1e7bf' }}>
                        {labelForDate(entry.group.service_date)}
                      </div>
                    )
                  }
                  const row = entry.row
                  const expanded = expandedRows.has(row.id)
                  return (
                    <div key={entry.key} className={`rounded-lg border bg-white ${idx % 2 === 0 ? '' : 'bg-[#fffdfa]'}`} style={{ borderColor: '#f1e7bf' }}>
                      <div className="space-y-2 p-3" onClick={() => toggleRow(row.id)}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-[#234d87]">{row.client_name}</p>
                            <p className="truncate text-xs text-gray-500">{row.phone_number || 'No phone'}</p>
                          </div>
                          <span className={operationStatusClass(row.status)}>{statusLabel(row.status)}</span>
                        </div>
                        <div className="text-xs">
                          <p className="truncate font-semibold text-gray-900">{row.device_model || row.service_name || '—'}</p>
                          <p className="truncate text-gray-600">IMEI: {imeiText(row)}</p>
                          <p className="truncate text-gray-500">Battery: {(row as any).battery_health ? `${(row as any).battery_health}%` : 'N/A'}</p>
                          <p className="mt-1 text-gray-700">Amount {formatCurrency(Number(row.total_amount || 0), currency)} • Paid {formatCurrency(Number(row.amount_paid || 0), currency)} • Bal {formatCurrency(Number(row.balance || 0), currency)}</p>
                        </div>
                        <div className="relative flex flex-wrap items-center gap-1" onClick={(e) => e.stopPropagation()}>
                          <button type="button" className="rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700" onClick={() => openApplyPayment(row)}>Apply Payment</button>
                          <button type="button" className="rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700" onClick={() => { void openWhatsApp(row) }}>Send Bill</button>
                          <button type="button" className="rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700" onClick={() => toggleRow(row.id)}>History</button>
                          <button type="button" className="inline-flex items-center gap-1 rounded border border-[#e7d89f] bg-white px-2 py-1 text-[11px] font-medium text-gray-700" onClick={() => setActionMenuRowId((prev) => prev === row.id ? null : row.id)}>
                            More <ChevronDown size={12} />
                          </button>
                          {actionMenuRowId === row.id && (
                            <div className="absolute right-0 top-[calc(100%+4px)] z-40 w-40 rounded-md border border-[#e7d89f] bg-white shadow-lg">
                              <button type="button" className="block w-full px-3 py-2 text-left text-[11px] hover:bg-[#fff7de]" onClick={() => { setActionMenuRowId(null); setPaymentQuickViewRow(row) }}>View Ledger</button>
                              <button type="button" className="block w-full px-3 py-2 text-left text-[11px] hover:bg-[#fff7de]" onClick={() => { setActionMenuRowId(null); void copyBill(row) }}>Copy Bill</button>
                              <button type="button" className="block w-full px-3 py-2 text-left text-[11px] hover:bg-[#fff7de]" onClick={() => { setActionMenuRowId(null); void openEdit(row) }}>Edit</button>
                              {isAdmin && <button type="button" className="block w-full px-3 py-2 text-left text-[11px] text-amber-800 hover:bg-amber-50" onClick={() => { setActionMenuRowId(null); openReversePayment(row) }}>Reverse Payment</button>}
                              {row.status !== 'RETURNED' && <button type="button" className="block w-full px-3 py-2 text-left text-[11px] text-amber-800 hover:bg-amber-50" onClick={() => { setActionMenuRowId(null); if (confirm('Mark as returned?')) markReturnedMutation.mutate(row.id) }}>Mark Returned</button>}
                              {isAdmin && <button type="button" className="block w-full px-3 py-2 text-left text-[11px] text-red-700 hover:bg-red-50" onClick={() => { setActionMenuRowId(null); if (confirm('Delete invoice?')) deleteMutation.mutate(row.id) }}>Delete</button>}
                            </div>
                          )}
                        </div>
                      </div>
                      {expanded && (
                        <div className="space-y-2 border-t border-[#f1e7bf] bg-[#fffdf7] p-3 text-xs">
                          <div className="rounded border border-[#efdca5] bg-white px-2 py-1"><p className="text-[10px] font-semibold text-[#866b2f]">DEVICE INFORMATION</p><p>{row.device_model || row.service_name || '—'}</p><p>IMEI: {imeiText(row)}</p><p>Battery Health: {(row as any).battery_health ? `${(row as any).battery_health}%` : '—'}</p></div>
                          <div className="rounded border border-[#efdca5] bg-white px-2 py-1"><p className="text-[10px] font-semibold text-[#866b2f]">CLIENT INFORMATION</p><p>{row.client_name}</p><p>{row.phone_number || '—'}</p></div>
                          <div className="rounded border border-[#efdca5] bg-white px-2 py-1"><p className="text-[10px] font-semibold text-[#866b2f]">FINANCIAL INFORMATION</p><p>Amount Charged: {formatCurrency(Number(row.total_amount || 0), currency)}</p><p>Amount Paid: {formatCurrency(Number(row.amount_paid || 0), currency)}</p><p>Outstanding: {formatCurrency(Number(row.balance || 0), currency)}</p></div>
                          <div className="rounded border border-[#efdca5] bg-white px-2 py-1"><p className="text-[10px] font-semibold text-[#866b2f]">NOTES</p><p>{row.notes || '—'}</p></div>
                          <div className="rounded border border-[#efdca5] bg-white px-2 py-1"><p className="text-[10px] font-semibold text-[#866b2f]">AUDIT LOG</p><p>Created: {String(row.service_date || row.invoice_date || '').slice(0, 19).replace('T', ' ') || '—'}</p><p>Edited: {String(row.last_edited_at || '').slice(0, 19).replace('T', ' ') || '—'}</p><p>Paid: {String(row.last_payment_at || '').slice(0, 19).replace('T', ' ') || '—'}</p><p>Returned: {String(row.returned_at || '').slice(0, 19).replace('T', ' ') || '—'}</p></div>
                          <InvoicePaymentHistory invoiceId={row.id} currency={currency} />
                          <BillingWhatsAppHistory invoiceId={row.id} />
                          <BillingReturnHistory invoiceId={row.id} />
                        </div>
                      )}
                    </div>
                  )
                })}
                {visibleCount < flatRows.length && <div ref={loadMoreRef} className="px-4 py-2 text-center text-xs text-gray-400">Loading more rows...</div>}
              </div>
            </section>
          )}

          <div className="flex items-center justify-end gap-2">
            <button disabled={page === 1} onClick={() => setParam('page', String(page - 1))} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page} of {groupedData?.total_pages ?? 1}</span>
            <button disabled={page >= (groupedData?.total_pages ?? 1)} onClick={() => setParam('page', String(page + 1))} className="btn-secondary">Next</button>
          </div>
        </div>
      )}

      {/* ── Client Quick View ── */}
      <Modal
        title="Client Quick View"
        open={!!clientQuickViewName}
        onClose={() => setClientQuickViewName(null)}
        size="md"
      >
        {!clientQuickViewName || clientQuickViewLoading ? (
          <LoadingSpinner />
        ) : !clientQuickView ? (
          <p className="text-sm text-gray-500">No client details found.</p>
        ) : (
          <div className="space-y-3 text-sm">
            <div className="rounded-lg border bg-gray-50 px-3 py-2" style={{ borderColor: '#e7d89f' }}>
              <p><span className="text-gray-500">Name:</span> <strong>{clientQuickView.client_name}</strong></p>
              <p><span className="text-gray-500">Phone:</span> {clientQuickView.phone_number || '—'}</p>
              <p><span className="text-gray-500">Total Jobs:</span> {clientQuickView.total_jobs}</p>
              <p><span className="text-gray-500">Unpaid Services:</span> {Number(clientQuickView.unpaid_services_count || 0)}</p>
              <p><span className="text-gray-500">Last Payment:</span> {clientQuickView.last_payment_date ? String(clientQuickView.last_payment_date).slice(0, 10) : '—'}</p>
              <p><span className="text-gray-500">Last WhatsApp:</span> {clientQuickView.last_whatsapp_sent_at ? String(clientQuickView.last_whatsapp_sent_at).slice(0, 19).replace('T', ' ') : '—'}</p>
              <p><span className="text-gray-500">WhatsApp Sends:</span> {Number(clientQuickView.whatsapp_sent_count || 0)}</p>
              <p>
                <span className="text-gray-500">Outstanding Balance:</span>{' '}
                {isAdmin
                  ? <strong className="text-amber-700">{formatCurrency(Number(clientQuickView.outstanding_balance || 0), currency)}</strong>
                  : <span className="text-gray-400">Restricted</span>}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-1">Recent Services</p>
              <div className="space-y-1">
                {clientQuickView.recent_services.map((item) => (
                  <div key={item.id} className="rounded border border-amber-100 bg-white px-2 py-1 text-xs">
                    <p className="font-medium text-gray-700">{item.service_name}</p>
                    <p className="text-gray-500">
                      {String(item.service_date || '').slice(0, 10) || 'Unknown date'}
                      {item.payment_status ? ` • ${item.payment_status}` : ''}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* ── Payment Quick View ── */}
      <Modal
        title="Payment History"
        open={!!paymentQuickViewRow}
        onClose={() => setPaymentQuickViewRow(null)}
        size="sm"
      >
        {paymentQuickViewRow && (
          <div className="space-y-3">
            <div className="rounded-lg border bg-gray-50 px-3 py-2 text-xs" style={{ borderColor: '#e7d89f' }}>
              <p><span className="text-gray-500">Client:</span> <strong>{paymentQuickViewRow.client_name}</strong></p>
              <p><span className="text-gray-500">Service:</span> {paymentQuickViewRow.service_name}</p>
              <p><span className="text-gray-500">IMEI:</span> {imeiText(paymentQuickViewRow)}</p>
              {isAdmin && <p><span className="text-gray-500">Balance:</span> <strong className="text-amber-700">{formatCurrency(Number(paymentQuickViewRow.balance || 0), currency)}</strong></p>}
            </div>
            <InvoicePaymentHistory invoiceId={paymentQuickViewRow.id} currency={currency} />
          </div>
        )}
      </Modal>

      {/* ── New / Edit Invoice Modal ── */}
      <Modal
        title={editRow ? 'Edit Invoice' : 'New Invoice'}
        open={showForm}
        onClose={closeForm}
        size="lg"
        bodyClassName="pb-2 max-h-[78vh]"
        footer={(
          <div className="flex justify-end gap-2 sticky bottom-0 bg-white py-1">
            <button type="button" className="btn-secondary" onClick={closeForm}>Cancel</button>
            <button type="submit" form="invoice-form" className="btn-primary" disabled={saveMutation.isPending || loadingEdit}>
              {loadingEdit ? 'Loading...' : saveMutation.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        )}
      >
        <form id="invoice-form" onKeyDown={handleInvoiceFormKeyDown} onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <input type="hidden" {...register('client_id')} />
          <div className="col-span-2 relative">
            <label className="form-label">Client Name</label>
            <input
              className="form-input"
              {...register('client_name', { required: 'Required' })}
              autoFocus
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
            <label className="form-label">Device Model</label>
            <input className="form-input" {...register('device_model')} />
          </div>
          <div>
            <label className="form-label">IMEI</label>
            <input className="form-input" {...register('imei')} />
          </div>
          <div>
            <label className="form-label">Serial Number</label>
            <input className="form-input" {...register('serial_number')} />
          </div>
          <div>
            <label className="form-label">Condition</label>
            <input className="form-input" {...register('condition')} placeholder="e.g. Used - Clean" />
          </div>
          <div>
            <label className="form-label">Lock Status</label>
            <input className="form-input" {...register('lock_status')} placeholder="e.g. Unlocked" />
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
          {isAdmin && (
            <div>
              <label className="form-label">Payment Status</label>
              <select className="form-input" {...register('payment_status')}>
                <option value="UNPAID">UNPAID</option>
                <option value="PART PAYMENT">PART PAYMENT</option>
                <option value="PAID">PAID</option>
                <option value="RETURNED">RETURNED</option>
              </select>
            </div>
          )}
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
            <label className="form-label">Description</label>
            <textarea className="form-input" rows={2} {...register('description')} />
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
        onClose={() => {
          setApplyPayRow(null)
          setApplyPayAmount('')
          setApplyPayMethod('cash')
          setApplyPayReference('')
          setApplyPayDate('')
          setApplyPayNotes('')
          setApplyPayIdempotencyKey('')
        }}
        size="sm"
        footer={(
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setApplyPayRow(null)
                setApplyPayAmount('')
                setApplyPayMethod('cash')
                setApplyPayReference('')
                setApplyPayDate('')
                setApplyPayNotes('')
                setApplyPayIdempotencyKey('')
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={applyPaymentMutation.isPending}
              onClick={() => {
                if (!applyPayRow) return
                if (!applyPayIdempotencyKey) { toast.error('Payment session expired. Reopen Apply Payment and try again.'); return }
                const val = parseFloat(applyPayAmount)
                if (!Number.isFinite(val) || val <= 0) { toast.error('Enter a valid payment amount'); return }
                if (val > Number(applyPayRow.balance || 0)) { toast.error('Payment cannot exceed outstanding balance'); return }
                applyPaymentMutation.mutate({ id: applyPayRow.id, amount: val })
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
              <label className="form-label">Payment Amount</label>
              <input
                type="number"
                min="0.01"
                step="0.01"
                className="form-input"
                value={applyPayAmount}
                onChange={(e) => setApplyPayAmount(e.target.value)}
                autoFocus
              />
              <p className="text-xs text-gray-400 mt-1">Enter incremental amount to add to this invoice.</p>
            </div>
            <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs space-y-1">
              <p className="font-medium text-gray-700">Allocation Preview</p>
              <p className="text-gray-500">{applyPayRow.service_name}</p>
              <p className="text-gray-700">
                Applying: <strong>{formatCurrency(Math.max(0, Math.min(Number(parseFloat(applyPayAmount || '0') || 0), Number(applyPayRow.balance || 0))), currency)}</strong>
              </p>
            </div>
            <div>
              <label className="form-label">Payment Method</label>
              <select className="form-input" value={applyPayMethod} onChange={(e) => setApplyPayMethod(e.target.value)}>
                <option value="cash">Cash</option>
                <option value="bank">Bank Transfer</option>
                <option value="mobile_money">Mobile Money</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label className="form-label">Reference No</label>
              <input className="form-input" value={applyPayReference} onChange={(e) => setApplyPayReference(e.target.value)} />
              <p className="text-xs text-gray-400 mt-1">Auto-generated but editable for operator overrides.</p>
            </div>
            <div>
              <label className="form-label">Payment Date</label>
              <input type="date" className="form-input" value={applyPayDate} onChange={(e) => setApplyPayDate(e.target.value)} />
            </div>
            <div>
              <label className="form-label">Payment Note</label>
              <textarea rows={2} className="form-input" value={applyPayNotes} onChange={(e) => setApplyPayNotes(e.target.value)} />
            </div>
          </div>
        )}
      </Modal>

      {/* ── Reverse Payment Modal ── */}
      <Modal
        title="Reverse Payment"
        open={!!reversePayRow}
        onClose={() => { setReversePayRow(null); setReversePayAmount(''); setReversePayReason(''); setReversePayIdempotencyKey('') }}
        size="sm"
        footer={(
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => { setReversePayRow(null); setReversePayAmount(''); setReversePayReason(''); setReversePayIdempotencyKey('') }}>Cancel</button>
            <button
              type="button"
              className="btn-primary"
              disabled={reversePaymentMutation.isPending}
              onClick={() => {
                if (!reversePayRow) return
                if (!reversePayIdempotencyKey) { toast.error('Reverse payment session expired. Reopen and try again.'); return }
                const val = parseFloat(reversePayAmount)
                const currentPaid = Number(reversePayRow.amount_paid || 0)
                if (!Number.isFinite(val) || val <= 0) {
                  toast.error('Enter a valid reversal amount')
                  return
                }
                if (val > currentPaid) {
                  toast.error('Reversal amount cannot exceed currently paid amount')
                  return
                }
                reversePaymentMutation.mutate({ id: reversePayRow.id, amount: val, reason: reversePayReason.trim() || undefined })
              }}
            >
              {reversePaymentMutation.isPending ? 'Saving...' : 'Reverse'}
            </button>
          </div>
        )}
      >
        {reversePayRow && (
          <div className="space-y-4">
            <div className="rounded-lg border bg-gray-50 px-4 py-3 text-sm space-y-1" style={{ borderColor: '#e7d89f' }}>
              <p><span className="text-gray-500">Client:</span> <strong>{reversePayRow.client_name}</strong></p>
              <p><span className="text-gray-500">Service:</span> {reversePayRow.service_name}</p>
              <p><span className="text-gray-500">Currently paid:</span> <span className="text-emerald-700 font-semibold">{formatCurrency(Number(reversePayRow.amount_paid || 0), currency)}</span></p>
            </div>
            <div>
              <label className="form-label">Reversal Amount</label>
              <input
                type="number"
                min="0"
                step="0.01"
                className="form-input"
                value={reversePayAmount}
                onChange={(e) => setReversePayAmount(e.target.value)}
                autoFocus
              />
            </div>
            <div>
              <label className="form-label">Reason (optional)</label>
              <textarea
                rows={2}
                className="form-input"
                value={reversePayReason}
                onChange={(e) => setReversePayReason(e.target.value)}
                placeholder="Reason for reversal"
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function InvoicePaymentHistory({ invoiceId, currency }: { invoiceId: string; currency: string }) {
  const { data, isLoading } = useQuery<PaymentHistoryRow[]>({
    queryKey: ['invoice-payments', invoiceId],
    queryFn: () => api.get('/payments', { params: { service_job_id: invoiceId } }).then((r) => r.data),
    enabled: !!invoiceId,
  })

  const rows = data ?? []
  return (
    <div className="rounded-md border border-amber-100 bg-white px-3 py-2">
      <p className="text-[11px] font-semibold text-gray-700 mb-1">Payment History</p>
      {isLoading ? (
        <p className="text-[11px] text-gray-400">Loading payment history...</p>
      ) : rows.length === 0 ? (
        <p className="text-[11px] text-gray-400">No payment transactions yet.</p>
      ) : (
        <div className="space-y-2 border-l border-amber-200 pl-3">
          {rows.slice(0, 10).map((payment) => {
            const amount = Number(payment.payment_amount ?? payment.amount ?? 0)
            const note = payment.payment_note || payment.notes || ''
            return (
              <div key={payment.id} className="relative flex items-start justify-between gap-4 text-[11px]">
                <span className="absolute -left-[14px] top-1.5 h-2 w-2 rounded-full bg-amber-500" />
                <div className="space-y-0.5">
                  <p className="font-medium text-gray-700">{payment.reference_no || payment.id.slice(0, 8)}</p>
                  <p className="text-gray-500">
                    {String(payment.payment_date || payment.created_at || '').slice(0, 19).replace('T', ' ')}
                    {payment.applied_by_name ? ` • ${payment.applied_by_name}` : ''}
                  </p>
                  <p className="text-gray-500">
                    {payment.payment_method || 'payment'}
                    {note ? ` • ${note}` : ''}
                    {payment.is_reversed ? ' • reversed' : ''}
                  </p>
                </div>
                <span className={`font-semibold ${amount < 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
                  {formatCurrency(amount, currency)}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function BillingWhatsAppHistory({ invoiceId }: { invoiceId: string }) {
  const { data, isLoading } = useQuery<{ items: BillingActivityRow[] }>({
    queryKey: ['billing-whatsapp-history', invoiceId],
    queryFn: () => api.get(`/billing/${invoiceId}/activity`, { params: { limit: 20 } }).then((r) => r.data),
    enabled: !!invoiceId,
  })

  const items = (data?.items ?? []).filter((item) => {
    const action = String(item.action || '').toLowerCase()
    return action.includes('whatsapp') || action.includes('bill_sent') || action.includes('send_bill')
  })

  return (
    <div className="rounded-md border border-amber-100 bg-white px-3 py-2">
      <p className="text-[11px] font-semibold text-gray-700 mb-1">WhatsApp History</p>
      {isLoading ? (
        <p className="text-[11px] text-gray-400">Loading WhatsApp history...</p>
      ) : items.length === 0 ? (
        <p className="text-[11px] text-gray-400">No WhatsApp activity recorded yet.</p>
      ) : (
        <div className="space-y-2 border-l border-amber-200 pl-3">
          {items.map((item) => {
            const label = String(item.action || '').replace(/_/g, ' ').toUpperCase() || 'EVENT'
            const when = String(item.created_at || '').slice(0, 19).replace('T', ' ')
            const detail = item.detail || {}
            const actor = detail.edited_by_name || detail.applied_by_name || detail.created_by_name || item.performed_by || ''
            return (
              <div key={item.id} className="relative flex items-start justify-between gap-4 text-[11px]">
                <span className="absolute -left-[14px] top-1.5 h-2 w-2 rounded-full bg-amber-500" />
                <div>
                  <p className="font-medium text-gray-700">{label}</p>
                  <p className="text-gray-500">{when}{actor ? ` • ${actor}` : ''}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function BillingReturnHistory({ invoiceId }: { invoiceId: string }) {
  const { data, isLoading } = useQuery<{ items: BillingActivityRow[] }>({
    queryKey: ['billing-return-history', invoiceId],
    queryFn: () => api.get(`/billing/${invoiceId}/activity`, { params: { limit: 20 } }).then((r) => r.data),
    enabled: !!invoiceId,
  })

  const items = (data?.items ?? []).filter((item) => {
    const action = String(item.action || '').toLowerCase()
    return action.includes('return') || action.includes('reversal')
  })

  return (
    <div className="rounded-md border border-amber-100 bg-white px-3 py-2">
      <p className="text-[11px] font-semibold text-gray-700 mb-1">Return History</p>
      {isLoading ? (
        <p className="text-[11px] text-gray-400">Loading return history...</p>
      ) : items.length === 0 ? (
        <p className="text-[11px] text-gray-400">No return activity recorded yet.</p>
      ) : (
        <div className="space-y-2 border-l border-amber-200 pl-3">
          {items.map((item) => {
            const label = String(item.action || '').replace(/_/g, ' ').toUpperCase() || 'EVENT'
            const when = String(item.created_at || '').slice(0, 19).replace('T', ' ')
            const detail = item.detail || {}
            const actor = detail.edited_by_name || detail.applied_by_name || detail.created_by_name || item.performed_by || ''
            return (
              <div key={item.id} className="relative flex items-start justify-between gap-4 text-[11px]">
                <span className="absolute -left-[14px] top-1.5 h-2 w-2 rounded-full bg-gray-500" />
                <div>
                  <p className="font-medium text-gray-700">{label}</p>
                  <p className="text-gray-500">{when}{actor ? ` • ${actor}` : ''}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
