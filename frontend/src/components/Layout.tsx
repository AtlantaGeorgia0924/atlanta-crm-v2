import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useMemo, useState } from 'react'
import {
  LayoutDashboard, Users, FileText, Package,
  AlertCircle, DollarSign, TrendingDown, BarChart2,
  Settings, LogOut, ClipboardList, Shield, PanelLeftClose, PanelLeftOpen,
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
  { to: '/cashflow/audit', label: 'Audit Log', icon: ClipboardList },
  { to: '/settings',   label: 'Settings',     icon: Settings },
]

const staffNav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/billing', label: 'Services', icon: FileText },
  { to: '/inventory', label: 'Inventory', icon: Package },
  { to: '/debtors', label: 'Debtors', icon: AlertCircle },
  { to: '/clients', label: 'Clients', icon: Users },
]

export default function Layout() {
  const { clear, user } = useAuthStore()
  const navigate = useNavigate()
  const [pendingAction, setPendingAction] = useState<'refreshWorkspace' | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [logoFailed, setLogoFailed] = useState(false)
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('layout-sidebar-collapsed') === '1'
    } catch {
      return false
    }
  })
  const isAdmin = user?.role === 'admin'
  const navItems = isAdmin ? [...nav, { to: '/users', label: 'Users', icon: Shield }] : staffNav

  const warningText = useMemo(() => {
    if (pendingAction === 'refreshWorkspace') {
      return 'This will recalculate dashboard and financial metrics from Supabase only. Continue?'
    }
    return ''
  }, [pendingAction])

  const handleLogout = () => {
    clear()
    navigate('/login')
  }

  const toggleSidebar = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('layout-sidebar-collapsed', next ? '1' : '0')
      } catch {
        // Ignore storage failure.
      }
      return next
    })
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


  const executeConfirmedAction = async () => {
    if (!pendingAction) return
    setIsSubmitting(true)
    try {
      if (pendingAction === 'refreshWorkspace') {
        await handleRefreshWorkspace()
      }
      setPendingAction(null)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className={`${collapsed ? 'w-16' : 'w-56'} shrink-0 text-white flex flex-col transition-all duration-200`} style={{ background: '#000000' }}>
        <div className={`${collapsed ? 'px-2 py-3' : 'px-4 py-5'} border-b`} style={{ borderColor: '#3b3b3b' }}>
          <div className={`flex items-center ${collapsed ? 'justify-center' : 'justify-between gap-3'}`}>
            {!logoFailed && (
              <img
                src="/assets/atlanta-logo.jpeg"
                alt="ATLANTA GEORGIA_TECH"
                className="h-10 w-10 rounded object-cover border"
                style={{ borderColor: '#D4AF37' }}
                onError={() => setLogoFailed(true)}
              />
            )}
            {!collapsed && (
              <div>
                <h1 className="font-bold text-xs leading-tight tracking-wide">ATLANTA</h1>
                <p className="text-[11px] leading-tight text-[#D4AF37] font-semibold">GEORGIA_TECH</p>
              </div>
            )}
            {!collapsed && (
              <button
                type="button"
                className="rounded p-1 text-gray-300 hover:bg-[#D4AF37] hover:text-black"
                title="Collapse sidebar"
                onClick={toggleSidebar}
              >
                <PanelLeftClose size={16} />
              </button>
            )}
          </div>
          {collapsed ? (
            <button
              type="button"
              className="mx-auto mt-2 block rounded p-1 text-gray-300 hover:bg-[#D4AF37] hover:text-black"
              title="Expand sidebar"
              onClick={toggleSidebar}
            >
              <PanelLeftOpen size={16} />
            </button>
          ) : (
            <p className="text-xs text-gray-300 truncate">{user?.email}</p>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto py-3 space-y-0.5 px-2">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center ${collapsed ? 'justify-center' : 'gap-3'} rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'text-black'
                    : 'text-gray-200 hover:text-black hover:bg-[#D4AF37]'
                }`
              }
              style={({ isActive }) => ({ background: isActive ? '#D4AF37' : 'transparent' })}
              title={collapsed ? label : undefined}
            >
              <Icon size={16} />
              {!collapsed && label}
            </NavLink>
          ))}
        </nav>

        <div className="px-2 pb-4 space-y-1 border-t pt-3" style={{ borderColor: '#3b3b3b' }}>
          {isAdmin && (
            <button
              onClick={() => setPendingAction('refreshWorkspace')}
              className={`flex items-center ${collapsed ? 'justify-center' : 'gap-3'} w-full rounded-lg px-3 py-2 text-sm text-gray-200 hover:text-black transition-colors hover:bg-[#D4AF37]`}
              title={collapsed ? 'Refresh Workspace' : undefined}
            >
              <Settings size={16} /> {!collapsed && 'Refresh Workspace'}
            </button>
          )}
          <button
            onClick={handleLogout}
            className={`flex items-center ${collapsed ? 'justify-center' : 'gap-3'} w-full rounded-lg px-3 py-2 text-sm text-gray-200 hover:text-black transition-colors hover:bg-[#D4AF37]`}
            title={collapsed ? 'Logout' : undefined}
          >
            <LogOut size={16} /> {!collapsed && 'Logout'}
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
              disabled={isSubmitting}
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
