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
  payment_status?: string
  product_status?: string
  sold_out?: boolean
}

interface FormValues {
  item_name: string
  sku?: string
  category?: string
  description?: string
  quantity: number
  unit?: string
  unit_cost: number
  unit_price: number
  reorder_level: number
  supplier?: string
  location?: string
  product_status?: string
}

interface GroupRow {
  name: string
  product_count: number
}

type InventoryView = 'products' | 'pending_deals' | 'groups' | 'out_of_stock'
type CreateMode = 'single' | 'multiple'

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

  const { register, handleSubmit, reset } = useForm<FormValues>()

  const groups: GroupRow[] = groupsData?.groups ?? []

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = {
        item_name: values.item_name?.trim(),
        sku: values.sku?.trim() || undefined,
        category: values.category?.trim() || undefined,
        description: values.description?.trim() || undefined,
        quantity: Number(values.quantity ?? 0),
        unit: values.unit?.trim() || 'pcs',
        unit_cost: Number(values.unit_cost ?? 0),
        unit_price: Number(values.unit_price ?? 0),
        reorder_level: Number(values.reorder_level ?? 0),
        supplier: values.supplier?.trim() || undefined,
        location: values.location?.trim() || undefined,
        payment_status: values.product_status?.trim() || undefined,
      }
      return editRow ? api.put(`/inventory/${editRow.id}`, payload) : api.post('/inventory', payload)
    },
    onSuccess: () => {
      toast.success('Saved')
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-groups'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false); setEditRow(null); reset()
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

  const openEdit = (row: StockItem) => {
    setEditRow(row)
    setCreateMode('single')
    reset({ ...row, product_status: row.product_status || row.payment_status || 'AVAILABLE' })
    setShowForm(true)
  }

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
        <button
          onClick={() => {
            setEditRow(null)
            setCreateMode('single')
            reset({ quantity: 1, unit: 'pcs', unit_cost: 0, unit_price: 0, reorder_level: 0, product_status: 'AVAILABLE' })
            setShowForm(true)
          }}
          className="btn-primary"
        >
          <Plus size={15} /> Add Product
        </button>
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

      <Modal title={editRow ? 'Edit Product' : 'Add Product'} open={showForm} onClose={() => { setShowForm(false); reset() }} size="lg">
        {!editRow && (
          <div className="flex gap-2 mb-4">
            <button className={createMode === 'single' ? 'btn-primary' : 'btn-secondary'} onClick={() => setCreateMode('single')} type="button">Single Product</button>
            <button className={createMode === 'multiple' ? 'btn-primary' : 'btn-secondary'} onClick={() => setCreateMode('multiple')} type="button">Multiple Products</button>
          </div>
        )}

        {(editRow || createMode === 'single') && (
          <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="grid grid-cols-2 gap-4">
            {[
              { name: 'item_name', label: 'Item Name', required: true, colSpan: 2 },
              { name: 'sku', label: 'SKU' },
              { name: 'category', label: 'Group / Category' },
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
            <div className="col-span-2">
              <label className="form-label">Product Status</label>
              <select className="form-input" {...register('product_status')}>
                <option value="AVAILABLE">AVAILABLE</option>
                <option value="PENDING DEAL">PENDING DEAL</option>
                <option value="SOLD">SOLD</option>
              </select>
            </div>
            <div className="col-span-2 flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={saveMutation.isPending}>
                {saveMutation.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        )}

        {!editRow && createMode === 'multiple' && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Paste a JSON array for bulk add. Example: [{'{"item_name":"IPHONE 14","category":"IPHONE","quantity":1,"unit_cost":500,"unit_price":650}'}]
            </p>
            <textarea
              className="form-input font-mono text-xs"
              rows={12}
              value={bulkInput}
              onChange={(e) => setBulkInput(e.target.value)}
              placeholder='[{"item_name":"IPHONE 14","category":"IPHONE","quantity":1,"unit_cost":500,"unit_price":650}]'
            />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button>
              <button type="button" className="btn-primary" onClick={handleBulkSubmit} disabled={bulkMutation.isPending}>
                {bulkMutation.isPending ? 'Saving…' : 'Save Multiple'}
              </button>
            </div>
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
    </div>
  )
}
