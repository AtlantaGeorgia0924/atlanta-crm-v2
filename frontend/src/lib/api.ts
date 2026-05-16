import axios from 'axios'
import { useAuthStore } from '@/store/authStore'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api',
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
  (err) => {
    const requestUrl = String(err?.config?.url ?? '')
    const isAuthRequest = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/signup')
    if (err.response?.status === 401 && !isAuthRequest) {
      useAuthStore.getState().clear()
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export default api
