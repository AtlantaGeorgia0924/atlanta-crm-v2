import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import Layout from '@/components/Layout'
import LoginPage from '@/pages/LoginPage'
import Dashboard from '@/pages/Dashboard'
import Clients from '@/pages/Clients'
import Billing from '@/pages/Billing'
import Inventory from '@/pages/Inventory'
import Debtors from '@/pages/Debtors'
import Expenses from '@/pages/Expenses'
import Allowances from '@/pages/Allowances'
import CashFlow from '@/pages/CashFlow'
import Settings from '@/pages/Settings'

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
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
          <Route path="debtors"     element={<Debtors />} />
          <Route path="expenses"    element={<Expenses />} />
          <Route path="allowances"  element={<Allowances />} />
          <Route path="cashflow"    element={<CashFlow />} />
          <Route path="settings"    element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
