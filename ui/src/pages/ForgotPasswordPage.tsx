import { useState, FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../services/api'
import AuthShell from '../components/ui/AuthShell'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    try {
      await authApi.forgotPassword(email)
    } finally {
      // Always show the same confirmation — the API deliberately doesn't
      // reveal whether the email has an account.
      setSent(true)
      setIsLoading(false)
    }
  }

  return (
    <AuthShell title="Reset password" subtitle="We'll email you a link to set a new one.">
      {sent ? (
        <div className="banner-ok text-center">
          If that email has an account, a reset link is on its way. Check your inbox.
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
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
          <button type="submit" disabled={isLoading} className="btn-primary w-full !py-3">
            {isLoading ? 'Sending…' : 'Send reset link'}
          </button>
        </form>
      )}

      <p className="mt-6 text-center">
        <Link to="/login" className="btn-link">
          Back to login
        </Link>
      </p>
    </AuthShell>
  )
}
