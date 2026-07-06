import { useState } from 'react'
import { authApi } from '../services/api'

export default function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setError('')
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match')
      return
    }
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters')
      return
    }
    setSaving(true)
    try {
      await authApi.changePassword(currentPassword, newPassword)
      setDone(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to change password')
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-2">Change password</h3>

        {done ? (
          <>
            <div className="banner-ok mb-4">
              Password updated. Your encrypted data carries over — the same
              recovery code still works.
            </div>
            <div className="flex justify-end">
              <button onClick={onClose} className="btn-primary">
                Done
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-slate-400 mb-4">
              Your encrypted data is re-keyed to the new password automatically —
              nothing is lost, and your recovery code stays the same.
            </p>

            {error && <div className="banner-err mb-3">{error}</div>}

            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Current password"
              className="input mb-3"
              autoComplete="current-password"
              autoFocus
            />
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password"
              className="input mb-3"
              autoComplete="new-password"
            />
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              className="input mb-4"
              autoComplete="new-password"
            />

            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="btn-ghost">
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !currentPassword || !newPassword}
                className="btn-primary"
              >
                {saving ? 'Saving…' : 'Change password'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
