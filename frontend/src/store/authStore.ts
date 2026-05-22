import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type UserRole = 'admin' | 'staff'

export interface AuthUser {
  id: string
  email: string
  full_name?: string | null
  phone?: string | null
  role: UserRole
  is_active?: boolean
  last_login_at?: string | null
}

interface AuthState {
  token: string | null
  refreshToken: string | null
  user: AuthUser | null
  setAuth: (token: string, user: AuthUser, refreshToken?: string | null) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,
      setAuth: (token, user, refreshToken = null) => set({ token, user, refreshToken }),
      clear: () => set({ token: null, user: null, refreshToken: null }),
    }),
    { name: 'crm-auth' },
  ),
)
