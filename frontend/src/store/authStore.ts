import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// Zustand is a lightweight state manager – add it to package.json
interface AuthState {
  token: string | null
  user: { id: string; email: string } | null
  setAuth: (token: string, user: { id: string; email: string }) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      clear: () => set({ token: null, user: null }),
    }),
    { name: 'crm-auth' },
  ),
)
