import { useState, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import AuthShell from '../components/ui/AuthShell'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      await login(email, password)
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
