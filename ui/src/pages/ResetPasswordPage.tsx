import { useState, FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../services/api'
import AuthShell from '../components/ui/AuthShell'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

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
      await authApi.resetPassword(token, password)
      setDone(true)
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosError = err as { response?: { data?: { detail?: string } } }
        setError(axiosError.response?.data?.detail || 'Reset failed — the link may have expired.')
      } else {
        setError('Reset failed — the link may have expired.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  if (!token) {
    return (
      <AuthShell title="Invalid link" subtitle="This reset link is missing its token.">
        <p className="text-center">
          <Link to="/forgot-password" className="btn-link">
            Request a new one
          </Link>
        </p>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Choose a new password">
      {done ? (
        <div className="text-center">
          <div className="banner-ok mb-4">Password updated.</div>
          <Link to="/login" className="btn-link">
            Log in with your new password
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="banner-err">{error}</div>}

          <div>
            <label className="label">New password</label>
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
            <label className="label">Confirm new password</label>
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
            {isLoading ? 'Saving…' : 'Set new password'}
          </button>
        </form>
      )}
    </AuthShell>
  )
}
