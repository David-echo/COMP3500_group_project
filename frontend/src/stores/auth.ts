import { defineStore } from 'pinia'
import { api, getToken, setToken, type User } from '../api'

export const useAuth = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    loading: false,
  }),
  getters: {
    isLoggedIn: (s) => !!s.user,
    isAdmin: (s) => s.user?.role === 'ADMIN',
    isStaff: (s) => s.user?.role === 'ADMIN' || s.user?.role === 'AUDITOR',
  },
  actions: {
    async login(studentId: string, password: string) {
      const r = await api.login(studentId, password)
      setToken(r.access_token)
      this.user = r.user
    },
    async restore() {
      if (!getToken()) return
      try {
        this.user = await api.me()
      } catch {
        setToken(null)
        this.user = null
      }
    },
    logout() {
      setToken(null)
      this.user = null
    },
  },
})
