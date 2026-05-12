import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import toast from 'react-hot-toast'
import { Save } from 'lucide-react'

interface SettingsMap {
  business_name: string
  currency: string
  google_sheet_id: string
  last_sync_at: string
  last_workspace_refresh: string
}

export default function Settings() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery<SettingsMap>({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings').then((r) => r.data),
  })

  const { register, handleSubmit } = useForm<SettingsMap>({ values: data })

  const saveMutation = useMutation({
    mutationFn: async (values: SettingsMap) => {
      await Promise.all(
        Object.entries(values).map(([key, value]) =>
          api.put(`/settings/${key}`, undefined, { params: { value } })
        )
      )
    },
    onSuccess: () => {
      toast.success('Settings saved')
      qc.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: () => toast.error('Save failed'),
  })

  const { data: status } = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
    refetchInterval: 30_000,
  })

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="p-8 space-y-6">
      <h1 className="text-2xl font-bold">Settings / System Status</h1>

      {/* System Status */}
      <div className="card space-y-3">
        <h2 className="font-semibold text-gray-700">System Status</h2>
        <div className="flex gap-3 flex-wrap">
          <span className={`px-3 py-1 rounded-full text-xs font-medium ${status?.db_connected ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
            {status?.db_connected ? '● Supabase Connected' : '● Supabase Disconnected'}
          </span>
        </div>
        <div className="text-xs text-gray-500 space-y-1">
          {status?.last_sync_at && <p>Last Sync to Sheets: {new Date(status.last_sync_at).toLocaleString()}</p>}
          {status?.last_workspace_refresh && <p>Last Refresh: {new Date(status.last_workspace_refresh).toLocaleString()}</p>}
        </div>
      </div>

      {/* Settings Form */}
      <div className="card">
        <h2 className="font-semibold text-gray-700 mb-4">Business Settings</h2>
        <form onSubmit={handleSubmit((v) => saveMutation.mutate(v))} className="space-y-4 max-w-md">
          <div>
            <label className="form-label">Business Name</label>
            <input className="form-input" {...register('business_name')} />
          </div>
          <div>
            <label className="form-label">Currency</label>
            <select className="form-input" {...register('currency')}>
              <option value="GHS">GHS – Ghana Cedi</option>
              <option value="USD">USD – US Dollar</option>
              <option value="EUR">EUR – Euro</option>
              <option value="GBP">GBP – British Pound</option>
              <option value="NGN">NGN – Nigerian Naira</option>
            </select>
          </div>
          <div>
            <label className="form-label">Google Sheet ID</label>
            <input className="form-input font-mono text-xs" {...register('google_sheet_id')} placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms" />
            <p className="text-xs text-gray-400 mt-1">The ID from your Google Sheet URL (between /d/ and /edit).</p>
          </div>
          <button type="submit" className="btn-primary" disabled={saveMutation.isPending}>
            <Save size={15} /> {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
          </button>
        </form>
      </div>
    </div>
  )
}
