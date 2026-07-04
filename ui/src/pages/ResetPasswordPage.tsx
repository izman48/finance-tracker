import { useState, FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../services/api'
import AuthShell from '../components/ui/AuthShell'
import RecoveryCodeCard from '../components/RecoveryCodeCard'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  // Set when resetting without the recovery code reissued the encryption key.
  const [newRecoveryCode, setNewRecoveryCode] = useState<string | null>(null)
  const [dataCleared, setDataCleared] = useState(false)
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
    if (!recoveryCode.trim() && !window.confirm(
      'Reset without your recovery code?\n\nYour encrypted bank data cannot be ' +
      'unlocked without it, so it will be cleared. You can rebuild it by ' +
      'reconnecting your bank afterwards.'
    )) {
      return
    }

    setIsLoading(true)
    try {
      const res = await authApi.resetPassword(token, password, recoveryCode.trim() || undefined)
      if (res.data.recovery_code) {
        setNewRecoveryCode(res.data.recovery_code)
        setDataCleared(true)
      }
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

  if (done && newRecoveryCode) {
    return (
      <AuthShell
        title="Save your new recovery code"
        subtitle="A new encryption key was issued — the old code no longer works."
      >
        <div className="banner-ok mb-4">
          Password updated. Your bank data was cleared — reconnect your bank to rebuild it.
        </div>
        <RecoveryCodeCard
          code={newRecoveryCode}
          continueLabel="I've saved it — log in"
          onContinue={() => (window.location.href = '/login')}
        />
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Choose a new password">
      {done ? (
        <div className="text-center">
          <div className="banner-ok mb-4">
            {dataCleared
              ? 'Password updated. Your bank data was cleared — reconnect your bank to rebuild it.'
              : 'Password updated.'}
          </div>
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

          <div>
            <label className="label">Recovery code</label>
            <input
              type="text"
              value={recoveryCode}
              onChange={(e) => setRecoveryCode(e.target.value)}
              className="input font-mono"
              placeholder="XXXX-XXXX-XXXX-…"
              autoComplete="off"
            />
            <p className="text-xs text-slate-500 mt-1.5">
              The code you saved at signup. It unlocks your encrypted data so
              nothing is lost. Without it, your synced bank data is cleared and
              rebuilt by reconnecting your bank.
            </p>
          </div>

          <button type="submit" disabled={isLoading} className="btn-primary w-full !py-3">
            {isLoading ? 'Saving…' : 'Set new password'}
          </button>
        </form>
      )}
    </AuthShell>
  )
}
