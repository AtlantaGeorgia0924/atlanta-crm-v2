import axios from 'axios'
import { useAuthStore } from '@/store/authStore'

const envBaseUrl = String(import.meta.env.VITE_API_URL ?? '').trim()
const isBrowser = typeof window !== 'undefined'
const isLocalFrontend = isBrowser && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)

function resolveApiBaseUrl(): string {
  if (!envBaseUrl) return '/api'

  const normalized = envBaseUrl.replace(/\/+$/, '')
  const pointsToLocalApi = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(normalized)
  const mixedContentRisk = isBrowser && window.location.protocol === 'https:' && /^http:\/\//i.test(normalized)

  // Never use local or insecure HTTP API from a deployed HTTPS frontend.
  if (isBrowser && !isLocalFrontend && (pointsToLocalApi || mixedContentRisk)) {
    return '/api'
  }

  return normalized
}

const api = axios.create({
  baseURL: resolveApiBaseUrl(),
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
