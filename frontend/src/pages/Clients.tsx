import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import Table from '@/components/Table'
import Modal from '@/components/Modal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Plus, Pencil, Trash2, Upload } from 'lucide-react'
import toast from 'react-hot-toast'

interface Client {
  id: string
  name: string
  client_name?: string
  email: string
  phone: string
  phone_number?: string
  company: string
  address: string
  notes: string
  source: string
}

interface FormValues {
  client_name: string
  email?: string
  phone_number: string
  company?: string
  address?: string
  notes?: string
}

interface ImportRow {
  name: string
  email?: string
  phone?: string
  company?: string
  address?: string
  notes?: string
}

export default function Clients() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState<Client | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [importText, setImportText] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['clients', search, page],
    queryFn: () =>
      api.get('/clients', { params: { search, page, page_size: 50 } }).then((r) => r.data),
  })

  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>()

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = {
        client_name: values.client_name?.trim(),
        phone_number: values.phone_number?.trim(),
        email: values.email?.trim() || undefined,
        company: values.company?.trim() || undefined,
        address: values.address?.trim() || undefined,
        notes: values.notes?.trim() || undefined,
      }
      return editRow
        ? api.put(`/clients/${editRow.id}`, payload)
        : api.post('/clients', payload)
    },
    onSuccess: () => {
      toast.success(editRow ? 'Client updated' : 'Client added')
      qc.invalidateQueries({ queryKey: ['clients'] })
      setShowForm(false)
      setEditRow(null)
      reset()
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/clients/${id}`),
    onSuccess: () => {
      toast.success('Client removed')
      qc.invalidateQueries({ queryKey: ['clients'] })
    },
  })

  const importMutation = useMutation({
    mutationFn: (rows: ImportRow[]) =>
      Promise.all(rows.map((r) => api.post('/clients', { ...r, source: 'sheet_import' }))),
    onSuccess: () => {
      toast.success('Contacts imported')
      qc.invalidateQueries({ queryKey: ['clients'] })
      setShowImport(false)
      setImportText('')
    },
    onError: () => toast.error('Import failed'),
  })

  const openEdit = (row: Client) => {
    setEditRow(row)
    reset({
      client_name: row.client_name ?? row.name,
      email: row.email,
      phone_number: row.phone_number ?? row.phone,
      company: row.company,
      address: row.address,
      notes: row.notes,
    })
    setShowForm(true)
  }

  const handleImport = () => {
    try {
      const rows: ImportRow[] = JSON.parse(importText)
      if (!Array.isArray(rows)) throw new Error()
      importMutation.mutate(rows)
    } catch {
      toast.error('Invalid JSON. Paste an array of objects.')
    }
  }

  const columns = [
    { key: 'client_name', header: 'Name', render: (row: Client) => row.client_name ?? row.name },
    { key: 'email', header: 'Email' },
    { key: 'phone_number', header: 'Phone', render: (row: Client) => row.phone_number ?? row.phone },
    { key: 'company', header: 'Company' },
    { key: 'source', header: 'Source' },
    {
      key: 'actions',
      header: '',
      render: (row: Client) => (
        <div className="flex items-center gap-2">
          <button onClick={() => openEdit(row)} className="text-gray-400 hover:text-primary-600"><Pencil size={15} /></button>
          <button onClick={() => { if (confirm('Delete this client?')) deleteMutation.mutate(row.id) }} className="text-gray-400 hover:text-red-600"><Trash2 size={15} /></button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Clients</h1>
        <div className="flex gap-2">
          <button onClick={() => setShowImport(true)} className="btn-secondary"><Upload size={15} /> Import from Sheet</button>
          <button onClick={() => { setEditRow(null); reset(); setShowForm(true) }} className="btn-primary"><Plus size={15} /> Add Client</button>
        </div>
      </div>

      <input
        className="form-input max-w-sm"
        placeholder="Search by name…"
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(1) }}
      />

      {isLoading ? <LoadingSpinner /> : (
        <>
          <Table columns={columns as any} data={data?.items ?? data?.data ?? []} />
          <div className="flex gap-2 justify-end">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="btn-secondary">Prev</button>
            <span className="text-sm text-gray-500 self-center">Page {page} of {data?.total_pages ?? 1}</span>
            <button disabled={page >= (data?.total_pages ?? 1)} onClick={() => setPage(p => p + 1)} className="btn-secondary">Next</button>
          </div>
        </>
      )}

      {/* Add / Edit Modal */}
      <Modal title={editRow ? 'Edit Client' : 'Add Client'} open={showForm} onClose={() => { setShowForm(false); setEditRow(null); reset() }}>
        <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="space-y-4">
          {[
            { name: 'client_name', label: 'Name', required: true },
            { name: 'email', label: 'Email' },
            { name: 'phone_number', label: 'Phone', required: true },
            { name: 'company', label: 'Company' },
            { name: 'address', label: 'Address' },
          ].map(({ name, label, required }) => (
            <div key={name}>
              <label className="form-label">{label}</label>
              <input className="form-input" {...register(name as any, required ? { required: 'Required' } : {})} />
              {errors[name as keyof FormValues] && <p className="text-xs text-red-500">{errors[name as keyof FormValues]?.message}</p>}
            </div>
          ))}
          <div>
            <label className="form-label">Notes</label>
            <textarea className="form-input" rows={2} {...register('notes')} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Import Modal */}
      <Modal title="Import Contacts from Sheet" open={showImport} onClose={() => setShowImport(false)} size="lg">
        <p className="text-sm text-gray-500 mb-3">
          Paste a JSON array of contacts. Each object should have: name, email, phone, company, address, notes.
        </p>
        <textarea
          className="form-input font-mono text-xs"
          rows={10}
          placeholder='[{"name":"John Doe","email":"john@example.com","phone":"0200000000"}]'
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
        />
        <div className="flex justify-end gap-2 pt-3">
          <button className="btn-secondary" onClick={() => setShowImport(false)}>Cancel</button>
          <button className="btn-primary" onClick={handleImport} disabled={importMutation.isPending}>
            {importMutation.isPending ? 'Importing…' : 'Import'}
          </button>
        </div>
      </Modal>
    </div>
  )
}
