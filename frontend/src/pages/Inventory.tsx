import { useState, useRef, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { buildIdempotencyKey } from '@/lib/idempotency'
import { Plus, Pencil, Trash2, ShoppingCart, History, RotateCcw, X, DollarSign } from 'lucide-react'
import toast from 'react-hot-toast'

const LOCK_STATUS_OPTIONS = ['Factory Unlocked', 'Carrier Locked', 'iCloud Locked', 'MDM Locked', 'Unknown']
const UNLOCK_METHOD_OPTIONS = ['RSIM', 'Official Unlock', 'Bypass', 'MDM Removal', 'Other']

function normalizeNigeriaPhone(raw: string): string {
  const digits = raw.replace(/\D/g, '')
  if (digits.startsWith('234') && digits.length >= 13) return digits
  if (digits.startsWith('0') && digits.length === 11) return '234' + digits.slice(1)
  return digits
}

interface StockItem {
  id: string
  item_name: string
  sku: string
  category: string
  quantity: number
  unit: string
  unit_cost: number
  unit_price?: number
  reorder_level: number
  supplier: string
  supplier_phone?: string
  supplier_contact?: string
  storage?: string
  color?: string
  payment_status?: string
  product_status?: string
  sold_out?: boolean
  condition?: string
  lock_status?: string
  previously_locked?: boolean
  unlock_method?: string
}

interface FormValues {
  item_name: string
  sku?: string
  category?: string
  description?: string
  quantity: number
  unit?: string
  unit_cost: number
  unit_price?: number
  reorder_level: number
  supplier?: string
  supplier_phone?: string
  supplier_contact?: string
  storage?: string
  color?: string
  location?: string
  product_status?: string
  condition?: string
  lock_status?: string
  previously_locked?: boolean
  unlock_method?: string
}

interface ClientSuggestion {
  id: string
  name: string
  phone?: string
  email?: string
  company?: string
  address?: string
  notes?: string
}

interface GroupRow {
  name: string
  product_count: number
}

interface InventoryTransaction {
  id: string
  action: string
  quantity_change: number
  quantity_before: number
  quantity_after: number
  related_sale_item_id?: string
  created_at: string
  performed_by?: string
  note?: string
}

type InventoryView = 'products' | 'pending_deals' | 'groups' | 'out_of_stock'
type CreateMode = 'single' | 'multiple'

interface CartItem extends StockItem {
  cart_quantity: number
  cart_unit_price: number
}

interface CheckoutFormValues {
  buyer_name: string
  buyer_phone?: string
  notes?: string
  amount_paid: number
  payment_method: string
  discount: number
  assigned_staff_name?: string
}

interface SellFormValues {
  quantity: number
  selling_price: number
  client_name: string
  client_phone?: string
  payment_status: string
  paid_amount: number
  notes?: string
}

interface InventorySaleHistoryRow {
  sale_item_id: string
  sale_id?: string
  service_job_id?: string
  quantity: number
  unit_price: number
  amount_charged: number
  paid_amount: number
  balance: number
  payment_status?: string
  client_name?: string
  client_phone?: string
  sold_at?: string
  sold_by?: string
  assigned_staff_name?: string
  created_by_name?: string
  is_reversed?: boolean
}

const CART_STORAGE_KEY = 'inventory-cart'

export default function Inventory() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [view, setView] = useState<InventoryView>('products')
  const [lowStock, setLowStock] = useState(false)
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [createMode, setCreateMode] = useState<CreateMode>('single')
  const [bulkInput, setBulkInput] = useState('')
  const [editRow, setEditRow] = useState<StockItem | null>(null)
  const [newGroupName, setNewGroupName] = useState('')
  const [editingGroup, setEditingGroup] = useState<GroupRow | null>(null)
  const [groupRenameValue, setGroupRenameValue] = useState('')
  const [historyItem, setHistoryItem] = useState<StockItem | null>(null)
  const [historyPage, setHistoryPage] = useState(1)
  const [sellItem, setSellItem] = useState<StockItem | null>(null)
  const [salesHistoryItem, setSalesHistoryItem] = useState<StockItem | null>(null)
  const [salesHistoryPage, setSalesHistoryPage] = useState(1)
  const [supplierQuery, setSupplierQuery] = useState('')
  const [showSupplierDropdown, setShowSupplierDropdown] = useState(false)
  const [showCart, setShowCart] = useState(false)
  const [cartClientQuery, setCartClientQuery] = useState('')
  const [showCartClientDropdown, setShowCartClientDropdown] = useState(false)
  const [sellClientQuery, setSellClientQuery] = useState('')
  const [showSellClientDropdown, setShowSellClientDropdown] = useState(false)
  const [cart, setCart] = useState<CartItem[]>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem(CART_STORAGE_KEY) || '[]')
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  })
  const supplierRef = useRef<HTMLDivElement>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['inventory', view, search, lowStock, category, page],
    queryFn: () =>
      api.get('/inventory', { params: { view, search, low_stock: lowStock, category: category || undefined, page, page_size: 50 } }).then((r) => r.data),
    enabled: view !== 'groups',
  })

  const { data: groupsData, isLoading: groupsLoading } = useQuery({
    queryKey: ['inventory-groups'],
    queryFn: () => api.get('/inventory/groups').then((r) => r.data),
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { register, handleSubmit, reset, setValue: setFormValue, watch: watchForm } = useForm<FormValues>()
  const {
    register: registerCheckout,
    handleSubmit: handleSubmitCheckout,
    reset: resetCheckout,
    watch: watchCheckout,
    setValue: setCheckoutValue,
  } = useForm<CheckoutFormValues>({
    defaultValues: {
      payment_method: 'cash',
      amount_paid: 0,
      discount: 0,
    },
  })
  const {
    register: registerSell,
    handleSubmit: handleSubmitSell,
    reset: resetSell,
    watch: watchSell,
    setValue: setSellValue,
  } = useForm<SellFormValues>({
    defaultValues: {
      quantity: 1,
      selling_price: 0,
      payment_status: 'UNPAID',
      paid_amount: 0,
    },
  })

  const groups: GroupRow[] = groupsData?.groups ?? []
  const cartCount = useMemo(() => cart.reduce((sum, item) => sum + Number(item.cart_quantity || 0), 0), [cart])
  const cartSubtotal = useMemo(() => cart.reduce((sum, item) => sum + Number(item.cart_quantity || 0) * Number(item.cart_unit_price || 0), 0), [cart])
  const checkoutDiscount = Math.min(Math.max(Number(watchCheckout('discount') || 0), 0), cartSubtotal)
  const checkoutTotal = Math.max(cartSubtotal - checkoutDiscount, 0)
  const checkoutPaid = Math.min(Math.max(Number(watchCheckout('amount_paid') || 0), 0), checkoutTotal)
  const checkoutBalance = Math.max(checkoutTotal - checkoutPaid, 0)
  const checkoutStatus = checkoutPaid <= 0 ? 'UNPAID' : checkoutPaid < checkoutTotal ? 'PART PAYMENT' : 'PAID'

  const previouslyLocked = watchForm('previously_locked')

  // Close supplier dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (supplierRef.current && !supplierRef.current.contains(e.target as Node)) {
        setShowSupplierDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(cart))
  }, [cart])

  const { data: clientSuggestions } = useQuery<{ items: ClientSuggestion[] }>({
    queryKey: ['clients-search', supplierQuery],
    queryFn: () => api.get('/clients', { params: { search: supplierQuery, page_size: 8 } }).then((r) => r.data),
    enabled: supplierQuery.trim().length >= 2,
    staleTime: 10_000,
  })

  const { data: cartClientSuggestions } = useQuery<{ items: ClientSuggestion[] }>({
    queryKey: ['cart-client-search', cartClientQuery],
    queryFn: () => api.get('/clients', { params: { search: cartClientQuery, page_size: 8 } }).then((r) => r.data),
    enabled: showCart && cartClientQuery.trim().length >= 2,
    staleTime: 10_000,
  })

  const { data: sellClientSuggestions } = useQuery<{ items: ClientSuggestion[] }>({
    queryKey: ['sell-client-search', sellClientQuery],
    queryFn: () => api.get('/clients', { params: { search: sellClientQuery, page_size: 8 } }).then((r) => r.data),
    enabled: !!sellItem && sellClientQuery.trim().length >= 2,
    staleTime: 10_000,
  })

  const { data: txData, isLoading: txLoading } = useQuery({
    queryKey: ['inventory-transactions', historyItem?.id, historyPage],
    queryFn: () =>
      api
        .get(`/inventory/${historyItem!.id}/transactions`, { params: { page: historyPage, page_size: 30 } })
        .then((r) => r.data),
    enabled: !!historyItem,
  })

  const { data: salesHistoryData, isLoading: salesHistoryLoading } = useQuery({
    queryKey: ['inventory-sales-history', salesHistoryItem?.id, salesHistoryPage],
    queryFn: () =>
      api
        .get(`/inventory/${salesHistoryItem!.id}/sales-history`, { params: { page: salesHistoryPage, page_size: 20 } })
        .then((r) => r.data),
    enabled: !!salesHistoryItem,
  })

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) => {
      const proposedSellingPrice = Number(values.unit_price)
      const payload = {
        item_name: values.item_name?.trim(),
        sku: values.sku?.trim() || undefined,
        category: values.category?.trim() || undefined,
        description: values.description?.trim() || undefined,
        quantity: Number(values.quantity ?? 0),
        unit: values.unit?.trim() || 'pcs',
        unit_cost: Number(values.unit_cost ?? 0),
        unit_price: Number.isFinite(proposedSellingPrice) ? proposedSellingPrice : undefined,
        reorder_level: Number(values.reorder_level ?? 0),
        supplier: values.supplier?.trim() || undefined,
        supplier_phone: values.supplier_phone?.trim() ? normalizeNigeriaPhone(values.supplier_phone.trim()) : undefined,
        supplier_contact: values.supplier_contact?.trim() || undefined,
        storage: values.storage?.trim() || undefined,
        color: values.color?.trim() || undefined,
        location: values.location?.trim() || undefined,
        payment_status: values.product_status?.trim() || undefined,
        condition: values.condition || undefined,
        lock_status: values.lock_status || undefined,
        previously_locked: values.previously_locked ?? false,
        unlock_method: values.previously_locked ? (values.unlock_method?.trim() || undefined) : undefined,
      }
      return editRow ? api.put(`/inventory/${editRow.id}`, payload) : api.post('/inventory', payload)
    },
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-groups'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false); setEditRow(null); reset()
      setSupplierQuery('')
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Save failed'),
  })

  const bulkMutation = useMutation({
    mutationFn: (items: FormValues[]) => api.post('/inventory/bulk', { items }),
    onSuccess: (res) => {
      toast.success(`Added ${res?.data?.inserted ?? 0} products`)
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-groups'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setBulkInput('')
      setShowForm(false)
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Bulk add failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/inventory/${id}`),
    onSuccess: () => {
      toast.success('Removed')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-groups'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Remove failed'),
  })

  const createGroupMutation = useMutation({
    mutationFn: (name: string) => api.post('/inventory/groups', { name }),
    onSuccess: () => {
      toast.success('Group created')
      setNewGroupName('')
      qc.invalidateQueries({ queryKey: ['inventory-groups'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Create group failed'),
  })

  const renameGroupMutation = useMutation({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      api.put(`/inventory/groups/${encodeURIComponent(oldName)}`, { new_name: newName }),
    onSuccess: () => {
      toast.success('Group updated')
      setEditingGroup(null)
      setGroupRenameValue('')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-groups'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Edit group failed'),
  })

  const assignGroupMutation = useMutation({
    mutationFn: ({ itemId, groupName }: { itemId: string; groupName: string }) =>
      api.post('/inventory/assign-group', { item_ids: [itemId], group_name: groupName }),
    onSuccess: () => {
      toast.success('Product assigned')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-groups'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Assign group failed'),
  })

  const checkoutMutation = useMutation({
    mutationFn: (values: CheckoutFormValues) => {
      if (!cart.length) throw new Error('Cart is empty')
      return api.post('/inventory/checkout', {
        items: cart.map((item) => ({
          item_id: item.id,
          quantity: Number(item.cart_quantity || 0),
          unit_price: Number(item.cart_unit_price || 0),
        })),
        buyer_name: values.buyer_name?.trim(),
        buyer_phone: values.buyer_phone?.trim() ? normalizeNigeriaPhone(values.buyer_phone.trim()) : undefined,
        notes: values.notes?.trim() || undefined,
        amount_paid: Number(values.amount_paid || 0),
        payment_method: values.payment_method || 'cash',
        discount: Number(values.discount || 0),
        assigned_staff_name: values.assigned_staff_name?.trim() || undefined,
        idempotency_key: buildIdempotencyKey('cart-checkout'),
      })
    },
    onSuccess: (res) => {
      toast.success(`Checkout complete: ${res?.data?.items?.length ?? cart.length} item(s) sold`)
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-transactions'] })
      qc.invalidateQueries({ queryKey: ['inventory-sales-history'] })
      qc.invalidateQueries({ queryKey: ['billing'] })
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
      setCart([])
      localStorage.removeItem(CART_STORAGE_KEY)
      setShowCart(false)
      setCartClientQuery('')
      resetCheckout({ payment_method: 'cash', amount_paid: 0, discount: 0 })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Checkout failed'),
  })

  const reverseSaleMutation = useMutation({
    mutationFn: (saleItemId: string) => api.post('/inventory/sales/reverse', { sale_item_id: saleItemId }),
    onSuccess: () => {
      toast.success('Sale reversed and stock restored')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-transactions'] })
      qc.invalidateQueries({ queryKey: ['inventory-sales-history'] })
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Reversal failed'),
  })

  const openEdit = (row: StockItem) => {
    setEditRow(row)
    setCreateMode('single')
    reset({
      ...row,
      product_status: row.product_status || row.payment_status || 'AVAILABLE',
      condition: row.condition || '',
      lock_status: row.lock_status || '',
      previously_locked: row.previously_locked ?? false,
      unlock_method: row.unlock_method || '',
    })
    setSupplierQuery(row.supplier || '')
    setShowForm(true)
  }

  const openSell = (row: StockItem) => {
    const defaultPrice = Number(row.unit_price || 0)
    setSellItem(row)
    setSellClientQuery('')
    setShowSellClientDropdown(false)
    resetSell({
      quantity: 1,
      selling_price: defaultPrice,
      client_name: '',
      client_phone: '',
      payment_status: 'UNPAID',
      paid_amount: 0,
      notes: '',
    })
  }

  const addToCart = (row: StockItem) => {
    const stockQty = Number(row.quantity || 0)
    if (stockQty <= 0) {
      toast.error('Item is out of stock')
      return
    }
    setCart((current) => {
      const existing = current.find((item) => item.id === row.id)
      if (existing) {
        if (Number(existing.cart_quantity || 0) >= stockQty) {
          toast.error(`Cannot add more than ${stockQty} in stock`)
          return current
        }
        return current.map((item) =>
          item.id === row.id
            ? { ...item, cart_quantity: Number(item.cart_quantity || 0) + 1 }
            : item,
        )
      }
      return [...current, { ...row, cart_quantity: 1, cart_unit_price: Number(row.unit_price || 0) }]
    })
    toast.success('Added to cart')
  }

  const updateCartQuantity = (itemId: string, quantity: number) => {
    setCart((current) =>
      current.flatMap((item) => {
        if (item.id !== itemId) return [item]
        const maxQty = Number(item.quantity || 0)
        const nextQty = Math.min(Math.max(Number(quantity || 0), 0), maxQty)
        return nextQty > 0 ? [{ ...item, cart_quantity: nextQty }] : []
      }),
    )
  }

  const updateCartPrice = (itemId: string, unitPrice: number) => {
    setCart((current) =>
      current.map((item) =>
        item.id === itemId ? { ...item, cart_unit_price: Math.max(Number(unitPrice || 0), 0) } : item,
      ),
    )
  }

  const removeFromCart = (itemId: string) => {
    setCart((current) => current.filter((item) => item.id !== itemId))
  }

  const openHistory = (row: StockItem) => {
    setHistoryItem(row)
    setHistoryPage(1)
  }

  const openSalesHistory = (row: StockItem) => {
    setSalesHistoryItem(row)
    setSalesHistoryPage(1)
  }

  const sellQuantity = Number(watchSell('quantity') || 0)
  const sellUnitPrice = Number(watchSell('selling_price') || 0)
  const sellAmountCharged = Math.max(sellQuantity * sellUnitPrice, 0)
  const sellPaidAmount = Math.min(Math.max(Number(watchSell('paid_amount') || 0), 0), sellAmountCharged)
  const sellBalance = Math.max(sellAmountCharged - sellPaidAmount, 0)

  const sellMutation = useMutation({
    mutationFn: (values: SellFormValues) => {
      if (!sellItem) throw new Error('No inventory item selected for sale')
      return api.post(`/inventory/${sellItem.id}/sell`, {
        quantity: Number(values.quantity || 0),
        selling_price: Number(values.selling_price || 0),
        client_name: values.client_name?.trim(),
        client_phone: values.client_phone?.trim() ? normalizeNigeriaPhone(values.client_phone.trim()) : undefined,
        payment_status: values.payment_status,
        paid_amount: Number(values.paid_amount || 0),
        notes: values.notes?.trim() || undefined,
      })
    },
    onSuccess: () => {
      toast.success('Item sold successfully')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-transactions'] })
      qc.invalidateQueries({ queryKey: ['inventory-sales-history'] })
      qc.invalidateQueries({ queryKey: ['billing'] })
      qc.invalidateQueries({ queryKey: ['billing-grouped'] })
      qc.invalidateQueries({ queryKey: ['debtors'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['cashflow-page-data'] })
      setSellItem(null)
      setSellClientQuery('')
      setShowSellClientDropdown(false)
      resetSell()
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Sell failed'),
  })

  const handleBulkSubmit = () => {
    try {
      const parsed = JSON.parse(bulkInput)
      if (!Array.isArray(parsed)) {
        throw new Error('Expected an array')
      }
      const items = parsed
        .map((item) => ({
          item_name: String(item.item_name ?? '').trim(),
          sku: item.sku ? String(item.sku) : undefined,
          category: item.category ? String(item.category) : undefined,
          description: item.description ? String(item.description) : undefined,
          quantity: Number(item.quantity ?? 0),
          unit: item.unit ? String(item.unit) : 'pcs',
          unit_cost: Number(item.unit_cost ?? 0),
          unit_price: Number(item.unit_price ?? 0),
          color: item.color ? String(item.color) : undefined,
          reorder_level: Number(item.reorder_level ?? 0),
          product_status: item.product_status ? String(item.product_status) : (item.payment_status ? String(item.payment_status) : undefined),
        }))
        .filter((item) => item.item_name)

      if (!items.length) {
        toast.error('No valid rows found in JSON array')
        return
      }
      bulkMutation.mutate(items as FormValues[])
    } catch {
      toast.error('Invalid JSON. Use an array of product objects.')
    }
  }

  const switchView = (nextView: InventoryView) => {
    setView(nextView)
    setPage(1)
  }

  const buildClientContactText = (client: ClientSuggestion): string => {
    const details = [client.phone, client.email, client.company].filter(Boolean)
    return details.length ? details.join(' • ') : 'No contact info'
  }

  const columns = [
    { key: 'item_name',    header: 'Item' },
    { key: 'sku',          header: 'SKU' },
    { key: 'category',     header: 'Category' },
    { key: 'storage',      header: 'Storage' },
    { key: 'color',        header: 'Color' },
    { key: 'quantity',     header: 'Qty',
      render: (r: StockItem) => (
        <span className={Number(r.quantity) <= Number(r.reorder_level) ? 'text-red-600 font-semibold' : ''}>
          {r.quantity} {r.unit}
        </span>
      )
    },
    { key: 'unit_price',   header: 'Proposed Price',  render: (r: StockItem) => formatCurrency(r.unit_price ?? 0, currency) },
    { key: 'reorder_level', header: 'Reorder' },
    {
      key: 'supplier_details',
      header: 'Supplier Details',
      render: (r: StockItem) => (
        <div className="text-xs leading-5">
          <div className="font-medium text-gray-800">{r.supplier || '—'}</div>
          {r.supplier_phone && <div className="text-gray-600">Phone: {r.supplier_phone}</div>}
          {r.supplier_contact && <div className="text-gray-600">Contact: {r.supplier_contact}</div>}
        </div>
      ),
    },
    {
      key: 'product_status',
      header: 'Status',
      render: (r: StockItem) => <span className="badge-partial">{r.product_status || 'AVAILABLE'}</span>,
    },
    {
      key: 'group',
      header: 'Group',
      render: (r: StockItem) => (
        <select
          className="form-input py-1 px-2 text-xs min-w-36"
          value={r.category || ''}
          onChange={(e) => {
            const groupName = e.target.value
            if (!groupName) return
            assignGroupMutation.mutate({ itemId: r.id, groupName })
          }}
        >
          <option value="">Unassigned</option>
          {groups.map((g) => (
            <option key={g.name} value={g.name}>{g.name}</option>
          ))}
        </select>
      ),
    },
    {
      key: 'actions', header: '',
      render: (r: StockItem) => (
        <div className="flex gap-2">
          <button
            onClick={() => openSell(r)}
            disabled={Number(r.quantity) <= 0}
            className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-emerald-700 disabled:opacity-40"
            title="Sell Item"
          >
            <DollarSign size={14} /> Sell
          </button>
          <button
            onClick={() => addToCart(r)}
            disabled={Number(r.quantity) <= 0}
            className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-emerald-700 disabled:opacity-40"
            title="Add to Cart"
          >
            <ShoppingCart size={14} /> Add to Cart
          </button>
          <button
            onClick={() => openSalesHistory(r)}
            className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-indigo-700"
            title="Sales History"
          >
            <History size={14} /> Sales History
          </button>
          <button onClick={() => openHistory(r)} className="text-gray-400 hover:text-blue-600" title="Transaction History"><History size={14} /></button>
          <button onClick={() => openEdit(r)} className="text-gray-400 hover:text-primary-600"><Pencil size={14} /></button>
          <button onClick={() => { if (confirm('Remove item?')) deleteMutation.mutate(r.id) }} className="text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Inventory</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCart(true)}
            className="btn-secondary relative"
          >
            <ShoppingCart size={15} /> Checkout / Sell Out
            {cartCount > 0 && (
              <span className="ml-1 rounded-full bg-black px-2 py-0.5 text-xs text-white">{cartCount}</span>
            )}
          </button>
          <button
            onClick={() => {
              setEditRow(null)
              setCreateMode('single')
              reset({ quantity: 1, unit: 'pcs', unit_cost: 0, reorder_level: 0, product_status: 'AVAILABLE', previously_locked: false })
              setSupplierQuery('')
              setShowForm(true)
            }}
            className="btn-primary"
          >
            <Plus size={15} /> Add Product
          </button>
        </div>
      </div>

      <div className="flex gap-2">
        <button className={view === 'products' ? 'btn-primary' : 'btn-secondary'} onClick={() => switchView('products')}>Products</button>
        <button className={view === 'pending_deals' ? 'btn-primary' : 'btn-secondary'} onClick={() => switchView('pending_deals')}>Pending Deals</button>
        <button className={view === 'groups' ? 'btn-primary' : 'btn-secondary'} onClick={() => switchView('groups')}>Groups</button>
        <button className={view === 'out_of_stock' ? 'btn-primary' : 'btn-secondary'} onClick={() => switchView('out_of_stock')}>Out of Stock</button>
      </div>

      {view !== 'groups' && (
        <div className="flex gap-3 items-center flex-wrap">
          <input
            className="form-input max-w-sm"
            placeholder="Search…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          />
          <select
            className="form-input max-w-xs"
            value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(1) }}
          >
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g.name} value={g.name}>{g.name}</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
            <input type="checkbox" checked={lowStock} onChange={(e) => setLowStock(e.target.checked)} className="rounded" />
            Low stock only
          </label>
        </div>
      )}

      {view !== 'groups' && (isLoading ? <LoadingSpinner /> : (
        <>
          <Table columns={columns as any} data={data?.items ?? data?.data ?? []} />
          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setPage((p) => p - 1)} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page} of {data?.total_pages ?? 1}</span>
            <button disabled={page >= (data?.total_pages ?? 1)} onClick={() => setPage((p) => p + 1)} className="btn-secondary">Next</button>
          </div>
        </>
      ))}

      {view === 'groups' && (
        <div className="space-y-4">
          <div className="flex gap-2 max-w-lg">
            <input
              className="form-input"
              placeholder="New group name"
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
            />
            <button
              className="btn-primary"
              onClick={() => createGroupMutation.mutate(newGroupName)}
              disabled={createGroupMutation.isPending}
            >
              Create Group
            </button>
          </div>

          {groupsLoading ? <LoadingSpinner /> : (
            <div className="card p-4">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left border-b">
                    <th className="py-2">Group</th>
                    <th className="py-2">Products</th>
                    <th className="py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.name} className="border-b last:border-b-0">
                      <td className="py-2">{g.name}</td>
                      <td className="py-2">{g.product_count}</td>
                      <td className="py-2">
                        <button
                          className="btn-secondary py-1 px-2 text-xs"
                          onClick={() => { setEditingGroup(g); setGroupRenameValue(g.name) }}
                        >
                          Edit
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <Modal
        title={editRow ? 'Edit Product' : 'Add Product'}
        open={showForm}
        onClose={() => { setShowForm(false); reset(); setSupplierQuery('') }}
        size="lg"
        bodyClassName="overflow-y-auto max-h-[70vh]"
        footer={
          (editRow || createMode === 'single') ? (
            <div className="flex justify-end gap-2 pt-3 border-t">
              <button type="button" className="btn-secondary" onClick={() => { setShowForm(false); reset(); setSupplierQuery('') }}>Cancel</button>
              <button type="submit" form="product-form" className="btn-primary" disabled={saveMutation.isPending}>
                {saveMutation.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          ) : (
            <div className="flex justify-end gap-2 pt-3 border-t">
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button>
              <button type="button" className="btn-primary" onClick={handleBulkSubmit} disabled={bulkMutation.isPending}>
                {bulkMutation.isPending ? 'Saving…' : 'Save Multiple'}
              </button>
            </div>
          )
        }
      >
        {!editRow && (
          <div className="flex gap-2 mb-4">
            <button className={createMode === 'single' ? 'btn-primary' : 'btn-secondary'} onClick={() => setCreateMode('single')} type="button">Single Product</button>
            <button className={createMode === 'multiple' ? 'btn-primary' : 'btn-secondary'} onClick={() => setCreateMode('multiple')} type="button">Multiple Products</button>
          </div>
        )}

        {(editRow || createMode === 'single') && (
          <form id="product-form" onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="space-y-4">
            {/* Basic Info */}
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="form-label">Item Name <span className="text-red-500">*</span></label>
                <input type="text" className="form-input" {...register('item_name', { required: 'Required' })} />
              </div>
              <div>
                <label className="form-label">SKU</label>
                <input type="text" className="form-input" {...register('sku')} />
              </div>
              <div>
                <label className="form-label">Group / Category</label>
                <input type="text" className="form-input" {...register('category')} />
              </div>
              <div>
                <label className="form-label">Quantity</label>
                <input type="number" step="0.01" className="form-input" {...register('quantity', { valueAsNumber: true })} />
              </div>
              <div>
                <label className="form-label">Unit</label>
                <input type="text" className="form-input" placeholder="pcs" {...register('unit')} />
              </div>
              <div>
                <label className="form-label">Unit Cost</label>
                <input type="number" step="0.01" className="form-input" {...register('unit_cost', { valueAsNumber: true })} />
              </div>
              <div>
                <label className="form-label">Proposed Selling Price</label>
                <input type="number" step="0.01" className="form-input" {...register('unit_price', { valueAsNumber: true })} />
              </div>
              <div>
                <label className="form-label">Reorder Level</label>
                <input type="number" step="0.01" className="form-input" {...register('reorder_level', { valueAsNumber: true })} />
              </div>
            </div>

            {/* Supplier / Contact */}
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mt-2">Supplier / Contact</p>
              <div className="grid grid-cols-3 gap-4">
                <div ref={supplierRef} className="relative">
                  <label className="form-label">Supplier / Contact</label>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Name or phone…"
                    value={supplierQuery}
                    onFocus={() => setShowSupplierDropdown(true)}
                    onChange={(e) => {
                      setSupplierQuery(e.target.value)
                      setFormValue('supplier', e.target.value)
                      setShowSupplierDropdown(true)
                    }}
                  />
                  {showSupplierDropdown && (clientSuggestions?.items ?? []).length > 0 && (
                    <ul className="absolute z-50 left-0 right-0 bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-48 overflow-y-auto text-sm">
                      {(clientSuggestions!.items as ClientSuggestion[]).map((c) => (
                        <li
                          key={c.id}
                          className="px-3 py-2 hover:bg-gray-50 cursor-pointer"
                          onMouseDown={() => {
                            setFormValue('supplier', c.name)
                            setFormValue('supplier_phone', c.phone ?? '')
                            setSupplierQuery(c.name)
                            setShowSupplierDropdown(false)
                          }}
                        >
                          <span className="font-medium">{c.name}</span>
                          {c.phone && <span className="ml-2 text-gray-400">{c.phone}</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <label className="form-label">Supplier Phone</label>
                  <input
                    type="tel"
                    className="form-input"
                    placeholder="080…  or  2348…"
                    {...register('supplier_phone')}
                  />
                </div>
                <div>
                  <label className="form-label">Supplier Contact</label>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Contact person"
                    {...register('supplier_contact')}
                  />
                </div>
              </div>
            </div>

            {/* Device Details */}
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mt-2">Device Details</p>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="form-label">Storage</label>
                  <input type="text" className="form-input" placeholder="e.g. 128GB" {...register('storage')} />
                </div>
                <div>
                  <label className="form-label">Color</label>
                  <input type="text" className="form-input" placeholder="e.g. Black" {...register('color')} />
                </div>
                <div>
                  <label className="form-label">Condition</label>
                  <input type="text" className="form-input" placeholder="e.g. Open Box" {...register('condition')} />
                </div>
                <div>
                  <label className="form-label">Lock Status</label>
                  <select className="form-input" {...register('lock_status')}>
                    <option value="">— Select —</option>
                    {LOCK_STATUS_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
              </div>

              <div className="flex items-center gap-3 mt-1">
                <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-gray-700">
                  <input type="checkbox" className="rounded" {...register('previously_locked')} />
                  Previously Locked
                </label>
              </div>

              {previouslyLocked && (
                <div>
                  <label className="form-label">Unlock Method</label>
                  <select className="form-input" {...register('unlock_method')}>
                    <option value="">— Select —</option>
                    {UNLOCK_METHOD_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
              )}
            </div>

            {/* Other */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="form-label">Location</label>
                <input type="text" className="form-input" {...register('location')} />
              </div>
              <div>
                <label className="form-label">Product Status</label>
                <select className="form-input" {...register('product_status')}>
                  <option value="AVAILABLE">AVAILABLE</option>
                  <option value="PENDING DEAL">PENDING DEAL</option>
                  <option value="SOLD">SOLD</option>
                </select>
              </div>
              <div className="col-span-2">
                <label className="form-label">Description</label>
                <textarea className="form-input" rows={2} {...register('description')} />
              </div>
            </div>
          </form>
        )}

        {!editRow && createMode === 'multiple' && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Paste a JSON array for bulk add. Example: [{'{"item_name":"IPHONE 14","category":"IPHONE","quantity":1,"unit_cost":500}'}]
            </p>
            <textarea
              className="form-input font-mono text-xs"
              rows={12}
              value={bulkInput}
              onChange={(e) => setBulkInput(e.target.value)}
              placeholder='[{"item_name":"IPHONE 14","category":"IPHONE","quantity":1,"unit_cost":500}]'
            />
          </div>
        )}
      </Modal>

      <Modal title="Edit Group" open={!!editingGroup} onClose={() => setEditingGroup(null)}>
        <div className="space-y-4">
          <div>
            <label className="form-label">Group Name</label>
            <input className="form-input" value={groupRenameValue} onChange={(e) => setGroupRenameValue(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setEditingGroup(null)}>Cancel</button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                if (!editingGroup) return
                renameGroupMutation.mutate({ oldName: editingGroup.name, newName: groupRenameValue })
              }}
              disabled={renameGroupMutation.isPending}
            >
              {renameGroupMutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        title="Inventory Cart"
        open={showCart}
        onClose={() => setShowCart(false)}
        size="lg"
        bodyClassName="overflow-y-auto max-h-[70vh]"
        footer={(
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setShowCart(false)}>Close</button>
            <button
              type="submit"
              form="inventory-checkout-form"
              className="btn-primary"
              disabled={checkoutMutation.isPending || cart.length === 0}
            >
              {checkoutMutation.isPending ? 'Processing...' : 'Checkout / Sell Out'}
            </button>
          </div>
        )}
      >
        <form
          id="inventory-checkout-form"
          className="space-y-4"
          onSubmit={handleSubmitCheckout((values) => {
            if (!cart.length) {
              toast.error('Cart is empty')
              return
            }
            const invalid = cart.find((item) => Number(item.cart_quantity || 0) > Number(item.quantity || 0))
            if (invalid) {
              toast.error(`Cannot oversell ${invalid.item_name}. Remaining quantity is ${invalid.quantity}`)
              return
            }
            checkoutMutation.mutate(values)
          })}
        >
          {cart.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
              No items in cart
            </div>
          ) : (
            <div className="space-y-2">
              {cart.map((item) => (
                <div key={item.id} className="grid grid-cols-[1fr_7rem_8rem_2rem] items-center gap-2 rounded-lg border border-gray-200 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-gray-900">{item.item_name}</p>
                    <p className="text-xs text-gray-500">Stock: {item.quantity} {item.unit || 'pcs'}</p>
                  </div>
                  <input
                    type="number"
                    min="0.01"
                    max={Number(item.quantity || 0)}
                    step="0.01"
                    className="form-input"
                    value={item.cart_quantity}
                    onChange={(e) => updateCartQuantity(item.id, Number(e.target.value))}
                  />
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className="form-input"
                    value={item.cart_unit_price}
                    onChange={(e) => updateCartPrice(item.id, Number(e.target.value))}
                  />
                  <button type="button" className="text-gray-400 hover:text-red-600" onClick={() => removeFromCart(item.id)} title="Remove item">
                    <X size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="relative">
              <label className="form-label">Buyer / Client Name</label>
              <input
                className="form-input"
                {...registerCheckout('buyer_name', { required: true })}
                value={cartClientQuery}
                onChange={(e) => {
                  setCartClientQuery(e.target.value)
                  setCheckoutValue('buyer_name', e.target.value)
                  setShowCartClientDropdown(true)
                }}
                onFocus={() => setShowCartClientDropdown(true)}
              />
              {showCartClientDropdown && cartClientQuery.trim() && (cartClientSuggestions?.items ?? []).length > 0 && (
                <div className="absolute z-20 mt-1 w-full rounded-lg border bg-white shadow-lg" style={{ borderColor: '#d4af37' }}>
                  {(cartClientSuggestions?.items ?? []).map((client) => (
                    <button
                      type="button"
                      key={client.id}
                      className="block w-full px-3 py-2 text-left text-sm hover:bg-[#fff9e7]"
                      onClick={() => {
                        setCartClientQuery(client.name)
                        setCheckoutValue('buyer_name', client.name)
                        setCheckoutValue('buyer_phone', client.phone || '')
                        setShowCartClientDropdown(false)
                      }}
                    >
                      <div className="font-medium">{client.name}</div>
                      <div className="text-xs text-gray-500">{buildClientContactText(client)}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="form-label">Buyer Phone</label>
              <input className="form-input" {...registerCheckout('buyer_phone')} />
            </div>
            <div>
              <label className="form-label">Payment Method</label>
              <select className="form-input" {...registerCheckout('payment_method')}>
                <option value="cash">Cash</option>
                <option value="bank">Bank</option>
                <option value="pos">POS</option>
                <option value="transfer">Transfer</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label className="form-label">Assigned Staff</label>
              <input className="form-input" {...registerCheckout('assigned_staff_name')} />
            </div>
            <div>
              <label className="form-label">Discount</label>
              <input type="number" step="0.01" min="0" className="form-input" {...registerCheckout('discount', { valueAsNumber: true })} />
            </div>
            <div>
              <label className="form-label">Amount Paid</label>
              <input type="number" step="0.01" min="0" className="form-input" {...registerCheckout('amount_paid', { valueAsNumber: true })} />
            </div>
            <div className="col-span-2">
              <label className="form-label">Notes</label>
              <textarea className="form-input" rows={2} {...registerCheckout('notes')} />
            </div>
          </div>

          <div className="grid grid-cols-4 gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
            <div>
              <p className="text-gray-500">Subtotal</p>
              <p className="font-semibold">{formatCurrency(cartSubtotal, currency)}</p>
            </div>
            <div>
              <p className="text-gray-500">Total</p>
              <p className="font-semibold">{formatCurrency(checkoutTotal, currency)}</p>
            </div>
            <div>
              <p className="text-gray-500">Outstanding</p>
              <p className="font-semibold text-red-600">{formatCurrency(checkoutBalance, currency)}</p>
            </div>
            <div>
              <p className="text-gray-500">Status</p>
              <p className="font-semibold">{checkoutStatus}</p>
            </div>
          </div>
        </form>
      </Modal>

      <Modal
        title={sellItem ? `Sell Item - ${sellItem.item_name}` : 'Sell Item'}
        open={!!sellItem}
        onClose={() => {
          setSellItem(null)
          resetSell()
        }}
        footer={(
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setSellItem(null)}>Cancel</button>
            <button type="submit" form="inventory-sell-form" className="btn-primary" disabled={sellMutation.isPending}>
              {sellMutation.isPending ? 'Processing...' : 'Sell Now'}
            </button>
          </div>
        )}
      >
        <form
          id="inventory-sell-form"
          className="space-y-4"
          onSubmit={handleSubmitSell((values) => {
            if (!sellItem) return
            if (Number(values.quantity || 0) <= 0) {
              toast.error('Quantity must be greater than zero')
              return
            }
            if (Number(values.quantity || 0) > Number(sellItem.quantity || 0)) {
              toast.error(`Cannot oversell. Remaining quantity is ${sellItem.quantity}`)
              return
            }
            if (!String(values.client_name || '').trim()) {
              toast.error('Buyer/client name is required')
              return
            }
            sellMutation.mutate(values)
          })}
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="form-label">Quantity</label>
              <input type="number" step="0.01" min="0.01" className="form-input" {...registerSell('quantity', { valueAsNumber: true })} />
              <p className="mt-1 text-xs text-gray-500">Available: {sellItem?.quantity || 0} {sellItem?.unit || 'pcs'}</p>
            </div>
            <div>
              <label className="form-label">Unit Selling Price</label>
              <input type="number" step="0.01" min="0" className="form-input" {...registerSell('selling_price', { valueAsNumber: true })} />
            </div>
            <div>
              <label className="form-label">Buyer / Client Name</label>
              <div className="relative">
                <input
                  className="form-input"
                  {...registerSell('client_name')}
                  value={sellClientQuery}
                  onChange={(e) => {
                    setSellClientQuery(e.target.value)
                    setSellValue('client_name', e.target.value)
                    setShowSellClientDropdown(true)
                  }}
                  onFocus={() => setShowSellClientDropdown(true)}
                />
                {showSellClientDropdown && sellClientQuery.trim() && (sellClientSuggestions?.items ?? []).length > 0 && (
                  <div className="absolute z-20 mt-1 w-full rounded-lg border bg-white shadow-lg" style={{ borderColor: '#d4af37' }}>
                    {(sellClientSuggestions?.items ?? []).map((client) => (
                      <button
                        type="button"
                        key={client.id}
                        className="block w-full px-3 py-2 text-left text-sm hover:bg-[#fff9e7]"
                        onClick={() => {
                          setSellClientQuery(client.name)
                          setSellValue('client_name', client.name)
                          setSellValue('client_phone', client.phone || '')
                          setShowSellClientDropdown(false)
                        }}
                      >
                        <div className="font-medium">{client.name}</div>
                        <div className="text-xs text-gray-500">{buildClientContactText(client)}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div>
              <label className="form-label">Buyer Phone</label>
              <input className="form-input" {...registerSell('client_phone')} />
            </div>
            <div>
              <label className="form-label">Payment Status</label>
              <select className="form-input" {...registerSell('payment_status')}>
                <option value="UNPAID">UNPAID</option>
                <option value="PART PAYMENT">PART PAYMENT</option>
                <option value="PAID">PAID</option>
              </select>
            </div>
            <div>
              <label className="form-label">Amount Paid</label>
              <input type="number" step="0.01" min="0" className="form-input" {...registerSell('paid_amount', { valueAsNumber: true })} />
            </div>
            <div className="col-span-2">
              <label className="form-label">Notes</label>
              <textarea className="form-input" rows={2} {...registerSell('notes')} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
            <div>
              <p className="text-gray-500">Amount Charged</p>
              <p className="font-semibold">{formatCurrency(sellAmountCharged, currency)}</p>
            </div>
            <div>
              <p className="text-gray-500">Paid</p>
              <p className="font-semibold">{formatCurrency(sellPaidAmount, currency)}</p>
            </div>
            <div>
              <p className="text-gray-500">Outstanding</p>
              <p className="font-semibold text-red-600">{formatCurrency(sellBalance, currency)}</p>
            </div>
          </div>
        </form>
      </Modal>

      <Modal
        title={salesHistoryItem ? `Sales History - ${salesHistoryItem.item_name}` : 'Sales History'}
        open={!!salesHistoryItem}
        onClose={() => setSalesHistoryItem(null)}
        size="lg"
      >
        {salesHistoryLoading ? <LoadingSpinner /> : (
          <div className="space-y-3">
            <div className="overflow-x-auto rounded-xl border" style={{ borderColor: '#d4af37' }}>
              <table className="min-w-full text-sm">
                <thead style={{ background: '#000000' }}>
                  <tr>
                    <th className="px-4 py-3 text-left font-semibold text-white">Date</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Buyer</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Qty</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Charged</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Paid</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Balance</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Status</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Staff</th>
                  </tr>
                </thead>
                <tbody className="bg-white">
                  {((salesHistoryData?.items ?? []) as InventorySaleHistoryRow[]).map((sale) => (
                    <tr key={sale.sale_item_id} className="border-t" style={{ borderColor: '#f1e7bf' }}>
                      <td className="px-4 py-3">{sale.sold_at ? new Date(sale.sold_at).toLocaleString() : '-'}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium">{sale.client_name || '-'}</div>
                        <div className="text-xs text-gray-500">{sale.client_phone || '-'}</div>
                      </td>
                      <td className="px-4 py-3">{sale.quantity}</td>
                      <td className="px-4 py-3">{formatCurrency(Number(sale.amount_charged || 0), currency)}</td>
                      <td className="px-4 py-3">{formatCurrency(Number(sale.paid_amount || 0), currency)}</td>
                      <td className="px-4 py-3">{formatCurrency(Number(sale.balance || 0), currency)}</td>
                      <td className="px-4 py-3">
                        <span className="badge-partial">{sale.is_reversed ? 'REVERSED' : (sale.payment_status || 'UNPAID')}</span>
                      </td>
                      <td className="px-4 py-3 text-xs">{sale.assigned_staff_name || sale.created_by_name || sale.sold_by || '-'}</td>
                    </tr>
                  ))}
                  {(salesHistoryData?.items ?? []).length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-6 text-center text-gray-500">No sales history yet</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex gap-2 justify-end">
              <button disabled={salesHistoryPage === 1} onClick={() => setSalesHistoryPage((p) => p - 1)} className="btn-secondary">Prev</button>
              <span className="text-sm text-gray-500 self-center">Page {salesHistoryPage} of {salesHistoryData?.total_pages ?? 1}</span>
              <button
                disabled={salesHistoryPage >= (salesHistoryData?.total_pages ?? 1)}
                onClick={() => setSalesHistoryPage((p) => p + 1)}
                className="btn-secondary"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        title={historyItem ? `Transaction History - ${historyItem.item_name}` : 'Transaction History'}
        open={!!historyItem}
        onClose={() => setHistoryItem(null)}
        size="lg"
      >
        {txLoading ? <LoadingSpinner /> : (
          <div className="space-y-3">
            <div className="overflow-x-auto rounded-xl border" style={{ borderColor: '#d4af37' }}>
              <table className="min-w-full text-sm">
                <thead style={{ background: '#000000' }}>
                  <tr>
                    <th className="px-4 py-3 text-left font-semibold text-white">Action</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Change</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Before</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">After</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Time</th>
                    <th className="px-4 py-3 text-left font-semibold text-white">Operation</th>
                  </tr>
                </thead>
                <tbody className="bg-white">
                  {((txData?.items ?? []) as InventoryTransaction[]).map((tx) => (
                    <tr key={tx.id} className="border-t" style={{ borderColor: '#f1e7bf' }}>
                      <td className="px-4 py-3">{tx.action}</td>
                      <td className="px-4 py-3">{tx.quantity_change}</td>
                      <td className="px-4 py-3">{tx.quantity_before}</td>
                      <td className="px-4 py-3">{tx.quantity_after}</td>
                      <td className="px-4 py-3">{new Date(tx.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3">
                        {tx.action === 'SALE' && tx.related_sale_item_id && (
                          <button
                            className="btn-secondary py-1 px-2 text-xs"
                            onClick={() => {
                              if (confirm('Reverse this sale and restore stock?')) {
                                const saleItemId = tx.related_sale_item_id
                                if (saleItemId) reverseSaleMutation.mutate(saleItemId)
                              }
                            }}
                            disabled={reverseSaleMutation.isPending}
                          >
                            <RotateCcw size={12} className="inline mr-1" />
                            Reverse
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(txData?.items ?? []).length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-gray-500">No transactions yet</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex gap-2 justify-end">
              <button disabled={historyPage === 1} onClick={() => setHistoryPage((p) => p - 1)} className="btn-secondary">Prev</button>
              <span className="text-sm text-gray-500 self-center">Page {historyPage} of {txData?.total_pages ?? 1}</span>
              <button disabled={historyPage >= (txData?.total_pages ?? 1)} onClick={() => setHistoryPage((p) => p + 1)} className="btn-secondary">Next</button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
