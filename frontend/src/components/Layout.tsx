import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Users, FileText, Package,
  AlertCircle, DollarSign, TrendingDown, BarChart2,
  Settings, RefreshCw, Sheet, LogOut,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import api from '@/lib/api'
import toast from 'react-hot-toast'

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

  const handleLogout = () => {
    clear()
    navigate('/login')
  }

  const handleRefresh = async () => {
    try {
      await api.post('/sync/refresh-workspace')
      toast.success('Workspace refreshed from Supabase')
      window.location.reload()
    } catch {
      toast.error('Refresh failed')
    }
  }

  const handleSync = async () => {
    try {
      await api.post('/sync/to-sheets')
      toast.success('Sync to Google Sheets started…')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Sync failed')
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
          <button onClick={handleRefresh} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
            <RefreshCw size={16} /> Refresh Workspace
          </button>
          <button onClick={handleSync} className="flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
            <Sheet size={16} /> Sync to Sheets
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
    </div>
  )
}
