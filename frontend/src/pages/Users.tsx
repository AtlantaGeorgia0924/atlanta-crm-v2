import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailCheck, Pencil, Plus, RotateCcw, Search, ShieldAlert, Trash2, UserCheck, UserMinus, UserX } from 'lucide-react'
import toast from 'react-hot-toast'

import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import Modal from '@/components/Modal'
import { useAuthStore } from '@/store/authStore'

type UserStatus = 'ACTIVE' | 'INACTIVE' | 'SUSPENDED' | 'DELETED'

interface UserRow {
  id: string
  full_name?: string
  email: string
  phone?: string
  role: 'admin' | 'staff' | string
  is_active: boolean
  account_status?: UserStatus
  created_at?: string
  last_login_at?: string
  failed_login_attempts?: number
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
  account_status?: UserStatus
}

interface PasswordResetValues {
  password: string
}

interface DeleteValues {
  hard_delete: boolean
  reassign_to?: string
}

interface CreateResponse {
  user: UserRow
  credentials?: {
    email?: string
    temporary_password?: string | null
    share_text?: string | null
  }
}

function parseApiDetail(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail?.message) return String(detail.message)
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0]
    return String(first?.msg || first?.message || fallback)
  }
  return fallback
}

function statusBadge(status: UserStatus) {
  if (status === 'ACTIVE') return 'bg-emerald-50 text-emerald-700'
  if (status === 'INACTIVE') return 'bg-gray-100 text-gray-700'
  if (status === 'SUSPENDED') return 'bg-amber-50 text-amber-700'
  return 'bg-red-50 text-red-700'
}

