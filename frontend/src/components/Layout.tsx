import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import {
  LayoutDashboard, Users, FileText, Package,
  AlertCircle, DollarSign, TrendingDown, BarChart2,
  Settings, RefreshCw, Sheet, LogOut,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import api from '@/lib/api'
import toast from 'react-hot-toast'
import Modal from '@/components/Modal'

const nav = [
  { to: '/dashboard',  label: 'Dashboard',   icon: LayoutDashboard },
  { to: '/clients',    label: 'Clients',      icon: Users },
  { to: '/billing',    label: 'Services',     icon: FileText },
  { to: '/inventory',  label: 'Inventory',    icon: Package },
  { to: '/debtors',    label: 'Debtors',      icon: AlertCircle },
  { to: '/expenses',   label: 'Expenses',     icon: TrendingDown },
  { to: '/allowances', label: 'Allowances',   icon: DollarSign },
  { to: '/cashflow',   label: 'Cash Flow',    icon: BarChart2 },
  { to: '/settings',   label: 'Settings',     icon: Settings },
]

export default function Layout() {
  const { clear, user } = useAuthStore()
  const navigate = useNavigate()
  const [pendingAction, setPendingAction] = useState<'refresh' | 'sync' | null>(null)
  const [countdown, setCountdown] = useState(5)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (!pendingAction) return
    setCountdown(5)
    const timer = setInterval(() => {
      setCountdown((prev) => (prev > 0 ? prev - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [pendingAction])

  const warningText = useMemo(() => {
    if (pendingAction === 'refresh') {
      return 'This will reload data from Google Sheets and Supabase. Continue?'
    }
    if (pendingAction === 'sync') {
      return 'This will overwrite the selected Google Sheets with the latest Supabase data. Continue?'
    }
    return ''
  }, [pendingAction])

  const handleLogout = () => {
    clear()
    navigate('/login')
  }

  const handleRefresh = async () => {
    try {
      const { data } = await api.post('/sync/refresh-workspace')
      const sheetsRead = Array.isArray(data?.sheets_read) ? data.sheets_read.join(', ') : ''
      const rowsProcessed = data?.rows_processed && typeof data.rows_processed === 'object'
        ? Object.entries(data.rows_processed)
            .map(([name, count]) => `${name}: ${count}`)
            .join(' | ')
        : ''
      const valuesCalculated = data?.values_calculated && typeof data.values_calculated === 'object'
        ? Object.entries(data.values_calculated)
            .map(([name, value]) => `${name}: ${value}`)
            .join(' | ')
        : ''
      toast.success([
        sheetsRead ? `sheets read: ${sheetsRead}` : '',
        rowsProcessed ? `rows processed: ${rowsProcessed}` : '',
        valuesCalculated ? `values calculated: ${valuesCalculated}` : '',
      ].filter(Boolean).join(' • ') || 'Workspace refreshed')
      window.location.reload()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Refresh failed')
    }
  }

  const handleSync = async () => {
    try {
      const res = await api.post('/sync/to-sheets')
      const payload = res?.data || {}
      const sheetCount = Array.isArray(payload.sheets_updated) ? payload.sheets_updated.length : 0
      const rowsWritten = payload.rows_written && typeof payload.rows_written === 'object'
        ? Object.entries(payload.rows_written)
            .map(([name, count]) => `${name}: ${count}`)
            .join(' | ')
        : ''
      const syncTime = payload.sync_timestamp ? new Date(payload.sync_timestamp).toLocaleString() : ''
      toast.success([
        sheetCount ? `${sheetCount} sheets updated` : '',
        rowsWritten,
        syncTime ? `at ${syncTime}` : '',
      ].filter(Boolean).join(' • ') || 'Sync completed')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Sync failed')
    }
  }

  const executeConfirmedAction = async () => {
    if (!pendingAction) return
    setIsSubmitting(true)
    try {
      if (pendingAction === 'refresh') {
        await handleRefresh()
      } else {
        await handleSync()
      }
      setPendingAction(null)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 bg-gray-900 text-gray-100 flex flex-col">
        <div className="px-4 py-5 border-b border-gray-700">
          <h1 className="font-bold text-lg">CRM</h1>
          <p className="text-xs text-gray-400 truncate">{user?.email}</p>
        </div>

        <nav className="flex-1 overflow-y-auto py-3 space-y-0.5 px-2">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-2 pb-4 space-y-1 border-t border-gray-700 pt-3">
          <button onClick={() => setPendingAction('refresh')} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
            <RefreshCw size={16} /> Refresh Workspace
          </button>
          <button onClick={() => setPendingAction('sync')} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
            <Sheet size={16} /> Sync to Google Sheets
          </button>
          <button onClick={handleLogout} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
            <LogOut size={16} /> Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      <Modal
        title="Please Confirm"
        open={Boolean(pendingAction)}
        onClose={() => {
          if (!isSubmitting) setPendingAction(null)
        }}
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-700">{warningText}</p>
          <p className="text-xs text-gray-500">Confirm enabled in {countdown}s</p>
          <div className="flex gap-2 justify-end">
            <button
              type="button"
              className="btn-secondary"
              disabled={isSubmitting}
              onClick={() => setPendingAction(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={countdown > 0 || isSubmitting}
              onClick={executeConfirmedAction}
            >
              {isSubmitting ? 'Working…' : 'Confirm'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
