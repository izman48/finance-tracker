import { useState } from 'react'
import { authApi } from '../services/api'

export default function DeleteAccountModal({ onClose }: { onClose: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async () => {
    setError('')
    setDeleting(true)
    try {
      await authApi.deleteAccount(password)
      localStorage.removeItem('token')
      window.location.href = '/'
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete account')
      setDeleting(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-neg mb-2">Delete account</h3>
        <p className="text-sm text-slate-400 mb-4">
          This permanently deletes your account, bank connections, accounts, and every
          transaction. There is no undo. Enter your password to confirm.
        </p>

        {error && <div className="banner-err mb-3">{error}</div>}

        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Current password"
          className="input mb-4"
          autoFocus
        />

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button onClick={handleDelete} disabled={deleting || !password} className="btn-danger">
            {deleting ? 'Deleting…' : 'Delete everything'}
          </button>
        </div>
      </div>
    </div>
  )
}
