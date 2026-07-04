import { useState } from 'react'
import { Copy, Check, ShieldAlert } from 'lucide-react'

/**
 * One-time recovery code display. Shown exactly once (signup, encryption
 * upgrade at login, or a reset that reissued the key) — the code wraps the
 * user's data-encryption key and is never stored in a recoverable form.
 * Continue stays disabled until the user confirms they saved it.
 */
export default function RecoveryCodeCard({
  code,
  continueLabel = 'Continue',
  onContinue,
}: {
  code: string
  continueLabel?: string
  onContinue: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [acknowledged, setAcknowledged] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard unavailable (e.g. non-secure context) — user can select it.
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 text-sm text-slate-300">
        <ShieldAlert className="w-5 h-5 text-warn shrink-0 mt-0.5" />
        <p>
          Your data is encrypted with a key only you can unlock. This recovery
          code is the <span className="font-semibold text-slate-100">only</span>{' '}
          way back in if you forget your password — we can't see it, store it,
          or resend it.
        </p>
      </div>

      <div className="card p-4 bg-white/[0.03]">
        <div className="font-mono text-sm sm:text-base text-accent tracking-wider break-all select-all text-center">
          {code}
        </div>
        <button onClick={copy} className="btn-ghost w-full mt-3">
          {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
          {copied ? 'Copied' : 'Copy code'}
        </button>
      </div>

      <p className="text-xs text-slate-500">
        Losing both your password and this code means your synced bank data
        cannot be recovered (you'd reconnect your bank and start fresh).
      </p>

      <label className="flex items-start gap-2.5 text-sm text-slate-300 cursor-pointer">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(e) => setAcknowledged(e.target.checked)}
          className="mt-0.5 accent-emerald-400"
        />
        I've saved my recovery code somewhere safe
      </label>

      <button
        onClick={onContinue}
        disabled={!acknowledged}
        className="btn-primary w-full !py-3 disabled:opacity-40"
      >
        {continueLabel}
      </button>
    </div>
  )
}
