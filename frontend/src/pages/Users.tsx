import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, RotateCcw, Search, ShieldAlert, UserX } from 'lucide-react'
import toast from 'react-hot-toast'

import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import Modal from '@/components/Modal'

interface UserRow {
  id: string
  full_name?: string
  email: string
  phone?: string
  role: 'admin' | 'staff' | string
  is_active: boolean
  created_at?: string
  last_login_at?: string
}

interface UsersResponse {
  items: UserRow[]
  page: number
  total_pages: number
  total: number
}

interface CreateValues {
  full_name: string
  email: string
  phone?: string
  password: string
  role: 'admin' | 'staff'
}

interface EditValues {
  full_name?: string
  email?: string
  phone?: string
  role?: 'admin' | 'staff'
  is_active?: boolean
}

interface PasswordResetValues {
  password: string
}

export default function UsersPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [editing, setEditing] = useState<UserRow | null>(null)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<CreateValues>({
    defaultValues: { role: 'staff' },
  })
  const {
    register: registerEdit,
    handleSubmit: submitEdit,
    reset: resetEdit,
  } = useForm<EditValues>()
  const {
    register: registerPassword,
    handleSubmit: submitPassword,
    reset: resetPassword,
  } = useForm<PasswordResetValues>()

  const { data, isLoading } = useQuery<UsersResponse>({
    queryKey: ['users', search, role, status, page],
    queryFn: () =>
      api
        .get('/users', {
          params: {
            search: search || undefined,
            role: role || undefined,
            is_active: status === '' ? undefined : status === 'active',
            page,
            page_size: 20,
          },
        })
        .then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: (values: CreateValues) => api.post('/users', values),
    onSuccess: () => {
      toast.success('User created')
      qc.invalidateQueries({ queryKey: ['users'] })
      setCreateOpen(false)
      reset({ role: 'staff' })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Create failed'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: EditValues }) => api.put(`/users/${id}`, values),
    onSuccess: () => {
      toast.success('User updated')
      qc.invalidateQueries({ queryKey: ['users'] })
      setEditOpen(false)
      setEditing(null)
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Update failed'),
  })

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => api.post(`/users/${id}/reset-password`, { password }),
    onSuccess: () => {
      toast.success('Password reset')
      setPasswordOpen(false)
      setEditing(null)
      resetPassword()
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Password reset failed'),
  })

  const rows = useMemo(() => data?.items ?? [], [data])

  const openEdit = (row: UserRow) => {
    setEditing(row)
    resetEdit({
      full_name: row.full_name || '',
      email: row.email,
      phone: row.phone || '',
      role: (row.role === 'admin' ? 'admin' : 'staff'),
      is_active: row.is_active,
    })
    setEditOpen(true)
  }

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Users</h1>
          <p className="text-sm text-gray-500">Admin-controlled user management</p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            reset({ role: 'staff' })
            setCreateOpen(true)
          }}
        >
          <Plus size={15} /> New User
        </button>
      </div>

      <div className="rounded-xl border p-3 bg-white" style={{ borderColor: '#e7d89f' }}>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              className="form-input pl-8"
              placeholder="Search name, email, phone"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            />
          </div>
          <select className="form-input" value={role} onChange={(e) => { setRole(e.target.value); setPage(1) }}>
            <option value="">All roles</option>
            <option value="admin">Admin</option>
            <option value="staff">Staff</option>
          </select>
          <select className="form-input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
            <option value="">All status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-white" style={{ borderColor: '#e7d89f' }}>
          <table className="min-w-full text-sm">
            <thead style={{ background: '#000000' }}>
              <tr>
                <th className="px-3 py-2 text-left text-white">Full Name</th>
                <th className="px-3 py-2 text-left text-white">Email</th>
                <th className="px-3 py-2 text-left text-white">Phone</th>
                <th className="px-3 py-2 text-left text-white">Role</th>
                <th className="px-3 py-2 text-left text-white">Status</th>
                <th className="px-3 py-2 text-left text-white">Created</th>
                <th className="px-3 py-2 text-left text-white">Last Login</th>
                <th className="px-3 py-2 text-left text-white">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-gray-500">No users found</td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id} className="border-t" style={{ borderColor: '#f1e7bf' }}>
                    <td className="px-3 py-2">{row.full_name || '-'}</td>
                    <td className="px-3 py-2">{row.email}</td>
                    <td className="px-3 py-2">{row.phone || '-'}</td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full border ${row.role === 'admin' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-gray-50 text-gray-700 border-gray-200'}`}>
                        {row.role}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${row.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
                        {row.is_active ? 'active' : 'inactive'}
                      </span>
                    </td>
                    <td className="px-3 py-2">{row.created_at ? new Date(row.created_at).toLocaleDateString() : '-'}</td>
                    <td className="px-3 py-2">{row.last_login_at ? new Date(row.last_login_at).toLocaleString() : '-'}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <button className="btn-secondary px-2 py-1" onClick={() => openEdit(row)}>
                          <Pencil size={13} />
                        </button>
                        <button
                          className="btn-secondary px-2 py-1"
                          onClick={() => {
                            setEditing(row)
                            resetPassword()
                            setPasswordOpen(true)
                          }}
                          title="Reset Password"
                        >
                          <RotateCcw size={13} />
                        </button>
                        <button
                          className="btn-secondary px-2 py-1"
                          onClick={() => updateMutation.mutate({ id: row.id, values: { is_active: !row.is_active } })}
                          title={row.is_active ? 'Deactivate' : 'Activate'}
                        >
                          {row.is_active ? <UserX size={13} /> : <ShieldAlert size={13} />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex gap-2 justify-end">
        <button disabled={page === 1} onClick={() => setPage((p) => p - 1)} className="btn-secondary">Prev</button>
        <span className="self-center text-sm text-gray-500">Page {page} of {data?.total_pages ?? 1}</span>
        <button disabled={page >= (data?.total_pages ?? 1)} onClick={() => setPage((p) => p + 1)} className="btn-secondary">Next</button>
      </div>

      <Modal title="Create User" open={createOpen} onClose={() => setCreateOpen(false)}>
        <form className="space-y-3" onSubmit={handleSubmit((values) => createMutation.mutate(values))}>
          <div>
            <label className="form-label">Full Name</label>
            <input className="form-input" {...register('full_name', { required: 'Required' })} />
            {errors.full_name && <p className="text-xs text-red-500">{errors.full_name.message}</p>}
          </div>
          <div>
            <label className="form-label">Email</label>
            <input type="email" className="form-input" {...register('email', { required: 'Required' })} />
            {errors.email && <p className="text-xs text-red-500">{errors.email.message}</p>}
          </div>
          <div>
            <label className="form-label">Phone</label>
            <input className="form-input" {...register('phone')} />
          </div>
          <div>
            <label className="form-label">Password</label>
            <input type="password" className="form-input" {...register('password', { required: 'Required', minLength: { value: 8, message: 'At least 8 characters' } })} />
            {errors.password && <p className="text-xs text-red-500">{errors.password.message}</p>}
          </div>
          <div>
            <label className="form-label">Role</label>
            <select className="form-input" {...register('role')}>
              <option value="staff">staff</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={() => setCreateOpen(false)}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={createMutation.isPending}>{createMutation.isPending ? 'Creating...' : 'Create User'}</button>
          </div>
        </form>
      </Modal>

      <Modal title="Edit User" open={editOpen} onClose={() => setEditOpen(false)}>
        <form className="space-y-3" onSubmit={submitEdit((values) => editing && updateMutation.mutate({ id: editing.id, values }))}>
          <div>
            <label className="form-label">Full Name</label>
            <input className="form-input" {...registerEdit('full_name')} />
          </div>
          <div>
            <label className="form-label">Email</label>
            <input type="email" className="form-input" {...registerEdit('email')} />
          </div>
          <div>
            <label className="form-label">Phone</label>
            <input className="form-input" {...registerEdit('phone')} />
          </div>
          <div>
            <label className="form-label">Role</label>
            <select className="form-input" {...registerEdit('role')}>
              <option value="staff">staff</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div>
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" {...registerEdit('is_active')} /> Active account
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={() => setEditOpen(false)}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={updateMutation.isPending}>{updateMutation.isPending ? 'Saving...' : 'Save Changes'}</button>
          </div>
        </form>
      </Modal>

      <Modal title="Reset Password" open={passwordOpen} onClose={() => setPasswordOpen(false)}>
        <form className="space-y-3" onSubmit={submitPassword((values) => editing && resetPasswordMutation.mutate({ id: editing.id, password: values.password }))}>
          <div>
            <label className="form-label">New Password</label>
            <input type="password" className="form-input" {...registerPassword('password', { required: true, minLength: 8 })} />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={() => setPasswordOpen(false)}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={resetPasswordMutation.isPending}>{resetPasswordMutation.isPending ? 'Updating...' : 'Reset Password'}</button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
