import type { Upcoming } from '../lib/upcoming'
import ClaudeMarker, { ClaudeChip, NOT_COUNTED_TEXT } from './changes/ClaudeMarker'

/**
 * The label side of a coming-up row, shared by Home and Cashflow so both
 * show the same marks (ux spec section 2): Claude's change, and that planned
 * income isn't counted until it arrives. On Home the whole card is a link,
 * so the marker is plain text there (`linkMarker` false).
 */
export default function UpcomingLabel({ item, linkMarker }: { item: Upcoming; linkMarker: boolean }) {
  return (
    <span className="min-w-0 flex-1">
      <span className="block text-slate-300 truncate">{item.label}</span>
      {item.claudeAuditId && (linkMarker ? <ClaudeMarker auditId={item.claudeAuditId} /> : <ClaudeChip />)}
      {item.plannedIncome && <span className="block text-xs text-slate-400">{NOT_COUNTED_TEXT}</span>}
    </span>
  )
}
