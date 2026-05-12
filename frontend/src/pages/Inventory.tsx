import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatCurrency } from '@/lib/utils'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

interface StockItem {
  id: string
  item_name: string
  sku: string
  category: string
  quantity: number
  unit: string
  unit_cost: number
  unit_price: number
  reorder_level: number
  supplier: string
}

interface FormValues {
  item_name: string
  sku: string
  category: string
  description: string
  quantity: number
  unit: string
  unit_cost: number
  unit_price: number
  reorder_level: number
  supplier: string
  location: string
}

export default function Inventory() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [lowStock, setLowStock] = useState(false)
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<StockItem | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['inventory', search, lowStock, page],
    queryFn: () =>
      api.get('/inventory', { params: { search, low_stock: lowStock, page, page_size: 50 } }).then((r) => r.data),
  })

  const { data: status } = useQuery<{ currency?: string }>({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
  })
  const currency = status?.currency ?? localStorage.getItem('currency') ?? 'NGN'

  const { register, handleSubmit, reset } = useForm<FormValues>()

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) =>
      editRow ? api.put(`/inventory/${editRow.id}`, values) : api.post('/inventory', values),
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false); setEditRow(null); reset()
    },
    onError: () => toast.error('Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/inventory/${id}`),
    onSuccess: () => {
      toast.success('Removed')
      qc.invalidateQueries({ queryKey: ['inventory'] })
    },
  })

  const openEdit = (row: StockItem) => {
    setEditRow(row)
    reset({ ...row })
    setShowForm(true)
  }

  const columns = [
    { key: 'item_name',    header: 'Item' },
    { key: 'sku',          header: 'SKU' },
    { key: 'category',     header: 'Category' },
    { key: 'quantity',     header: 'Qty',
      render: (r: StockItem) => (
        <span className={Number(r.quantity) <= Number(r.reorder_level) ? 'text-red-600 font-semibold' : ''}>
          {r.quantity} {r.unit}
        </span>
      )
    },
    { key: 'unit_price',   header: 'Price',  render: (r: StockItem) => formatCurrency(r.unit_price, currency) },
    { key: 'reorder_level', header: 'Reorder' },
    { key: 'supplier',     header: 'Supplier' },
    {
      key: 'actions', header: '',
      render: (r: StockItem) => (
        <div className="flex gap-2">
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
        <button onClick={() => { setEditRow(null); reset(); setShowForm(true) }} className="btn-primary"><Plus size={15} /> Add Item</button>
      </div>

      <div className="flex gap-3 items-center">
        <input className="form-input max-w-sm" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input type="checkbox" checked={lowStock} onChange={(e) => setLowStock(e.target.checked)} className="rounded" />
          Low stock only
        </label>
      </div>

      {isLoading ? <LoadingSpinner /> : (
        <>
          <Table columns={columns as any} data={data?.items ?? data?.data ?? []} />
          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setPage((p) => p - 1)} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page} of {data?.total_pages ?? 1}</span>
            <button disabled={page >= (data?.total_pages ?? 1)} onClick={() => setPage((p) => p + 1)} className="btn-secondary">Next</button>
          </div>
        </>
      )}

      <Modal title={editRow ? 'Edit Item' : 'Add Item'} open={showForm} onClose={() => { setShowForm(false); reset() }} size="lg">
        <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="grid grid-cols-2 gap-4">
          {[
            { name: 'item_name', label: 'Item Name', required: true, colSpan: 2 },
            { name: 'sku', label: 'SKU' },
            { name: 'category', label: 'Category' },
            { name: 'quantity', label: 'Quantity', type: 'number' },
            { name: 'unit', label: 'Unit' },
            { name: 'unit_cost', label: 'Unit Cost', type: 'number' },
            { name: 'unit_price', label: 'Unit Price', type: 'number' },
            { name: 'reorder_level', label: 'Reorder Level', type: 'number' },
            { name: 'supplier', label: 'Supplier' },
            { name: 'location', label: 'Location' },
          ].map(({ name, label, required, colSpan, type }) => (
            <div key={name} className={colSpan === 2 ? 'col-span-2' : ''}>
              <label className="form-label">{label}</label>
              <input
                type={type ?? 'text'}
                step={type === 'number' ? '0.01' : undefined}
                className="form-input"
                {...register(name as any, { ...(required ? { required: 'Required' } : {}), ...(type === 'number' ? { valueAsNumber: true } : {}) })}
              />
            </div>
          ))}
          <div className="col-span-2 flex justify-end gap-2">
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
