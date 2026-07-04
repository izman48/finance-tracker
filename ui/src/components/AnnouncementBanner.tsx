import { useState } from 'react'
import { ShieldCheck, X } from 'lucide-react'

// Bump this key to re-show the banner for a future announcement.
const DISMISS_KEY = 'announcement-dismissed-2026-07-db-reset'

export default function AnnouncementBanner() {
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISS_KEY) === '1',
  )

  if (dismissed) return null

  return (
    <div className="bg-accent/10 border-b border-accent/20">
      <div className="max-w-7xl mx-auto px-4 py-2.5 flex items-start sm:items-center gap-3 text-sm">
        <ShieldCheck className="w-4 h-4 text-accent shrink-0 mt-0.5 sm:mt-0" />
        <p className="flex-1 text-slate-300">
          <span className="font-medium text-slate-100">
            Used nilu finance before?
          </span>{' '}
          We&apos;ve reset our databases as part of a security upgrade — your
          old account and data are gone. Sign up again and reconnect your bank
          to pick back up.
        </p>
        <button
          onClick={() => {
            localStorage.setItem(DISMISS_KEY, '1')
            setDismissed(true)
          }}
          aria-label="Dismiss announcement"
          className="p-1 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-white/[0.06] transition-colors shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
