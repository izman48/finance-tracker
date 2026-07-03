import { useState, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import AuthShell from '../components/ui/AuthShell'
import RecoveryCodeCard from '../components/RecoveryCodeCard'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null)

  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      // A recovery code comes back when this login upgraded the account to
      // per-user encryption — hold here so it's seen (it's shown only once).
      const code = await login(email, password)
      if (code) {
        setRecoveryCode(code)
        return
      }
      navigate('/dashboard')
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosError = err as { response?: { data?: { detail?: string } } }
        setError(axiosError.response?.data?.detail || 'Login failed')
      } else {
        setError('Login failed')
      }
    } finally {
      setIsLoading(false)
    }
  }

  if (recoveryCode) {
    return (
      <AuthShell
        title="Save your recovery code"
        subtitle="Your account now has per-user encryption — this code is new."
      >
        <RecoveryCodeCard
          code={recoveryCode}
          continueLabel="I've saved it — go to my dashboard"
          onContinue={() => navigate('/dashboard')}
        />
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Welcome back" subtitle="Log in to see today's numbers.">
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <div className="banner-err">{error}</div>}

        <div>
          <label className="label">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
            autoComplete="email"
            required
          />
        </div>

        <div>
          <label className="label">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
            autoComplete="current-password"
            required
          />
        </div>

        <button type="submit" disabled={isLoading} className="btn-primary w-full !py-3">
          {isLoading ? 'Logging in…' : 'Log in'}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-400">
        Don't have an account?{' '}
        <Link to="/register" className="btn-link">
          Create one
        </Link>
      </p>
      <p className="mt-2 text-center">
        <Link to="/forgot-password" className="text-sm text-slate-500 hover:text-accent transition-colors">
          Forgot password?
        </Link>
      </p>
    </AuthShell>
  )
}
