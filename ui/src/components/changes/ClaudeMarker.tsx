import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'

/** D1: planned income is shown, never counted, until the credit lands (ux spec 2). */
export const NOT_COUNTED_TEXT = 'Not counted in your safe to spend until it arrives.'

const AUDIT_ID = /^[A-Za-z0-9-]+$/

/**
 * "Changed by Claude": links an item to its row on the changes screen
 * (ux spec section 2). The audit id comes from our API; anything that isn't
 * a plain id is not turned into a link.
 */
export default function ClaudeMarker({ auditId }: { auditId: string }) {
  if (!AUDIT_ID.test(auditId)) return null
  return (
    <Link
      to={`/changes#change-${auditId}`}
      aria-label="Changed by Claude. See what changed."
      className="inline-flex items-center shrink-0 min-h-[44px] sm:min-h-[24px]"
    >
      <span className="chip-info inline-flex items-center gap-1 px-2 py-1">
        <Sparkles className="w-3 h-3" aria-hidden="true" />
        Changed by Claude
      </span>
    </Link>
  )
}