export default function UsersPage() {
  const qc = useQueryClient()
  const me = useAuthStore((s) => s.user)

  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [lastLoginFrom, setLastLoginFrom] = useState('')
  const [lastLoginTo, setLastLoginTo] = useState('')
  const [page, setPage] = useState(1)

  const [createOpen, setCreateOpen] = useState(false)
  const [createSuccessOpen, setCreateSuccessOpen] = useState(false)
  const [createdCredentials, setCreatedCredentials] = useState<CreateResponse['credentials'] | null>(null)

  const [editOpen, setEditOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
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
  const {
    register: registerDelete,
    handleSubmit: submitDelete,
    reset: resetDelete,
    watch: watchDelete,
  } = useForm<DeleteValues>({ defaultValues: { hard_delete: false, reassign_to: '' } })

  const { data, isLoading } = useQuery<UsersResponse>({
    queryKey: ['users', search, role, status, lastLoginFrom, lastLoginTo, page],
    queryFn: () =>
      api
        .get('/users', {
          params: {
            search: search || undefined,
            role: role || undefined,
            account_status: status || undefined,
            last_login_from: lastLoginFrom || undefined,
            last_login_to: lastLoginTo || undefined,
            page,
            page_size: 20,
          },
        })
        .then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: (values: CreateValues) => api.post<CreateResponse>('/users', values),
    onSuccess: (res) => {
      toast.success('User created')
      qc.invalidateQueries({ queryKey: ['users'] })
      setCreateOpen(false)
      setCreatedCredentials(res.data?.credentials || null)
      setCreateSuccessOpen(true)
      reset({ role: 'staff', full_name: '', email: '', phone: '', password: '' })
    },
    onError: (e: any) => toast.error(parseApiDetail(e, 'Create failed')),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: EditValues }) => api.put(`/users/${id}`, values),
    onSuccess: () => {
      toast.success('User updated')
      qc.invalidateQueries({ queryKey: ['users'] })
      setEditOpen(false)
      setEditing(null)
    },
    onError: (e: any) => toast.error(parseApiDetail(e, 'Update failed')),
  })

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => api.post(`/users/${id}/reset-password`, { password }),
    onSuccess: () => {
      toast.success('Password reset')
      setPasswordOpen(false)
      setEditing(null)
      resetPassword()
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e: any) => toast.error(parseApiDetail(e, 'Password reset failed')),
  })

  const activateMutation = useMutation({
    mutationFn: (id: string) => api.post(`/users/${id}/activate`),
    onSuccess: () => {
      toast.success('User activated')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e: any) => toast.error(parseApiDetail(e, 'Activation failed')),
  })

  const suspendMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => api.post(`/users/${id}/suspend`, { reason: reason || undefined }),
    onSuccess: () => {
      toast.success('User suspended')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e: any) => toast.error(parseApiDetail(e, 'Suspend failed')),
  })

  const unlockMutation = useMutation({
    mutationFn: (id: string) => api.post(`/users/${id}/unlock`),
    onSuccess: () => {
      toast.success('Account unlocked')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e: any) => toast.error(parseApiDetail(e, 'Unlock failed')),
  })

  const resendActivationMutation = useMutation({
    mutationFn: (id: string) => api.post(`/users/${id}/resend-activation`),
    onSuccess: () => toast.success('Activation sent'),
    onError: (e: any) => toast.error(parseApiDetail(e, 'Resend activation failed')),
  })

  const deleteMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: DeleteValues }) => api.delete(`/users/${id}`, { data: values }),
    onSuccess: () => {
      toast.success('User deletion completed')
      qc.invalidateQueries({ queryKey: ['users'] })
      setDeleteOpen(false)
      setEditing(null)
      resetDelete({ hard_delete: false, reassign_to: '' })
    },
    onError: (e: any) => toast.error(parseApiDetail(e, 'Delete failed')),
  })

  const rows = useMemo(() => data?.items ?? [], [data])

  const openEdit = (row: UserRow) => {
    setEditing(row)
    resetEdit({
      full_name: row.full_name || '',
      email: row.email,
      phone: row.phone || '',
      role: (row.role === 'admin' ? 'admin' : 'staff'),
      account_status: (row.account_status || (row.is_active ? 'ACTIVE' : 'INACTIVE')) as UserStatus,
    })
    setEditOpen(true)
  }

  const currentDeleteHard = watchDelete('hard_delete')

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
            <option value="ACTIVE">ACTIVE</option>
            <option value="INACTIVE">INACTIVE</option>
            <option value="SUSPENDED">SUSPENDED</option>
            <option value="DELETED">DELETED</option>
          </select>
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <span>Last login</span>
            <input type="date" className="form-input" value={lastLoginFrom} onChange={(e) => { setLastLoginFrom(e.target.value); setPage(1) }} />
            <span>to</span>
            <input type="date" className="form-input" value={lastLoginTo} onChange={(e) => { setLastLoginTo(e.target.value); setPage(1) }} />
          </div>
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
                <th className="px-3 py-2 text-left text-white">Failed Attempts</th>
                <th className="px-3 py-2 text-left text-white">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-gray-500">No users found</td>
                </tr>
              ) : (
                rows.map((row) => {
                  const accountStatus = (row.account_status || (row.is_active ? 'ACTIVE' : 'INACTIVE')) as UserStatus
                  const isSelf = row.id === me?.id
                  return (
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
                        <span className={`text-xs px-2 py-0.5 rounded-full ${statusBadge(accountStatus)}`}>
                          {accountStatus}
                        </span>
                      </td>
                      <td className="px-3 py-2">{row.created_at ? new Date(row.created_at).toLocaleDateString() : '-'}</td>
                      <td className="px-3 py-2">{row.last_login_at ? new Date(row.last_login_at).toLocaleString() : '-'}</td>
                      <td className="px-3 py-2">{Number(row.failed_login_attempts || 0)}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1 flex-wrap">
                          <button className="btn-secondary px-2 py-1" onClick={() => openEdit(row)} title="Edit user">
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
                          <button className="btn-secondary px-2 py-1" onClick={() => resendActivationMutation.mutate(row.id)} title="Resend activation">
                            <MailCheck size={13} />
                          </button>
                          <button className="btn-secondary px-2 py-1" onClick={() => unlockMutation.mutate(row.id)} title="Unlock account">
                            <ShieldAlert size={13} />
                          </button>
                          {accountStatus === 'ACTIVE' ? (
                            <button className="btn-secondary px-2 py-1" disabled={isSelf} onClick={() => suspendMutation.mutate({ id: row.id })} title="Suspend">
                              <UserMinus size={13} />
                            </button>
                          ) : (
                            <button className="btn-secondary px-2 py-1" onClick={() => activateMutation.mutate(row.id)} title="Activate">
                              <UserCheck size={13} />
                            </button>
                          )}
                          <button
                            className="btn-secondary px-2 py-1"
                            disabled={isSelf}
                            onClick={() => {
                              setEditing(row)
                              resetDelete({ hard_delete: false, reassign_to: '' })
                              setDeleteOpen(true)
                            }}
                            title="Delete"
                          >
                            <Trash2 size={13} />
                          </button>
                          <button
                            className="btn-secondary px-2 py-1"
                            disabled={isSelf}
                            onClick={() => updateMutation.mutate({ id: row.id, values: { account_status: accountStatus === 'INACTIVE' ? 'ACTIVE' : 'INACTIVE' } })}
                            title={accountStatus === 'INACTIVE' ? 'Set active' : 'Set inactive'}
                          >
                            {accountStatus === 'INACTIVE' ? <UserCheck size={13} /> : <UserX size={13} />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
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

      <Modal title="User Created" open={createSuccessOpen} onClose={() => setCreateSuccessOpen(false)}>
        <div className="space-y-3 text-sm">
          <p className="text-gray-700">User account was created successfully.</p>
          {createdCredentials?.temporary_password && (
            <div className="rounded-lg border border-gray-200 p-3 space-y-1">
              <p><span className="font-medium">Email:</span> {createdCredentials.email}</p>
              <p><span className="font-medium">Temporary password:</span> {createdCredentials.temporary_password}</p>
            </div>
          )}
          <div className="flex justify-end gap-2">
            {createdCredentials?.share_text && (
              <button
                type="button"
                className="btn-secondary"
                onClick={async () => {
                  await navigator.clipboard.writeText(createdCredentials.share_text || '')
                  toast.success('Credentials copied')
                }}
              >
                Copy Credentials
              </button>
            )}
            <button type="button" className="btn-primary" onClick={() => setCreateSuccessOpen(false)}>Done</button>
          </div>
        </div>
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
            <label className="form-label">Account Status</label>
            <select className="form-input" {...registerEdit('account_status')}>
              <option value="ACTIVE">ACTIVE</option>
              <option value="INACTIVE">INACTIVE</option>
              <option value="SUSPENDED">SUSPENDED</option>
              <option value="DELETED">DELETED</option>
            </select>
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

      <Modal title="Delete User" open={deleteOpen} onClose={() => setDeleteOpen(false)}>
        <form className="space-y-3" onSubmit={submitDelete((values) => editing && deleteMutation.mutate({ id: editing.id, values }))}>
          <p className="text-sm text-gray-600">
            This action is admin-only. Soft delete is recommended for auditability and transaction integrity.
          </p>
          <div>
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" {...registerDelete('hard_delete')} /> Permanently hard delete user
            </label>
          </div>
          <div>
            <label className="form-label">Reassign ownership to user ID (optional but recommended)</label>
            <input className="form-input" {...registerDelete('reassign_to')} placeholder="Target user ID for dependency reassignment" />
          </div>
          {currentDeleteHard && <p className="text-xs text-red-600">Hard delete removes the profile row and attempts auth deletion.</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={() => setDeleteOpen(false)}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={deleteMutation.isPending}>{deleteMutation.isPending ? 'Deleting...' : 'Confirm Delete'}</button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
