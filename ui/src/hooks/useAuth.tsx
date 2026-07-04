import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from 'react'
import { authApi, bankingAPI } from '../services/api'

interface User {
  id: string
  email: string
}

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  /** True while the post-login bank sync is running (shown in the layout). */
  isSyncing: boolean
  /** Resolves to a one-time recovery code when login provisioned encryption
   *  for a pre-existing account (show it before navigating), else null. */
  login: (email: string, password: string) => Promise<string | null>
  /** Resolves to the one-time recovery code — show it, require acknowledgement. */
  register: (email: string, password: string) => Promise<string>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSyncing, setIsSyncing] = useState(false)

  // Check for existing token on mount
  useEffect(() => {
    const token = localStorage.getItem('token')
    if (token) {
      authApi
        .me()
        .then((res) => setUser(res.data))
        .catch(() => localStorage.removeItem('token'))
        .finally(() => setIsLoading(false))
    } else {
      setIsLoading(false)
    }
  }, [])

  // Bank data can only be pulled while the user's encryption key is in
  // session, so sync happens here at login (there is no background worker).
  // Fire-and-forget: pages refresh as data lands; failures are non-fatal.
  const syncAfterLogin = async () => {
    setIsSyncing(true)
    try {
      const status = await bankingAPI.getConnectionStatus()
      if (status.data?.is_connected) {
        await bankingAPI.syncAccounts()
        await bankingAPI.syncTransactions(90)
      }
    } catch {
      // No connections / transient sync error: the dashboard still loads and
      // the user can sync manually.
    } finally {
      setIsSyncing(false)
    }
  }

  const login = async (email: string, password: string) => {
    const response = await authApi.login(email, password)
    localStorage.setItem('token', response.data.access_token)
    const userResponse = await authApi.me()
    setUser(userResponse.data)
    void syncAfterLogin()
    return response.data.recovery_code ?? null
  }

  const register = async (email: string, password: string) => {
    const res = await authApi.register(email, password)
    await login(email, password)
    return res.data.recovery_code
  }

  const logout = () => {
    localStorage.removeItem('token')
    setUser(null)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        isSyncing,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- provider + hook intentionally share a file
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
