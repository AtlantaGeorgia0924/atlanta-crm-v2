import axios from 'axios'
import { useAuthStore } from '@/store/authStore'

// In development Vite proxies /api -> localhost:8000 (vite.config.ts).
// VITE_API_BASE_URL is the production name; VITE_API_URL remains supported
// for older deployments.
export const apiBaseUrl = String(
  import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '',
).trim().replace(/\/$/, '')

const api = axios.create({
  baseURL: apiBaseUrl || '/api',
})

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (r) => r,
  async (err) => {
    const requestUrl = String(err?.config?.url ?? '')
    const isAuthRequest = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/signup')
    const isRefreshRequest = requestUrl.includes('/auth/refresh')

    if (err.response?.status === 401 && !isAuthRequest && !isRefreshRequest) {
      const state = useAuthStore.getState()
      const refreshToken = state.refreshToken

      if (refreshToken && !err.config?._retry) {
        try {
          err.config._retry = true
          const refreshRes = await api.post('/auth/refresh', { refresh_token: refreshToken })
          const newAccessToken = refreshRes.data?.access_token
          const newRefreshToken = refreshRes.data?.refresh_token ?? refreshToken
          if (newAccessToken && state.user) {
            useAuthStore.getState().setAuth(newAccessToken, state.user, newRefreshToken)
            err.config.headers = err.config.headers || {}
            err.config.headers.Authorization = `Bearer ${newAccessToken}`
            return api.request(err.config)
          }
        } catch {
          // fall through to forced logout
        }
      }

      useAuthStore.getState().clear()
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export default api
