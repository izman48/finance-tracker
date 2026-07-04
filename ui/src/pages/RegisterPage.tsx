import { useState, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import AuthShell from '../components/ui/AuthShell'
import RecoveryCodeCard from '../components/RecoveryCodeCard'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null)

  const { register } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }

    setIsLoading(true)

    try {
      // The account is created and logged in, but hold at the recovery-code
      // screen until it's acknowledged — it is shown exactly once.
      setRecoveryCode(await register(email, password))
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosError = err as { response?: { data?: { detail?: string } } }
        setError(axiosError.response?.data?.detail || 'Registration failed')
      } else {
        setError('Registration failed')
      }
    } finally {
      setIsLoading(false)
    }
  }

  if (recoveryCode) {
    return (
      <AuthShell
        title="Save your recovery code"
        subtitle="Your account is ready — this is the one thing to keep safe."
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
    <AuthShell title="Create your account" subtitle="Free, self-hosted, and your data stays yours.">
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
            autoComplete="new-password"
            required
          />
        </div>

        <div>
          <label className="label">Confirm password</label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="input"
            autoComplete="new-password"
            required
          />
        </div>

        <button type="submit" disabled={isLoading} className="btn-primary w-full !py-3">
          {isLoading ? 'Creating account…' : 'Create account'}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-400">
        Already have an account?{' '}
        <Link to="/login" className="btn-link">
          Log in
        </Link>
      </p>
    </AuthShell>
  )
}
