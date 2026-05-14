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
  const [pendingAction, setPendingAction] = useState<'refreshSheets' | 'refreshWorkspace' | 'sync' | null>(null)
  const [countdown, setCountdown] = useState(5)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [logoFailed, setLogoFailed] = useState(false)

  useEffect(() => {
    if (!pendingAction) return
    setCountdown(5)
    const timer = setInterval(() => {
      setCountdown((prev) => (prev > 0 ? prev - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [pendingAction])

  const warningText = useMemo(() => {
    if (pendingAction === 'refreshSheets') {
      return 'This will import latest Services, Inventory and Clients from Google Sheets into Supabase. Continue?'
    }
    if (pendingAction === 'refreshWorkspace') {
      return 'This will recalculate dashboard and financial metrics from Supabase only. Continue?'
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

  const handleRefreshFromSheets = async () => {
    try {
      const { data } = await api.post('/sync/refresh-from-google-sheets')
      const sheetsRead = Array.isArray(data?.sheets_read) ? data.sheets_read.join(', ') : ''
      const rowsProcessed = data?.rows_processed && typeof data.rows_processed === 'object'
        ? Object.entries(data.rows_processed)
            .map(([name, count]) => `${name}: ${count}`)
            .join(' | ')
        : ''
      const rowsUpserted = data?.rows_upserted && typeof data.rows_upserted === 'object'
        ? Object.entries(data.rows_upserted)
            .map(([name, count]) => `${name}: ${count}`)
            .join(' | ')
        : ''
      const valuesCalculated = data?.values_calculated && typeof data.values_calculated === 'object'
        ? Object.entries(data.values_calculated)
            .map(([name, value]) => `${name}: ${typeof value === 'object' ? JSON.stringify(value) : value}`)
            .join(' | ')
        : ''
      toast.success([
        sheetsRead ? `sheets read: ${sheetsRead}` : '',
        rowsProcessed ? `rows processed: ${rowsProcessed}` : '',
        rowsUpserted ? `rows upserted: ${rowsUpserted}` : '',
        valuesCalculated ? `values calculated: ${valuesCalculated}` : '',
      ].filter(Boolean).join(' • ') || 'Google Sheets imported')
      window.location.reload()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Google Sheets refresh failed')
    }
  }

  const handleRefreshWorkspace = async () => {
    try {
      const { data } = await api.post('/sync/refresh-workspace')
      const valuesCalculated = data?.values_calculated && typeof data.values_calculated === 'object'
        ? Object.entries(data.values_calculated)
            .map(([name, value]) => `${name}: ${typeof value === 'object' ? JSON.stringify(value) : value}`)
            .join(' | ')
        : ''
      toast.success(valuesCalculated || 'Workspace refreshed from Supabase')
      window.location.reload()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Workspace refresh failed')
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
      if (pendingAction === 'refreshSheets') {
        await handleRefreshFromSheets()
      } else if (pendingAction === 'refreshWorkspace') {
        await handleRefreshWorkspace()
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
      <aside className="w-56 shrink-0 text-white flex flex-col" style={{ background: '#000000' }}>
        <div className="px-4 py-5 border-b" style={{ borderColor: '#3b3b3b' }}>
          <div className="flex items-center gap-3">
            {!logoFailed && (
              <img
                src="/assets/atlanta-logo.jpeg"
                alt="ATLANTA GEORGIA_TECH"
                className="h-10 w-10 rounded object-cover border"
                style={{ borderColor: '#D4AF37' }}
                onError={() => setLogoFailed(true)}
              />
            )}
            <div>
              <h1 className="font-bold text-xs leading-tight tracking-wide">ATLANTA</h1>
              <p className="text-[11px] leading-tight text-[#D4AF37] font-semibold">GEORGIA_TECH</p>
            </div>
          </div>
          <p className="text-xs text-gray-300 truncate">{user?.email}</p>
        </div>

        <nav className="flex-1 overflow-y-auto py-3 space-y-0.5 px-2">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'text-black'
                    : 'text-gray-200 hover:text-black'
                }`
              }
              style={({ isActive }) => ({ background: isActive ? '#D4AF37' : 'transparent' })}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-2 pb-4 space-y-1 border-t pt-3" style={{ borderColor: '#3b3b3b' }}>
          <button onClick={() => setPendingAction('refreshSheets')} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-200 hover:text-black transition-colors hover:bg-[#D4AF37]">
            <RefreshCw size={16} /> Refresh from Google Sheets
          </button>
          <button onClick={() => setPendingAction('refreshWorkspace')} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-200 hover:text-black transition-colors hover:bg-[#D4AF37]">
            <RefreshCw size={16} /> Refresh Workspace
          </button>
          <button onClick={() => setPendingAction('sync')} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-200 hover:text-black transition-colors hover:bg-[#D4AF37]">
            <Sheet size={16} /> Sync to Google Sheets
          </button>
          <button onClick={handleLogout} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-200 hover:text-black transition-colors hover:bg-[#D4AF37]">
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
