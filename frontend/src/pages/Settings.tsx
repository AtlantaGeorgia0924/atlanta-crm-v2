import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useEffect, useState } from 'react'
import api from '@/lib/api'
import LoadingSpinner from '@/components/LoadingSpinner'
import Modal from '@/components/Modal'
import toast from 'react-hot-toast'
import { Save, Copy, Bug } from 'lucide-react'

interface SettingsMap {
  business_name?: string
  currency?: string
  google_sheet_id?: string
  google_sheet_id_stocks?: string
  google_sheet_id_services?: string
  last_sync_at?: string
  last_workspace_refresh?: string
}

export default function Settings() {
  const qc = useQueryClient()
  const [confirmSyncOpen, setConfirmSyncOpen] = useState(false)
  const [countdown, setCountdown] = useState(5)
  const [debugModalOpen, setDebugModalOpen] = useState(false)
  const [debugData, setDebugData] = useState<Record<string, any> | null>(null)

  useEffect(() => {
    if (!confirmSyncOpen) return
    setCountdown(5)
    const timer = setInterval(() => {
      setCountdown((prev) => (prev > 0 ? prev - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [confirmSyncOpen])
  const { data, isLoading } = useQuery<SettingsMap>({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings').then((r) => r.data),
  })

  const { register, handleSubmit } = useForm<SettingsMap>({ values: data })

  const saveMutation = useMutation({
    mutationFn: async (values: SettingsMap) => {
      const editableEntries: Array<[keyof SettingsMap, string]> = [
        ['business_name', values.business_name ?? ''],
        ['currency', values.currency ?? 'NGN'],
        ['google_sheet_id_stocks', values.google_sheet_id_stocks ?? ''],
        ['google_sheet_id_services', values.google_sheet_id_services ?? ''],
        // Legacy single-sheet key retained for backward compatibility.
        ['google_sheet_id', values.google_sheet_id ?? ''],
      ]
      await Promise.all(
        editableEntries.map(([key, value]) =>
          api.put(`/settings/${key}`, undefined, { params: { value: String(value ?? '') } })
        )
      )
    },
    onSuccess: () => {
      toast.success('Settings saved')
      if (data?.currency) {
        localStorage.setItem('currency', data.currency)
      }
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['system-status'] })
    },
    onError: () => toast.error('Save failed'),
  })

  const syncMutation = useMutation({
    mutationFn: () => api.post('/sync/to-sheets').then((r) => r.data),
    onSuccess: (res: any) => {
      const sheetCount = Array.isArray(res?.sheets_updated) ? res.sheets_updated.length : 0
      const rowsWritten = res?.rows_written && typeof res.rows_written === 'object'
        ? Object.entries(res.rows_written)
            .map(([name, count]) => `${name}: ${count}`)
            .join(' | ')
        : ''
      const syncTime = res?.sync_timestamp ? new Date(res.sync_timestamp).toLocaleString() : ''
      const detailParts = [
        sheetCount ? `${sheetCount} sheets updated` : '',
        rowsWritten,
        syncTime ? `at ${syncTime}` : '',
      ].filter(Boolean)
      toast.success(detailParts.join(' • ') || 'Sync completed')
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['system-status'] })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Sync failed'),
  })

  const debugMutation = useMutation({
    mutationFn: () => api.get('/debug/google-sheets').then((r) => r.data),
    onSuccess: (res: any) => {
      setDebugData(res)
      setDebugModalOpen(true)
      toast.success('Debug data loaded')
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Debug request failed'),
  })

  const { data: status } = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.get('/settings/status').then((r) => r.data),
    refetchInterval: 30_000,
  })

  if (isLoading) return <LoadingSpinner />

  if (data?.currency) {
    localStorage.setItem('currency', data.currency)
  }

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
              <option value="NGN">NGN – Nigerian Naira</option>
              <option value="GHS">GHS – Ghana Cedi</option>
              <option value="USD">USD – US Dollar</option>
              <option value="EUR">EUR – Euro</option>
              <option value="GBP">GBP – British Pound</option>
            </select>
          </div>
          <div>
            <label className="form-label">Stocks Sheet ID</label>
            <input className="form-input font-mono text-xs" {...register('google_sheet_id_stocks')} placeholder="Spreadsheet ID for Stocks workbook" />
            <p className="text-xs text-gray-400 mt-1">Used for Inventory tab sync.</p>
          </div>
          <div>
            <label className="form-label">Services Sheet ID</label>
            <input className="form-input font-mono text-xs" {...register('google_sheet_id_services')} placeholder="Spreadsheet ID for Services workbook" />
            <p className="text-xs text-gray-400 mt-1">Used for Services, Clients, Expenses, Cash Flow, and Allowance tabs.</p>
          </div>
          <div>
            <label className="form-label">Legacy Single Sheet ID (Optional)</label>
            <input className="form-input font-mono text-xs" {...register('google_sheet_id')} placeholder="Only for backward compatibility" />
            <p className="text-xs text-gray-400 mt-1">Only needed if you still run a single-sheet setup.</p>
          </div>
          <button type="submit" className="btn-primary" disabled={saveMutation.isPending}>
            <Save size={15} /> {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setConfirmSyncOpen(true)}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? 'Syncing…' : 'Sync to Google Sheets'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => debugMutation.mutate()}
            disabled={debugMutation.isPending}
          >
            <Bug size={15} /> {debugMutation.isPending ? 'Loading…' : 'Debug Google Sheets'}
          </button>
        </form>
      </div>

      <Modal
        title="Please Confirm"
        open={confirmSyncOpen}
        onClose={() => {
          if (!syncMutation.isPending) setConfirmSyncOpen(false)
        }}
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-700">This will overwrite the selected Google Sheets with the latest Supabase data. Continue?</p>
          <p className="text-xs text-gray-500">Confirm enabled in {countdown}s</p>
          <div className="flex gap-2 justify-end">
            <button
              type="button"
              className="btn-secondary"
              disabled={syncMutation.isPending}
              onClick={() => setConfirmSyncOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={countdown > 0 || syncMutation.isPending}
              onClick={() => {
                syncMutation.mutate()
                setConfirmSyncOpen(false)
              }}
            >
              {syncMutation.isPending ? 'Syncing…' : 'Confirm'}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        title="Google Sheets Debug Information"
        open={debugModalOpen}
        onClose={() => setDebugModalOpen(false)}
      >
        <div className="space-y-4">
          {debugData && (
            <>
              <div className="bg-gray-100 rounded p-4 max-h-96 overflow-y-auto">
                <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap break-words">
                  {JSON.stringify(debugData, null, 2)}
                </pre>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    navigator.clipboard.writeText(JSON.stringify(debugData, null, 2))
                    toast.success('Copied to clipboard')
                  }}
                >
                  <Copy size={15} /> Copy JSON
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => setDebugModalOpen(false)}
                >
                  Close
                </button>
              </div>
            </>
          )}
        </div>
      </Modal>
    </div>
  )
}
