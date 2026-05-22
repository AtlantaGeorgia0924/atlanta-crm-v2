import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import Layout from '@/components/Layout'
import LoginPage from '@/pages/LoginPage'
import Dashboard from '@/pages/Dashboard'
import Clients from '@/pages/Clients'
import Billing from '@/pages/Billing'
import Inventory from '@/pages/Inventory'
import Debtors from '@/pages/Debtors'
import DebtorDetails from '@/pages/DebtorDetails'
import Expenses from '@/pages/Expenses'
import Allowances from '@/pages/Allowances'
import CashFlow from '@/pages/CashFlow'
import Settings from '@/pages/Settings'
import CashFlowAudit from '@/pages/CashFlowAudit'
import UsersPage from '@/pages/Users'

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return children
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const user = useAuthStore((s) => s.user)
  if (!user || user.role !== 'admin') return <Navigate to="/dashboard" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard"   element={<Dashboard />} />
          <Route path="clients"     element={<Clients />} />
          <Route path="billing"     element={<Billing />} />
          <Route path="inventory"   element={<Inventory />} />
          <Route path="debtors"     element={<RequireAdmin><Debtors /></RequireAdmin>} />
          <Route path="debtors/:clientName" element={<RequireAdmin><DebtorDetails /></RequireAdmin>} />
          <Route path="expenses"    element={<RequireAdmin><Expenses /></RequireAdmin>} />
          <Route path="allowances"  element={<RequireAdmin><Allowances /></RequireAdmin>} />
          <Route path="cashflow"    element={<RequireAdmin><CashFlow /></RequireAdmin>} />
          <Route path="cashflow/audit" element={<RequireAdmin><CashFlowAudit /></RequireAdmin>} />
          <Route path="settings"    element={<RequireAdmin><Settings /></RequireAdmin>} />
          <Route path="users"       element={<RequireAdmin><UsersPage /></RequireAdmin>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
